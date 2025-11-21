# invoices/models.py
from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, timedelta
from django.db import models, transaction
from django.db.models import Sum, Q
from django.utils.timezone import localdate, now
from clients.models import Client
from orders.models import Order
from credit.models import CreditEntry  
from collections import defaultdict
from calendar import monthrange
import math
from typing import Callable, Optional, Tuple
from django.conf import settings



def r2(x: Decimal | None) -> Decimal:
    """Round to 2 decimals, treating None as 0.00."""
    if x is None:
        return Decimal("0.00")
    return Decimal(x).quantize(Decimal("0.01"))


class Invoice(models.Model):
    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name="invoice"
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="invoices"
    )

    STATUS_CHOICES = [
        ("unpaid", "Unpaid"),
        ("partial", "Partially Paid"),
        ("paid", "Paid"),
        ("overdue", "Overdue"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="unpaid")
    invoice_date = models.DateField(default=localdate)
    due_date = models.DateField(null=True, blank=True)

    paid_date = models.DateField(
        null=True, blank=True, db_index=True,
        help_text="Date invoice reached fully-paid deposit status.",
    )

    # Snapshots
    order_total_inc   = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_due        = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))  # deposit due
    deposit_required  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    deposit_paid      = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit_used       = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))  # planned 70%

    # Deprecated shim
    credit_usage_applied = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="(Deprecated) Old delta tracker when pushing to ledger directly.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Only customer cash toward deposit counts here (exclude funder cash/credit events).
    PAYMENT_TYPES = {"payment", "refund"}

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["invoice_date"]),
            models.Index(fields=["client", "status"]),
        ]

    def __str__(self) -> str:
        return f"Invoice #{self.id or '—'} · {self.client} · {self.status}"

    # ---------- Core logic ----------

    def calculate_totals(self) -> None:
        """
        Compute deposit/credit snapshots from the linked order & client.
        CREDIT clients (ACTIVE):
          - 30% upfront cash deposit, 70% planned on credit ledger.
        Non-credit:
          - 100% upfront cash deposit, 0 credit.
        (NOTE) We only *post* credit once deposit is fully paid; see can_release_credit().
        """
        total = r2(self.order.grand_total_inc)
        self.order_total_inc = total

        if self.client.account_type == "CREDIT" and self.client.credit_status == "ACTIVE":
            self.deposit_required = r2(total * Decimal("0.30"))
            self.credit_used = r2(total - self.deposit_required)  # planned 70%
            self.amount_due = self.deposit_required
            if not self.due_date:
                self.due_date = localdate() + timedelta(days=3)
        else:
            self.deposit_required = total
            self.credit_used = Decimal("0.00")
            self.amount_due = total
            if not self.due_date:
                self.due_date = localdate()

    @classmethod
    def create_for_order(cls, order: Order) -> "Invoice":
        """
        Create or update the invoice for an approved order and keep the 'invoice' Transaction
        in sync. Do NOT post credit yet; credit is only posted once the deposit is fully paid.
        """
        if hasattr(order, "invoice"):
            inv: "Invoice" = order.invoice
            inv.calculate_totals()
            inv.save(update_fields=[
                "order_total_inc", "amount_due", "deposit_required",
                "credit_used", "due_date", "updated_at",
            ])
            inv.ensure_invoice_out_txn()
            # Gate credit posting behind deposit being fully paid:
            inv.ensure_credit_after_deposit()
            return inv

        with transaction.atomic():
            invoice = cls(order=order, client=order.client)
            invoice.calculate_totals()
            invoice.save()
            invoice.ensure_invoice_out_txn()
            # Gate credit posting behind deposit being fully paid:
            invoice.ensure_credit_after_deposit()
            return invoice

    # ---------- Credit release gating ----------

    def can_release_credit(self) -> bool:
        """
        Only release/post credit (usage ledger + funder cash-in) when:
         - client is an ACTIVE credit client, AND
         - the invoice deposit is fully paid (status==paid or deposit_paid >= amount_due).
        """
        is_credit_client = (self.client.account_type == "CREDIT" and self.client.credit_status == "ACTIVE")
        return is_credit_client and self.is_fully_paid()

    def ensure_credit_after_deposit(self):
        """
        Create/update OR remove credit artefacts to match the current deposit state:
         - If can_release_credit() -> ensure usage ledger + credit_issue txn exist at 'credit_used'.
         - Else                   -> remove any existing usage ledger + credit_issue txn.
        """
        if self.can_release_credit():
            self.ensure_credit_issue_txn()
            self.ensure_credit_usage_entry()
        else:
            self.remove_credit_issue_txn()
            self.remove_credit_usage_entry()

    # ---------- Transaction helpers (lazy imports to avoid circulars) ----------

    def ensure_invoice_out_txn(self):
        """
        Ensure exactly one 'invoice' transaction exists for this invoice,
        with the current invoice total. If it exists, keep the amount in sync.
        """
        from transactions.models import Transaction  # lazy import

        if not self.pk:
            self.save()

        txn, created = Transaction.objects.get_or_create(
            invoice=self,
            transaction_type="invoice",
            defaults={
                "client": self.client,
                "amount": self.order_total_inc,
                "reference": f"INV-{self.id}",
                "note": "Invoice issued",
            },
        )
        if not created and txn.amount != self.order_total_inc:
            txn.amount = self.order_total_inc
            txn.save(update_fields=["amount"])
        return txn

    def ensure_credit_issue_txn(self):
        """
        Ensure one cash-in Transaction(type='credit_issue') exists equal to credit_used,
        BUT ONLY when can_release_credit() is True. Otherwise, ensure none exist.
        """
        from transactions.models import Transaction  # lazy import

        if not self.pk:
            self.save()

        if not self.can_release_credit():
            self.remove_credit_issue_txn()
            return None

        target = r2(self.credit_used or Decimal("0.00"))
        if target == Decimal("0.00"):
            self.remove_credit_issue_txn()
            return None

        tx = Transaction.objects.filter(invoice=self, transaction_type="credit_issue").first()
        if tx:
            changed = False
            if r2(tx.amount) != target:
                tx.amount = target
                changed = True
            if not tx.reference:
                tx.reference = f"INV-{self.id} credit funded"
                changed = True
            if not tx.note:
                tx.note = "Funder covered credit portion"
                changed = True
            if changed:
                tx.save(update_fields=["amount", "reference", "note"])
            return tx

        return Transaction.objects.create(
            client=self.client,
            invoice=self,
            transaction_type="credit_issue",
            amount=target,
            reference=f"INV-{self.id} credit funded",
            note="Funder covered credit portion",
        )

    def remove_credit_issue_txn(self):
        """Delete any existing 'credit_issue' transaction for this invoice."""
        from transactions.models import Transaction  # lazy import
        q = Transaction.objects.filter(invoice=self, transaction_type="credit_issue")
        for tx in q.order_by("-created_at", "-id"):
            tx.delete()

    # ---- Ledger-first: maintain a single USAGE entry per invoice ----

    def ensure_credit_usage_entry(self):
        """
        Ensure exactly one CreditEntry.USAGE exists for this invoice whose amount equals
        invoice.credit_used, BUT ONLY when can_release_credit() is True; else ensure none.
        Adjusting/deleting the entry auto-updates CreditAccount via CreditEntry signals.
        """
        if not self.pk:
            self.save()

        if not self.can_release_credit():
            self.remove_credit_usage_entry()
            return None

        target = r2(self.credit_used or Decimal("0.00"))
        if target == Decimal("0.00"):
            self.remove_credit_usage_entry()
            return None

        entry = (
            CreditEntry.objects
            .filter(invoice=self, kind=CreditEntry.USAGE, credit_account__client=self.client)
            .order_by("-posted_at", "-id")
            .first()
        )

        if entry:
            if r2(entry.amount) != target:
                entry.amount = target
                entry.posted_at = now()
                entry.save(update_fields=["amount", "posted_at"])
            return entry

        return CreditEntry.record_usage(
            client=self.client,
            amount=target,
            invoice=self,
            reference=f"INV-{self.id} credit usage",
            note="Credit portion of invoice (released after deposit paid)",
        )

    def remove_credit_usage_entry(self):
        """Delete any USAGE ledger entries tied to this invoice (signals reverse the account)."""
        for ce in self.credit_entries.filter(kind=CreditEntry.USAGE).order_by("-posted_at", "-id"):
            ce.delete()

    # --- payments & status (cash deposit side) ---

    def recalc_deposit_from_transactions(self, save: bool = True) -> None:
        """
        Recompute deposit_paid from all *cash-like* transactions on this invoice,
        then update status accordingly, and sync credit release/removal.
        """
        total_in = (
            self.transactions
            .filter(transaction_type__in=self.PAYMENT_TYPES)
            .aggregate(s=Sum("amount"))["s"]
            or Decimal("0.00")
        )
        self.deposit_paid = r2(total_in)
        self.update_status(save=save)

        # After status change, ensure credit artefacts match current state.
        self.ensure_credit_after_deposit()

    def record_payment(
        self,
        amount: Decimal,
        *,
        reference: str = "",
        note: str = "",
        when=None,
    ) -> None:
        """
        Create a 'payment' (cash) transaction toward the deposit, then recompute
        deposit_paid/status and (if now fully paid) release credit.
        """
        from transactions.models import Transaction  # lazy import

        amt = r2(Decimal(amount))
        if amt <= 0:
            raise ValueError("Amount must be a positive decimal.")

        # Ensure the invoice-out row exists first
        self.ensure_invoice_out_txn()

        Transaction.objects.create(
            client=self.client,
            invoice=self,
            transaction_type="payment",
            amount=amt,
            reference=reference or f"INV-{self.id} payment",
            note=note,
            created_at=when or now(),
        )

        # Refresh deposit snapshot & status
        self.recalc_deposit_from_transactions(save=True)

        # If now fully paid (deposit side), persist paid_date to the actual calendar day
        if self.status == "paid":
            payment_day = (when or now()).date()
            if self.paid_date != payment_day:
                self.paid_date = payment_day
                self.save(update_fields=["paid_date", "updated_at"])

        # Ensure credit artefacts reflect the (possibly new) state
        self.ensure_credit_after_deposit()

    # --- credit repayments (ledger side only) ---

    def record_credit_repayment(
        self,
        amount: Decimal,
        *,
        reference: str = "",
        note: str = "",
        when=None,
    ):
        """
        Ledger-only: record a repayment against the CREDIT portion (not the cash deposit).
        No business Transaction is created (money flows to funder, not us).
        """
        amt = r2(Decimal(amount))
        if amt <= 0:
            raise ValueError("Amount must be a positive decimal.")

        return CreditEntry.record_repayment(
            client=self.client,
            amount=amt,
            invoice=self,
            transaction=None,
            reference=reference or f"INV-{self.id} credit repayment",
            note=note,
            when=when,
        )

    # --- status helpers (cash deposit dimension) ---

    def is_fully_paid(self) -> bool:
        return self.deposit_paid >= self.amount_due

    @property
    def is_overdue(self) -> bool:
        return (
            self.due_date is not None
            and localdate() > self.due_date
            and not self.is_fully_paid()
        )

    def update_status(self, save: bool = False) -> None:
        """
        Decide status from current deposit snapshots and keep paid_date consistent:
        - Set paid_date the first time it becomes fully paid.
        - Clear paid_date if it drops below fully paid (refund/adjustment).
        """
        today = localdate()

        if self.is_fully_paid():
            new_status = "paid"
        elif self.due_date and today > self.due_date and self.deposit_paid < self.amount_due:
            new_status = "overdue"
        elif self.deposit_paid > 0:
            new_status = "partial"
        else:
            new_status = "unpaid"

        if new_status == "paid":
            if self.paid_date is None:
                self.paid_date = today
        else:
            if self.paid_date is not None:
                self.paid_date = None

        self.status = new_status
        if save:
            self.save(update_fields=["status", "deposit_paid", "paid_date", "updated_at"])

    # --- cascading delete of related transactions & ledger rollback via signals ---

    @transaction.atomic
    def delete(self, *args, **kwargs):
        """
        1) Delete all related Transaction rows so their own delete() logic runs.
        2) Delete any ledger entries (CreditEntry) tied to this invoice.
           CreditEntry signals will reverse their effect on CreditAccount.
        """
        from transactions.models import Transaction  # lazy import

        # 1) delete TX rows first
        for tx in self.transactions.all().order_by("-created_at", "-id"):
            tx.delete()

        # 2) delete any ledger entries tied to this invoice (signals reverse effects)
        for ce in self.credit_entries.all().order_by("-posted_at", "-id"):
            ce.delete()

        super().delete(*args, **kwargs)


