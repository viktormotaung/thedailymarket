from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, timedelta
import math
from django.apps import apps
from calendar import monthrange
from collections import defaultdict
from typing import Callable, Optional
import calendar
from django.conf import settings
from django.db import models, transaction
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.timezone import localdate, now

from clients.models import Client
from orders.models import Order
from credit.models import CreditEntry
from django.db.models.signals import post_save, post_delete
from django.db.models.functions import Coalesce
from datetime import date
import uuid

def r2(x: Decimal | None) -> Decimal:
    """Round to 2 decimals, treating None as 0.00."""
    if x is None:
        return Decimal("0.00")
    return Decimal(x).quantize(Decimal("0.01"))

# 🇿🇦 South Africa Public Holidays (example for 2026)
PUBLIC_HOLIDAYS = {
    2026: [
        date(2026, 1, 1),   # New Year's Day
        date(2026, 3, 21),  # Human Rights Day
        date(2026, 4, 3),   # Good Friday
        date(2026, 4, 6),   # Family Day
        date(2026, 4, 27),  # Freedom Day
        date(2026, 5, 1),   # Workers' Day
        date(2026, 6, 16),  # Youth Day
        date(2026, 8, 9),   # Women's Day
        date(2026, 9, 24),  # Heritage Day
        date(2026, 12, 16), # Day of Reconciliation
        date(2026, 12, 25), # Christmas Day
        date(2026, 12, 26), # Day of Goodwill
    ]
}