class DailyOverdueSummary(models.Model):
    """
    Stores the result of the daily overdue sweep so you can report/audit
    how many invoices turned overdue and how many are overdue in total.
    """
    run_date = models.DateField(db_index=True, unique=True)
    new_overdue = models.IntegerField(default=0)
    total_overdue = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-run_date"]
        indexes = [
            models.Index(fields=["run_date"]),
        ]

    def __str__(self) -> str:
        return f"Overdue Summary {self.run_date} (new={self.new_overdue}, total={self.total_overdue})"

class CommissionEntry(models.Model):
    """
    One row per invoice that records the commission earned for that invoice.
    CommissionEntry is created/updated when an Invoice becomes fully paid.
    """

    rep = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="commission_entries",
        help_text="Snapshot of the sales rep who owned the client when commission was generated.",
    )

    invoice = models.OneToOneField(
        Invoice,
        on_delete=models.CASCADE,
        related_name="commission_entry",
        help_text="Invoice that generated this commission entry (created when invoice is paid).",
    )

    invoice_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"),
                               help_text="Commission percent (e.g. 5.00 for 5%).")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    is_new_business = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["rep"]),
            models.Index(fields=["is_new_business"]),
        ]

    def __str__(self):
        return f"CommissionEntry #{self.id} - Invoice {self.invoice_id} - R{self.amount}"