# ====================================================================
# Invoice
# ====================================================================
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
    order_total_inc = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_due = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Deposit due (cash portion).",
    )
    deposit_required = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    deposit_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit_used = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Portion going onto credit (after deposit).",
    )

    # Deprecated shim (kept for migrations/backwards compatibility)
    credit_usage_applied = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="(Deprecated) Old delta tracker when pushing to ledger directly.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    public_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    segment = models.ForeignKey(
        "UtilizationSegment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
        help_text="Utilization segment this invoice belongs to (Daily / 3-Day / 7-Day)."
    )

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

    # ---------- Core logic (deposit + credit) ----------

    def calculate_totals(self) -> None:
        """
        Compute deposit/credit snapshots from the linked order & client.

        For CREDIT clients (account_type='CREDIT' and credit_status='ACTIVE'):
        - Use the client's CreditAccount.credit_deposit_pct (0, 30, 50 or 100)
          to decide the cash deposit.
        - The remaining portion goes onto credit (credit_used).
        - Due date is invoice_date + payment_term days (0D, 3D, 7D).

        For non-credit clients (or if no CreditAccount exists):
        - 100% upfront cash deposit, 0 credit.
        - Due date is invoice_date (0-day account).
        """
        total = r2(self.order.grand_total_inc)
        self.order_total_inc = total

        # Defaults: non-credit behaviour
        deposit_pct = Decimal("100.00")  # 100% cash upfront
        term_days = 0                    # due today

        is_credit_client = (
            self.client.account_type == "CREDIT"
            and self.client.credit_status == "ACTIVE"
        )

        if is_credit_client:
            # Try to read settings from the client's CreditAccount
            ca = getattr(self.client, "credit_account", None)

            if ca is not None:
                # 1) Deposit percentage (0, 30, 50, 100)
                try:
                    if ca.credit_deposit_pct is not None:
                        deposit_pct = Decimal(str(ca.credit_deposit_pct))
                except Exception:
                    # If anything is weird, fall back to full deposit
                    deposit_pct = Decimal("100.00")

                # 2) Payment term → due date offset
                term_code = (getattr(ca, "payment_term", "0D") or "0D").upper()
                if term_code == "3D":
                    term_days = 3
                elif term_code == "7D":
                    term_days = 7
                else:
                    term_days = 0  # treat anything else as 0-day
            else:
                # CREDIT client but no CreditAccount yet:
                # You can customise this behaviour if you want different defaults.
                pass
        UtilizationSegment = apps.get_model("invoices", "UtilizationSegment")

        cycle_days = term_days if term_days > 0 else 1
        db = self._state.db or self.order._state.db or "default"

        self.segment = (
            UtilizationSegment.objects.using(db)
            .filter(cycle_days=cycle_days, is_active=True)
            .first()
        )

        # Compute deposit + credit portions
        self.deposit_required = r2(total * (deposit_pct / Decimal("100")))
        self.credit_used = r2(total - self.deposit_required)

        # For non-credit clients, ensure no credit is used (safety clamp)
        if not is_credit_client:
            self.credit_used = Decimal("0.00")

        # Amount currently due is always the deposit portion
        self.amount_due = self.deposit_required

        # Set due_date only if not already set
        if not self.due_date:
            base_date = self.invoice_date or localdate()
            self.due_date = base_date + timedelta(days=term_days)

    
    @classmethod
    def create_for_order(cls, order: Order) -> "Invoice":
        db = order._state.db  # 🔥 KEY LINE

        if hasattr(order, "invoice"):
            inv: "Invoice" = order.invoice

            inv.calculate_totals()
            inv.save(
                using=db,
                update_fields=[
                    "order_total_inc",
                    "amount_due",
                    "deposit_required",
                    "credit_used",
                    "due_date",
                    "updated_at",
                ],
            )

            inv.ensure_invoice_out_txn()
            inv.ensure_credit_after_deposit()
            return inv

        with transaction.atomic(using=db):  # 🔥 IMPORTANT
            invoice = cls(order=order, client=order.client)

            invoice.calculate_totals()

            invoice.save(using=db)  # 🔥 IMPORTANT

            invoice.ensure_invoice_out_txn()
            invoice.ensure_credit_after_deposit()

            return invoice

    # ---------- Credit release gating ----------

    def can_release_credit(self) -> bool:
        """
        Only release/post credit (usage ledger + funder cash-in) when:
         - client is an ACTIVE credit client, AND
         - the invoice deposit is fully paid (status==paid or deposit_paid >= amount_due).
        """
        is_credit_client = (
            self.client.account_type == "CREDIT"
            and self.client.credit_status == "ACTIVE"
        )
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
        from transactions.models import Transaction

        db = self._state.db  # 🔥

        if not self.pk:
            self.save(using=db)

        txn, created = Transaction.objects.using(db).get_or_create(
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
            txn.save(using=db, update_fields=["amount"])

        return txn
    


    def ensure_credit_issue_txn(self):
        from transactions.models import Transaction

        db = self._state.db  # 🔥 IMPORTANT

        if not self.pk:
            self.save(using=db)

        if not self.can_release_credit():
            self.remove_credit_issue_txn()
            return None

        target = r2(self.credit_used or Decimal("0.00"))
        if target == Decimal("0.00"):
            self.remove_credit_issue_txn()
            return None

        tx = Transaction.objects.using(db).filter(
            invoice=self,
            transaction_type="credit_issue",
        ).first()

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
                tx.save(using=db, update_fields=["amount", "reference", "note"])
            return tx

        return Transaction.objects.using(db).create(
            client=self.client,
            invoice=self,
            transaction_type="credit_issue",
            amount=target,
            reference=f"INV-{self.id} credit funded",
            note="Funder covered credit portion",
        )
    
    def remove_credit_issue_txn(self):
        from transactions.models import Transaction

        db = self._state.db

        q = Transaction.objects.using(db).filter(
            invoice=self,
            transaction_type="credit_issue"
        )

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
            CreditEntry.objects.using(self._state.db)
            .filter(
                invoice=self,
                kind=CreditEntry.USAGE,
                credit_account__client=self.client
            )
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
            using=self._state.db
        )

    def remove_credit_usage_entry(self):
        db = self._state.db

        for ce in self.credit_entries.using(db).filter(
            kind=CreditEntry.USAGE
        ).order_by("-posted_at", "-id"):
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

        Transaction.objects.using(self._state.db).create(
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

            # ---------------------------------------
            # 1️⃣ Persist paid_date (calendar day)
            # ---------------------------------------
            if self.paid_date != payment_day:
                self.paid_date = payment_day
                self.save(update_fields=["paid_date", "updated_at"])

            # ---------------------------------------
            # 2️⃣ Update CreditAccount next_due_date
            # ---------------------------------------
            ca = getattr(self.client, "credit_account", None)
            if ca:
                ca.next_due_date = payment_day + timedelta(days=1)
                ca.save(update_fields=["next_due_date"])

            # ---------------------------------------
            # 3️⃣ Move Order to "at_warehouse"
            # ---------------------------------------
            order = getattr(self, "order", None)

            if order:

                order.refresh_from_db()

                # Prevent moving orders that are already past warehouse
                terminal_statuses = [
                    "at_warehouse",
                    "ready_for_delivery",
                    "out_for_delivery",
                    "complete",
                    "cancelled",
                ]

                if order.status not in terminal_statuses:

                    print(f"📦 Moving order {order.id} to AT_WAREHOUSE")
                    print(f"Previous order status: {order.status}")

                    order.status = "at_warehouse"
                    order.save(update_fields=["status", "updated_at"])

                    print(f"✅ Order {order.id} moved to AT_WAREHOUSE")

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
            using=self._state.db  # 🔥 ADD THIS
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



@receiver(post_save, sender=Invoice)
def ensure_order_progress_after_payment(sender, instance, **kwargs):

    if instance.status != "paid":
        return

    order = getattr(instance, "order", None)

    if not order:
        return

    order.refresh_from_db()

    terminal_statuses = [
        "at_warehouse",
        "ready_for_delivery",
        "out_for_delivery",
        "complete",
        "cancelled",
    ]

    if order.status not in terminal_statuses:

        print(f"📦 Signal moving order {order.id} to AT_WAREHOUSE")

        order.status = "at_warehouse"
        order.save(using=order._state.db, update_fields=["status", "updated_at"])



@receiver(post_save, sender=CreditEntry)
def update_credit_next_due(sender, instance, **kwargs):
    ca = instance.credit_account
    # Recalculate total credit_used
    ca.credit_used = ca.entries.filter(kind=CreditEntry.USAGE).aggregate(
        s=Coalesce(Sum("amount"), Decimal("0.00"))
    )["s"] or Decimal("0.00")

    # Update next_due_date based on invoice due date + 1 day
    invoice_due = getattr(instance.invoice, "due_date", None)
    if invoice_due:
        ca.next_due_date = invoice_due + timedelta(days=1)

    ca.save(update_fields=["credit_used", "next_due_date"])



@receiver(post_delete, sender=CreditEntry)
def reverse_credit_next_due(sender, instance, **kwargs):
    ca = instance.credit_account
    # Recalculate total credit_used after deletion
    ca.credit_used = ca.entries.filter(kind=CreditEntry.USAGE).aggregate(
        s=Coalesce(Sum("amount"), Decimal("0.00"))
    )["s"] or Decimal("0.00")

    # Clear next_due_date if no remaining credit
    if ca.credit_used == 0:
        ca.next_due_date = None

    ca.save(update_fields=["credit_used", "next_due_date"])



# ====================================================================
# Daily overdue summary
# ====================================================================

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


# ====================================================================
# Commission: cost-based, per invoice
# ====================================================================

# ====================================================================
# Commission: cost-based, per invoice
# ====================================================================

class CommissionEntry(models.Model):
    """
    One row per invoice that records commission on COST, not selling price.
    - cost_total: total cost of products on invoice (snapshot).
    - rep_rate / rep_amount: commission for sales rep.
    - supervisor_rate / supervisor_amount: commission for supervisor (optional).
    - is_new_business: whether this commission qualifies for the above-target new-business bonus.
    """

    COMMISSION_RATE_CHOICES = [
        (Decimal("1.00"), "1%"),
        (Decimal("1.50"), "1.5%"),
        (Decimal("2.00"), "2%"),
        (Decimal("2.50"), "2.5%"),
        (Decimal("3.00"), "3%"),
        (Decimal("3.50"), "3.5%"),
        (Decimal("4.00"), "4%"),
        (Decimal("5.00"), "5%"),
    ]

    rep = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
        help_text="Snapshot of the sales rep who owned the client when commission was generated.",
    )

    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supervisor_commission_entries",
        help_text="Snapshot of the supervisor at commission time (optional).",
    )

    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
        help_text="Snapshot of the client associated with this commission entry."
    )

    invoice = models.OneToOneField(
        "Invoice",
        on_delete=models.CASCADE,
        related_name="commission_entry",
        help_text="Invoice that generated this commission entry (created when invoice is paid).",
    )

    # COST-based snapshot (ex VAT)
    cost_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total COST of products on invoice (ex VAT).",
    )

    # Rep commission
    rep_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=COMMISSION_RATE_CHOICES,
        default=Decimal("2.50"),  # default 2.5% (new business)
        help_text="Commission percent for sales rep (on cost).",
    )
    rep_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    # Supervisor commission
    supervisor_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=COMMISSION_RATE_CHOICES,
        default=Decimal("1.00"),  # default 1% for supervisor
        help_text="Commission percent for supervisor (on cost).",
    )
    supervisor_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    is_new_business = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["rep"]),
            models.Index(fields=["supervisor"]),
            models.Index(fields=["is_new_business"]),
        ]

    def __str__(self):
        return (
            f"CommissionEntry #{self.id} - Invoice {self.invoice_id} - "
            f"Rep R{self.rep_amount} / Sup R{self.supervisor_amount}"
        )

    # ---------- amount recomputation ----------

    def recompute_amounts(self):
        """
        Recalculate rep_amount and supervisor_amount from:
        - cost_total
        - rep_rate
        - supervisor_rate
        and whether a supervisor is set.
        """
        if self.cost_total is None:
            return

        base = self.cost_total or Decimal("0.00")

        # Rep commission
        self.rep_amount = r2(
            base * (self.rep_rate / Decimal("100"))
        )

        # Supervisor commission only if there *is* a supervisor
        if self.supervisor:
            self.supervisor_amount = r2(
                base * (self.supervisor_rate / Decimal("100"))
            )
        else:
            self.supervisor_amount = Decimal("0.00")

    def save(self, *args, **kwargs):
        """
        Before saving:
        - If client is missing, copy it from the linked invoice.
        - Keep commission amounts in sync.
        """

        if not self.client and self.invoice_id:
            invoice = getattr(self, "invoice", None)

            if invoice and invoice.client_id:
                self.client = invoice.client

        # Always keep amounts in sync with rates, cost_total and supervisor
        self.recompute_amounts()

        super().save(*args, **kwargs)