class MonthlyCommission(models.Model):
    """
    Aggregated monthly commission for a rep (one row per rep / year / month).
    Stores recurring commissions, new-business commissions, the chosen tier and bonus,
    and the final total payout for that month.
    """

    rep = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="monthly_commissions")
    year = models.IntegerField(db_index=True)
    month = models.IntegerField(db_index=True)  # 1..12

    recurring_sales_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    recurring_commission_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    new_business_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    new_business_commission = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    weekly_average = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    commission_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    monthly_cash_bonus = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    total_payout = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    paid = models.BooleanField(default=False)
    paid_on = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("rep", "year", "month")]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"MonthlyCommission {self.rep} {self.year}-{self.month:02d}"


class CommissionAdjustment(models.Model):
    """
    Manual adjustment record for a MonthlyCommission (positive or negative).
    Keeps the payroll audit trail tidy.
    """

    monthly_commission = models.ForeignKey(MonthlyCommission, on_delete=models.CASCADE, related_name="adjustments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Adjustment {self.amount} for {self.monthly_commission}"


# -------------------------
# Commission tier config
# -------------------------
# Each tuple: (weekly_threshold, commission_pct, monthly_cash_bonus)
# Should be ordered descending by threshold.
COMMISSION_TIERS = [
    (Decimal("35000"), Decimal("8.00"), Decimal("4000.00")),
    (Decimal("30000"), Decimal("7.00"), Decimal("3000.00")),
    (Decimal("25000"), Decimal("6.00"), Decimal("2000.00")),
    (Decimal("20000"), Decimal("5.00"), Decimal("1000.00")),
    (Decimal("10000"), Decimal("4.00"), Decimal("0.00")),
]


def pick_tier_for_weekly_avg(weekly_avg: Decimal) -> Tuple[Decimal, Decimal]:
    """
    Return (rate_pct, monthly_bonus) for a given weekly average value.
    If below the lowest threshold, returns (0.00, 0.00).
    """
    for threshold, pct, bonus in COMMISSION_TIERS:
        if weekly_avg >= threshold:
            return pct, bonus
    return Decimal("0.00"), Decimal("0.00")


# -------------------------
# Helpers: new-business detection & per-invoice creation
# -------------------------
def invoice_is_new_business(invoice: Invoice) -> bool:
    """
    True if this is the client's first paid invoice (based on paid_date ordering).
    Called after invoice.paid_date is set.
    """
    if not invoice.paid_date:
        return False
    prior_exists = invoice.client.invoices.filter(
        paid_date__lt=invoice.paid_date
    ).exclude(pk=invoice.pk).exists()
    return not prior_exists


def create_or_update_commission_entry_for_invoice(invoice: Invoice) -> CommissionEntry:
    """
    Create or update CommissionEntry for a fully paid invoice.
    - If invoice is new business -> immediately set rate = 8% and compute amount.
    - Otherwise, create entry with rate 0 and amount 0; monthly job will set final rate/amount.
    The rep is taken from invoice.client.account_manager (snapshot).
    """
    rep = getattr(invoice.client, "account_manager", None)
    inv_total = r2(invoice.order_total_inc or getattr(invoice.order, "grand_total_inc", Decimal("0.00")))
    is_new = invoice_is_new_business(invoice)

    if is_new:
        rate_pct = Decimal("8.00")
        amount = r2(inv_total * (rate_pct / Decimal("100")))
    else:
        rate_pct = Decimal("0.00")
        amount = Decimal("0.00")

    ce, _ = CommissionEntry.objects.update_or_create(
        invoice=invoice,
        defaults={
            "rep": rep,
            "invoice_total": inv_total,
            "rate": rate_pct,
            "amount": amount,
            "is_new_business": is_new,
        },
    )
    return ce


# Signal: create commission entry when invoice becomes fully paid
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=Invoice)
def invoice_post_save_create_commission(sender, instance: Invoice, created, **kwargs):
    """
    When an Invoice becomes fully paid (deposit_paid >= amount_due / status == 'paid' and paid_date present),
    ensure there's a CommissionEntry for auditing. New-business entries get immediate 8% calculation.
    Recurring entries are updated later by monthly aggregation.
    """
    if not instance.is_fully_paid():
        return
    # create/update CommissionEntry
    create_or_update_commission_entry_for_invoice(instance)


# -------------------------
# Monthly calculation / aggregation
# -------------------------
def weeks_in_month(year: int, month: int) -> Decimal:
    """Return a reasonable week count for a month (ceil(days/7))."""
    days = monthrange(year, month)[1]
    return Decimal(str(math.ceil(days / 7)))


def calculate_monthly_commissions(
    year: int,
    month: int,
    *,
    require_kpi_fn: Optional[Callable[[settings.AUTH_USER_MODEL, int, int], bool]] = None,
    force_recalc: bool = False,
) -> None:
    """
    Calculate monthly commissions for all reps with paid invoices in the month.

    Arguments:
    - year, month: ints for the period to calculate (e.g. 2025, 11)
    - require_kpi_fn: optional function(rep, year, month) -> bool that returns True if the rep met KPI eligibility.
                      If provided and it returns False for a rep, the monthly_cash_bonus is set to 0.
    - force_recalc: if True, existing MonthlyCommission rows will be re-calculated/overwritten.

    Behaviour:
    - Collect all Invoices with paid_date in the month.
    - Ensure CommissionEntry exists for each (create placeholder if missing).
    - Group CommissionEntry by rep.
    - For each rep:
        - Sum recurring (non-new) invoice totals for month
        - Compute weekly average = recurring_total / weeks_in_month
        - Pick tier (rate_pct, monthly_bonus)
        - Compute recurring_commission_total = recurring_total * rate_pct
        - Sum new-business commissions (already stored in CommissionEntry.amount)
        - Create/update MonthlyCommission with totals and set total_payout
        - Update CommissionEntry rows for recurring invoices to store final rate & amount
    """
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    # fetch paid invoices in range
    paid_invoices_qs = Invoice.objects.filter(paid_date__gte=first_day, paid_date__lte=last_day).select_related("client", "client__account_manager").prefetch_related("commission_entry")

    # Ensure CommissionEntry exists for each invoice; group by rep
    reps_map = defaultdict(list)  # rep -> list[(invoice, commission_entry)]
    for inv in paid_invoices_qs:
        ce = getattr(inv, "commission_entry", None)
        if ce is None:
            ce = create_or_update_commission_entry_for_invoice(inv)
        rep = ce.rep
        # skip invoices with no rep assigned (surface them via admin later)
        if rep is None:
            continue
        reps_map[rep].append((inv, ce))

    weeks = weeks_in_month(year, month)

    # Process each rep
    for rep, items in reps_map.items():
        recurring_total = Decimal("0.00")
        recurring_entries = []
        new_business_total = Decimal("0.00")
        new_business_commission_total = Decimal("0.00")

        for inv, ce in items:
            if ce.is_new_business:
                new_business_total += ce.invoice_total
                new_business_commission_total += ce.amount
            else:
                recurring_total += ce.invoice_total
                recurring_entries.append((inv, ce))

        weekly_avg = r2(recurring_total / weeks) if weeks > 0 else Decimal("0.00")

        rate_pct, monthly_bonus = pick_tier_for_weekly_avg(weekly_avg)

        # If KPI checker provided and fails, zero the monthly bonus
        if require_kpi_fn is not None and not require_kpi_fn(rep, year, month):
            monthly_bonus = Decimal("0.00")

        recurring_commission_total = r2(recurring_total * (rate_pct / Decimal("100")))

        total_payout = r2(recurring_commission_total + new_business_commission_total + monthly_bonus)

        # create/update MonthlyCommission
        mc, created = MonthlyCommission.objects.update_or_create(
            rep=rep, year=year, month=month,
            defaults={
                "recurring_sales_total": r2(recurring_total),
                "recurring_commission_total": recurring_commission_total,
                "new_business_total": r2(new_business_total),
                "new_business_commission": r2(new_business_commission_total),
                "weekly_average": weekly_avg,
                "commission_rate_pct": rate_pct,
                "monthly_cash_bonus": monthly_bonus,
                "total_payout": total_payout,
            }
        )

        # Update recurring CommissionEntry rows with final rate & per-invoice amounts
        for inv, ce in recurring_entries:
            new_amount = r2(ce.invoice_total * (rate_pct / Decimal("100")))
            if ce.rate != rate_pct or ce.amount != new_amount:
                ce.rate = rate_pct
                ce.amount = new_amount
                ce.save(update_fields=["rate", "amount"])