@receiver(post_save, sender=CommissionEntry)
def commission_entry_post_save_update_targets(sender, instance: CommissionEntry, **kwargs):
    """
    After a commission entry is saved:
    - update/check the rep's MonthlyTargetAllocation timestamps
    - update/check the area MonthlyTarget timestamps
    """

    invoice = instance.invoice
    rep = instance.rep

    if not invoice or not invoice.paid_date or not rep:
        return

    paid_day = invoice.paid_date
    month_code = paid_day.strftime("%b").upper()[:3]

    allocation = (
        MonthlyTargetAllocation.objects
        .filter(
            sales_rep=rep,
            monthly_target__year=paid_day.year,
            monthly_target__month=month_code,
            monthly_target__area=invoice.client.area,
        )
        .first()
    )

    if allocation:
        allocation.check_and_set_target_reached()
        allocation.monthly_target.check_and_set_target_reached()


# ====================================================================
# MonthlyCommission + adjustments
# ====================================================================

class MonthlyCommission(models.Model):
    """
    Aggregated monthly commission for a rep (one row per rep / year / month).
    Uses cost-based commissions from CommissionEntry.
    """

    rep = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monthly_commissions",
    )
    year = models.IntegerField(db_index=True)
    month = models.IntegerField(db_index=True)  # 1..12

    recurring_sales_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=Decimal("0.00")
    )
    recurring_commission_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=Decimal("0.00")
    )

    new_business_total = models.DecimalField(
        max_digits=16, decimal_places=2, default=Decimal("0.00")
    )
    new_business_commission = models.DecimalField(
        max_digits=16, decimal_places=2, default=Decimal("0.00")
    )

    weekly_average = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    commission_rate_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Effective commission % on recurring cost (for reporting).",
    )
    monthly_cash_bonus = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    total_payout = models.DecimalField(
        max_digits=16, decimal_places=2, default=Decimal("0.00")
    )

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

    monthly_commission = models.ForeignKey(
        MonthlyCommission,
        on_delete=models.CASCADE,
        related_name="adjustments",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Adjustment {self.amount} for {self.monthly_commission}"


# ====================================================================
# Commission helpers & aggregation
# ====================================================================

def weeks_in_month(year: int, month: int) -> Decimal:
    """Return a reasonable week count for a month (ceil(days/7))."""
    days = monthrange(year, month)[1]
    return Decimal(str(math.ceil(days / 7)))


def invoice_qualifies_for_new_business_bonus(invoice: Invoice, rep) -> bool:
    """
    A commission entry qualifies as new-business bonus only if:

    1. The invoice has a paid_date.
    2. A rep exists.
    3. This is the client's first commission-generating invoice
       for this rep in this month.
    4. The rep's unique monthly client count is ABOVE their client target.

    Example:
        client_target = 8

        Client 1-8  -> is_new_business = False
        Client 9+   -> is_new_business = True
    """

    if not invoice.paid_date or not rep:
        return False

    paid_day = invoice.paid_date
    first_day = date(paid_day.year, paid_day.month, 1)
    last_day = date(
        paid_day.year,
        paid_day.month,
        monthrange(paid_day.year, paid_day.month)[1]
    )

    client = invoice.client

    # --------------------------------------------------
    # 1. Only count the client once per rep/month
    # --------------------------------------------------
    prior_client_commission_exists = (
        CommissionEntry.objects
        .filter(
            rep=rep,
            invoice__client=client,
            invoice__paid_date__gte=first_day,
            invoice__paid_date__lte=last_day,
        )
        .exclude(invoice=invoice)
        .exists()
    )

    if prior_client_commission_exists:
        return False

    # --------------------------------------------------
    # 2. Find this rep's monthly target allocation
    # --------------------------------------------------
    allocation = (
        MonthlyTargetAllocation.objects
        .filter(
            sales_rep=rep,
            monthly_target__year=paid_day.year,
            monthly_target__month=paid_day.strftime("%b").upper()[:3],
            monthly_target__area=client.area,
        )
        .first()
    )

    if not allocation:
        return False

    # --------------------------------------------------
    # 3. Count unique commission-generating clients
    #    for the rep/month, including this invoice
    # --------------------------------------------------
    unique_client_count = (
        CommissionEntry.objects
        .filter(
            rep=rep,
            invoice__paid_date__gte=first_day,
            invoice__paid_date__lte=last_day,
            invoice__client__area=client.area,
        )
        .values("invoice__client_id")
        .distinct()
        .count()
    )

    # If this commission entry does not exist yet, include current client manually
    current_client_already_counted = (
        CommissionEntry.objects
        .filter(
            rep=rep,
            invoice__client=client,
            invoice__paid_date__gte=first_day,
            invoice__paid_date__lte=last_day,
        )
        .exists()
    )

    if not current_client_already_counted:
        unique_client_count += 1

    return unique_client_count > allocation.client_target


def compute_invoice_cost_excl(invoice: Invoice) -> Decimal:
    """
    Approximate total COST of the invoice based on Product.cost_price (ex VAT) * quantity
    for each OrderItem. If a product has no cost_price, we treat it as 0.00.

    NOTE: This uses CURRENT product.cost_price. If you later change cost_price
    and recompute commissions, old invoices will reflect the new cost.
    """
    order = invoice.order
    total = Decimal("0.00")

    # Avoid N+1: load products with each order item
    items = order.items.select_related("product")

    for item in items:
        product = item.product
        cost_per_unit = getattr(product, "cost_price", None) or Decimal("0.00")
        qty = item.quantity or Decimal("0.00")
        total += r2(cost_per_unit * qty)

    return r2(total)


def resolve_rep_and_supervisor_for_invoice(invoice: Invoice):
    """
    Decide who the sales rep and supervisor are for this invoice.

    - Rep: taken from client.account_manager (User).
    - Supervisor: taken from that rep's SalesRepProfile.supervisor (if it exists).
    """
    client = invoice.client

    # Main sales rep = account_manager on the client
    rep = getattr(client, "account_manager", None)

    supervisor = None
    if rep is not None:
        # rep.sales_rep_profile is the OneToOne from SalesRepProfile.user
        sales_profile = getattr(rep, "sales_rep_profile", None)
        supervisor = getattr(sales_profile, "supervisor", None) if sales_profile else None

    return rep, supervisor



def create_or_update_commission_entry_for_invoice(invoice: Invoice) -> CommissionEntry:
    """
    Create or update CommissionEntry for a fully paid invoice.

    New logic:
    - Rep is resolved from client.account_manager.
    - Client only counts once per month once they have a commission-generating invoice.
    - is_new_business=True only when rep has exceeded their monthly client target.
    - New-business bonus rate = 5%.
    - Normal recurring rate = 2.5%.
    """

    rep, supervisor = resolve_rep_and_supervisor_for_invoice(invoice)

    cost_total = compute_invoice_cost_excl(invoice)

    is_new = invoice_qualifies_for_new_business_bonus(invoice, rep)

    rep_rate_pct = Decimal("5.00") if is_new else Decimal("2.50")
    supervisor_rate_pct = Decimal("1.00")

    ce, _ = CommissionEntry.objects.using(invoice._state.db).update_or_create(
        invoice=invoice,
        defaults={
            "client": invoice.client,
            "rep": rep,
            "supervisor": supervisor,
            "cost_total": cost_total,
            "rep_rate": rep_rate_pct,
            "supervisor_rate": supervisor_rate_pct,
            "is_new_business": is_new,
        },
    )

    return ce


@receiver(post_save, sender=Invoice)
def invoice_post_save_create_commission(sender, instance: Invoice, created, **kwargs):
    """
    When an Invoice becomes fully paid (deposit_paid >= amount_due / status == 'paid' and paid_date present),
    ensure there's a CommissionEntry for auditing (cost-based, with fixed %).
    """
    if not instance.is_fully_paid():
        return
    create_or_update_commission_entry_for_invoice(instance)


def calculate_monthly_commissions(
    year: int,
    month: int,
    *,
    require_kpi_fn: Optional[Callable[[settings.AUTH_USER_MODEL, int, int], bool]] = None,
    force_recalc: bool = False,
) -> None:
    """
    Calculate monthly commissions per rep based on CommissionEntry rows:

    - recurring_* = totals for repeat business (is_new_business=False)
    - new_business_* = totals for first invoices (is_new_business=True)
    - weekly_average = recurring_sales_total / weeks_in_month (for reporting)
    - commission_rate_pct = effective % on recurring cost
      (recurring_commission_total / recurring_sales_total)
    - monthly_cash_bonus is 0 for now; you can plug in require_kpi_fn to turn it on/off.
    """
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    # pull all commission entries whose invoice was paid in this month
    ces = (
        CommissionEntry.objects
        .filter(invoice__paid_date__gte=first_day, invoice__paid_date__lte=last_day)
        .select_related("rep")
    )

    reps_map: dict = defaultdict(list)
    for ce in ces:
        if ce.rep is None:
            continue
        reps_map[ce.rep].append(ce)

    weeks = weeks_in_month(year, month)

    for rep, entries in reps_map.items():
        recurring_sales_total = Decimal("0.00")
        recurring_comm_total = Decimal("0.00")
        new_business_total = Decimal("0.00")
        new_business_comm_total = Decimal("0.00")

        for ce in entries:
            if ce.is_new_business:
                new_business_total += ce.cost_total
                new_business_comm_total += ce.rep_amount
            else:
                recurring_sales_total += ce.cost_total
                recurring_comm_total += ce.rep_amount

        weekly_average = r2(recurring_sales_total / weeks) if weeks > 0 else Decimal("0.00")

        # Effective commission rate on recurring cost
        if recurring_sales_total > 0:
            commission_rate_pct = r2(
                (recurring_comm_total / recurring_sales_total) * Decimal("100")
            )
        else:
            commission_rate_pct = Decimal("0.00")

        monthly_cash_bonus = Decimal("0.00")
        if require_kpi_fn is not None and not require_kpi_fn(rep, year, month):
            monthly_cash_bonus = Decimal("0.00")

        total_payout = r2(recurring_comm_total + new_business_comm_total + monthly_cash_bonus)

        MonthlyCommission.objects.update_or_create(
            rep=rep,
            year=year,
            month=month,
            defaults={
                "recurring_sales_total": r2(recurring_sales_total),
                "recurring_commission_total": r2(recurring_comm_total),
                "new_business_total": r2(new_business_total),
                "new_business_commission": r2(new_business_comm_total),
                "weekly_average": weekly_average,
                "commission_rate_pct": commission_rate_pct,
                "monthly_cash_bonus": monthly_cash_bonus,
                "total_payout": total_payout,
            },
        )




# =========================================================
# UTILIZATION SEGMENT MODEL
# =========================================================

class UtilizationSegment(models.Model):
    """
    Defines utilization cycle types (Daily, 3 Day, 7 Day, 14 Day etc.)
    """

    name = models.CharField(max_length=50)  # e.g. Daily, 3 Days
    cycle_days = models.IntegerField()      # 1, 3, 7, 14
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["cycle_days"]

    def __str__(self):
        return f"{self.name} ({self.cycle_days}-Day Cycle)"


# =========================================================
# MONTHLY TARGET MODEL
# =========================================================

class MonthlyTarget(models.Model):
    """
    Master monthly target for a territory/area.

    Example:
        North/Central - May 2026
            Total Revenue Target: R300,000
            Total Client Target: 24

    Rep allocations are handled by MonthlyTargetAllocation.
    """

    MONTH_CHOICES = [
        ("JAN", "January"),
        ("FEB", "February"),
        ("MAR", "March"),
        ("APR", "April"),
        ("MAY", "May"),
        ("JUN", "June"),
        ("JUL", "July"),
        ("AUG", "August"),
        ("SEP", "September"),
        ("OCT", "October"),
        ("NOV", "November"),
        ("DEC", "December"),
    ]

    YEAR_CHOICES = [(y, str(y)) for y in range(2026, 2031)]

    QUARTER_CHOICES = [
        ("Q1", "Q1"),
        ("Q2", "Q2"),
        ("Q3", "Q3"),
        ("Q4", "Q4"),
    ]

    AREA_CHOICES = [
        ("SOUTH_WEST", "South / West"),
        ("EAST", "East"),
        ("NORTH_CENTRAL", "North / Central"),
        ("MIDVAAL", "Midvaal"),
        ("PRETORIA", "Pretoria"),
        ("OTHER", "Other"),
    ]

    month = models.CharField(max_length=3, choices=MONTH_CHOICES)
    year = models.IntegerField(choices=YEAR_CHOICES)
    quarter = models.CharField(max_length=2, choices=QUARTER_CHOICES)
    area = models.CharField(max_length=20, choices=AREA_CHOICES)

    monthly_target = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total rand value target for this month and area."
    )

    total_client_target = models.PositiveIntegerField(
        default=0,
        help_text="Total new recurring client target for this month and area."
    )

    monthly_target_reached_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the total monthly revenue target was reached."
    )

    client_target_reached_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the total client target was reached."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("month", "year", "area")
        ordering = ["-year", "month"]

    def __str__(self):
        return f"{self.get_area_display()} - {self.get_month_display()} {self.year}"

    def get_month_number(self):
        month_map = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }
        return month_map[self.month]

    def get_total_days(self):
        return calendar.monthrange(self.year, self.get_month_number())[1]

    def get_total_working_days(self):
        month_number = self.get_month_number()
        total_days = calendar.monthrange(self.year, month_number)[1]

        holidays = PUBLIC_HOLIDAYS.get(self.year)

        if holidays is None:
            raise ValueError(f"No public holidays configured for year {self.year}")

        working_days = 0

        for day in range(1, total_days + 1):
            current_date = date(self.year, month_number, day)

            if current_date.weekday() < 5 and current_date not in holidays:
                working_days += 1

        return working_days

    def get_daily_target(self):
        working_days = self.get_total_working_days()

        if working_days <= 0:
            return Decimal("0.00")

        return (
            self.monthly_target / Decimal(working_days)
        ).quantize(Decimal("0.01"))

    def get_period_dates(self):
        month_number = self.get_month_number()

        first_day = date(self.year, month_number, 1)
        last_day = date(self.year, month_number, self.get_total_days())

        return first_day, last_day

    def get_actual_revenue(self):
        """
        Total paid invoice revenue for this area and month.
        """

        first_day, last_day = self.get_period_dates()

        total = (
            Invoice.objects.filter(
                status="paid",
                paid_date__gte=first_day,
                paid_date__lte=last_day,
                client__area=self.area,
            ).aggregate(
                s=Sum("order_total_inc")
            )["s"]
            or Decimal("0.00")
        )

        return total.quantize(Decimal("0.01"))

    def get_actual_clients(self):
        """
        Total unique commission-generating clients for this area and month.
        """

        first_day, last_day = self.get_period_dates()

        return (
            CommissionEntry.objects
            .filter(
                invoice__paid_date__gte=first_day,
                invoice__paid_date__lte=last_day,
                invoice__client__area=self.area,
            )
            .values("invoice__client_id")
            .distinct()
            .count()
        )

    def get_revenue_gap(self):
        return (
            self.monthly_target - self.get_actual_revenue()
        ).quantize(Decimal("0.01"))

    def get_client_gap(self):
        return max(
            self.total_client_target - self.get_actual_clients(),
            0
        )

    def get_revenue_percentage(self):
        if self.monthly_target <= 0:
            return Decimal("0.00")

        return (
            self.get_actual_revenue()
            / self.monthly_target
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    def get_client_percentage(self):
        if self.total_client_target <= 0:
            return Decimal("0.00")

        return (
            Decimal(self.get_actual_clients())
            / Decimal(self.total_client_target)
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    def check_and_set_target_reached(self):
        """
        Automatically sets timestamps once area-level targets are achieved.
        """

        changed = False

        if (
            not self.monthly_target_reached_at
            and self.get_actual_revenue() >= self.monthly_target
        ):
            self.monthly_target_reached_at = now()
            changed = True

        if (
            not self.client_target_reached_at
            and self.get_actual_clients() >= self.total_client_target
        ):
            self.client_target_reached_at = now()
            changed = True

        if changed:
            self.save(
                update_fields=[
                    "monthly_target_reached_at",
                    "client_target_reached_at",
                ]
            )


# =========================================================
# MONTHLY TARGET ALLOCATION MODEL
# =========================================================

class MonthlyTargetAllocation(models.Model):
    """
    Individual sales rep allocation for a MonthlyTarget.

    Example:
        North/Central Monthly Target:
            - Total Revenue Target: R300,000
            - Total Client Target: 24

        Rep Allocations:
            Rep A -> R100,000 / 8 clients
            Rep B -> R100,000 / 8 clients
            Rep C -> R100,000 / 8 clients
    """

    monthly_target = models.ForeignKey(
        "MonthlyTarget",
        on_delete=models.CASCADE,
        related_name="rep_allocations"
    )

    sales_rep = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="monthly_target_allocations",
        null=True,
        blank=True,
        help_text="Sales rep assigned to this monthly target allocation."
    )

    monthly_target_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Rand value target assigned to this sales rep for the month."
    )

    client_target = models.PositiveIntegerField(
        default=0,
        help_text="Number of new recurring clients this sales rep must achieve for the month."
    )

    monthly_target_reached_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the sales rep reached their monthly revenue target."
    )

    client_target_reached_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the sales rep reached their client target."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("monthly_target", "sales_rep")
        ordering = ["sales_rep__first_name", "sales_rep__last_name"]

    def __str__(self):
        rep_name = (
            self.sales_rep.get_full_name()
            or self.sales_rep.get_username()
        ) if self.sales_rep else "Unassigned"

        return (
            f"{rep_name} | "
            f"{self.monthly_target.get_month_display()} "
            f"{self.monthly_target.year}"
        )

    def get_period_dates(self):
        return self.monthly_target.get_period_dates()

    def get_actual_revenue(self):
        """
        Actual paid invoice revenue generated by this rep
        within the MonthlyTarget period.
        """

        if not self.sales_rep:
            return Decimal("0.00")

        first_day, last_day = self.get_period_dates()

        total = (
            Invoice.objects.filter(
                status="paid",
                paid_date__gte=first_day,
                paid_date__lte=last_day,
                client__account_manager=self.sales_rep,
                client__area=self.monthly_target.area,
            ).aggregate(
                s=Sum("order_total_inc")
            )["s"]
            or Decimal("0.00")
        )

        return total.quantize(Decimal("0.01"))

    def get_actual_clients(self):
        """
        Number of unique commission-generating clients for this rep
        within the MonthlyTarget period.
        """

        if not self.sales_rep:
            return 0

        first_day, last_day = self.get_period_dates()

        return (
            CommissionEntry.objects
            .filter(
                rep=self.sales_rep,
                invoice__paid_date__gte=first_day,
                invoice__paid_date__lte=last_day,
                invoice__client__area=self.monthly_target.area,
            )
            .values("invoice__client_id")
            .distinct()
            .count()
        )

    def get_revenue_gap(self):
        return (
            self.monthly_target_value - self.get_actual_revenue()
        ).quantize(Decimal("0.01"))

    def get_client_gap(self):
        return max(
            self.client_target - self.get_actual_clients(),
            0
        )

    def get_revenue_percentage(self):
        if self.monthly_target_value <= 0:
            return Decimal("0.00")

        return (
            self.get_actual_revenue()
            / self.monthly_target_value
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    def get_client_percentage(self):
        if self.client_target <= 0:
            return Decimal("0.00")

        return (
            Decimal(self.get_actual_clients())
            / Decimal(self.client_target)
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    def check_and_set_target_reached(self):
        """
        Automatically sets timestamps once rep-level targets are achieved.
        """

        changed = False

        if (
            not self.monthly_target_reached_at
            and self.get_actual_revenue() >= self.monthly_target_value
        ):
            self.monthly_target_reached_at = now()
            changed = True

        if (
            not self.client_target_reached_at
            and self.get_actual_clients() >= self.client_target
        ):
            self.client_target_reached_at = now()
            changed = True

        if changed:
            self.save(
                update_fields=[
                    "monthly_target_reached_at",
                    "client_target_reached_at",
                    "updated_at",
                ]
            )


class PaymentLog(models.Model):
    PROVIDER_CHOICES = [
        ("ozow", "Ozow"),
        ("yoco", "Yoco")
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    invoice = models.ForeignKey("Invoice", on_delete=models.CASCADE, related_name="payment_logs")

    transaction_reference = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    raw_request = models.JSONField(null=True, blank=True)
    raw_response = models.JSONField(null=True, blank=True)

    status = models.CharField(max_length=50, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider.upper()} - {self.transaction_reference}"