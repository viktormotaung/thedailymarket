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
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.timezone import localdate, now
from datetime import timedelta
from clients.models import Client
from orders.models import Order
from credit.models import CreditEntry
from django.db.models.signals import post_save, post_delete
from django.db.models.functions import Coalesce
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
    end_user = models.ForeignKey(
        "clients.EndUser", on_delete=models.SET_NULL,
        related_name="invoices", null=True, blank=True,
        help_text="End user receiving or benefiting from this invoice.",
    )

    STATUS_CHOICES = [
        ("unpaid", "Unpaid"),
        ("partial", "Partially Paid"),
        ("paid", "Customer Contribution Paid"),
        ("overdue", "Customer Contribution Overdue"),
    ]
    ALLOCATION_STATUS_CHOICES = [
        ("not_required", "Not Required"),
        ("pending", "Pending Contribution"),
        ("active", "Active"),
        ("settled", "Settled"),
        ("cancelled", "Cancelled"),
    ]
    SETTLEMENT_STATUS_CHOICES = [
        ("not_applicable", "Not Applicable"),
        ("pending", "Pending Activation"),
        ("outstanding", "Outstanding"),
        ("partial", "Partially Settled"),
        ("settled", "Settled"),
        ("overdue", "Overdue"),
        ("suspended", "Suspended"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="unpaid")
    invoice_date = models.DateField(default=localdate)
    # Customer contribution due date. The upfront contribution is due on invoice.
    due_date = models.DateField(null=True, blank=True)
    paid_date = models.DateField(
        null=True, blank=True, db_index=True,
        help_text="Date the customer's required contribution was fully paid.",
    )

    order_total_inc = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_due = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Customer contribution required before fulfilment.",
    )
    deposit_required = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    deposit_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit_used = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="TA-funded portion activated after verified customer contribution.",
    )

    # Immutable commercial snapshots for this invoice.
    contribution_pct_snapshot = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("100.00"),
        help_text="Customer contribution percentage approved when this invoice was created.",
    )
    settlement_term_snapshot = models.CharField(
        max_length=3, default="0D",
        help_text="Approved settlement term snapshot: 0D, 1D, 3D or 7D.",
    )
    settlement_due_date = models.DateField(null=True, blank=True, db_index=True)
    settlement_grace_end_date = models.DateField(null=True, blank=True)
    allocation_status = models.CharField(
        max_length=20, choices=ALLOCATION_STATUS_CHOICES, default="not_required",
        db_index=True,
    )
    settlement_status = models.CharField(
        max_length=20, choices=SETTLEMENT_STATUS_CHOICES, default="not_applicable",
        db_index=True,
    )
    settlement_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    settlement_outstanding = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # Deprecated shim retained for compatibility with existing code/data.
    credit_usage_applied = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Deprecated legacy delta tracker.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    segment = models.ForeignKey(
        "UtilizationSegment", on_delete=models.PROTECT, null=True, blank=True,
        related_name="invoices",
        help_text="Utilization segment this invoice belongs to (Daily / 3-Day / 7-Day).",
    )

    PAYMENT_TYPES = {"payment", "refund"}

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["invoice_date"]),
            models.Index(fields=["client", "status"]),
            models.Index(fields=["end_user", "status"]),
            models.Index(fields=["settlement_status", "settlement_due_date"]),
            models.Index(fields=["allocation_status"]),
        ]

    def __str__(self):
        if self.end_user:
            return f"Invoice #{self.id or '—'} · {self.client} · {self.end_user.full_name} · {self.status}"
        return f"Invoice #{self.id or '—'} · {self.client} · {self.status}"

    def clean(self):
        super().clean()
        if self.end_user and self.end_user.client_id != self.client_id:
            raise ValidationError("The selected end user does not belong to the selected client.")
        if self.end_user and self.order_id and self.order.end_user_id != self.end_user_id:
            raise ValidationError("The invoice end user must match the order end user.")

    @staticmethod
    def _term_days(term_code):
        return {"0D": 0, "1D": 1, "3D": 3, "7D": 7}.get(
            (term_code or "0D").upper(), 0
        )

    def _get_credit_account(self, lock=False):
        CreditAccount = apps.get_model("credit", "CreditAccount")
        qs = CreditAccount.objects.using(self._state.db or "default")
        if lock:
            qs = qs.select_for_update()
        return qs.filter(client_id=self.client_id).first()

    def calculate_totals(self):
        """
        Snapshot invoice terms from the current approved CreditAccount.
        This method does not consume buying power or create ledger entries.
        """
        total = r2(self.order.grand_total_inc)
        self.order_total_inc = total

        # Once an allocation is active, or money has been received, do not
        # silently rewrite the commercial terms of this issued invoice.
        frozen = (
            self.pk and (
                self.allocation_status in {"active", "settled"}
                or (self.deposit_paid or Decimal("0.00")) > 0
            )
        )
        if frozen:
            return

        deposit_pct = Decimal("100.00")
        term_code = "0D"
        ca = self._get_credit_account() if self.client_id else None

        if ca and ca.status == "ACTIVE":
            configured_term = (ca.payment_term or "0D").upper()
            if configured_term in {"1D", "3D", "7D"}:
                deposit_pct = Decimal(str(ca.credit_deposit_pct))
                term_code = configured_term
            else:
                # 0D or an invalid/legacy term is cash-only, fail-safe.
                deposit_pct = Decimal("100.00")
                term_code = "0D"
        else:
            # Pending, missing, overdue, suspended or closed accounts do not
            # receive a new TA-funded allocation.
            term_code = "0D"

        if not Decimal("0") <= deposit_pct <= Decimal("100"):
            raise ValidationError("Customer contribution percentage must be between 0 and 100.")

        self.contribution_pct_snapshot = deposit_pct
        self.settlement_term_snapshot = term_code
        self.deposit_required = r2(total * deposit_pct / Decimal("100"))
        self.amount_due = self.deposit_required
        self.credit_used = r2(total - self.deposit_required)

        if self.credit_used > 0:
            self.allocation_status = "pending"
            self.settlement_status = "pending"
            days = self._term_days(term_code)
            # Invoice date is Day 1: a 1D term is due on invoice date.
            self.settlement_due_date = (self.invoice_date or localdate()) + timedelta(days=max(days - 1, 0))
            self.settlement_grace_end_date = self.settlement_due_date + timedelta(days=1)
        else:
            self.allocation_status = "not_required"
            self.settlement_status = "not_applicable"
            self.credit_used = Decimal("0.00")
            self.settlement_due_date = None
            self.settlement_grace_end_date = None

        self.due_date = self.invoice_date or localdate()
        UtilizationSegment = apps.get_model("invoices", "UtilizationSegment")
        cycle_days = max(self._term_days(term_code), 1)
        self.segment = (
            UtilizationSegment.objects.using(self._state.db or "default")
            .filter(cycle_days=cycle_days, is_active=True).first()
        )

    @classmethod
    def create_for_order(cls, order):
        db = order._state.db or "default"
        with transaction.atomic(using=db):
            inv = cls.objects.using(db).filter(order=order).first()
            if inv:
                # Existing invoices are immutable financial snapshots. Only
                # keep the operational end-user link aligned with the order.
                if inv.end_user_id != order.end_user_id:
                    inv.end_user = order.end_user
                    inv.save(using=db, update_fields=["end_user", "updated_at"])
            else:
                inv = cls(order=order, client=order.client, end_user=order.end_user)
                inv.calculate_totals()
                inv.save(using=db)

            inv.ensure_invoice_out_txn()
            # Deliberately do not activate or consume BP here.
            return inv

    def can_release_credit(self):
        return (
            self.allocation_status == "pending"
            and self.credit_used > 0
            and self.deposit_paid >= self.deposit_required
        )

    def ensure_credit_after_deposit(self):
        """
        Activate a pending allocation only after the customer's contribution
        has been received and verified. The account is locked and rechecked.
        """
        if not self.can_release_credit():
            return None
        return self.activate_credit_allocation()

    @transaction.atomic
    def activate_credit_allocation(self):
        db = self._state.db or "default"
        if self.allocation_status != "pending":
            return None
        if self.deposit_paid < self.deposit_required:
            return None
        if self.credit_used <= 0:
            self.allocation_status = "not_required"
            self.settlement_status = "not_applicable"
            self.save(using=db, update_fields=[
                "allocation_status", "settlement_status", "updated_at"
            ])
            return None

        CreditAccount = apps.get_model("credit", "CreditAccount")
        ca = (
            CreditAccount.objects.using(db)
            .select_for_update()
            .filter(client_id=self.client_id)
            .first()
        )
        if not ca or ca.status != CreditAccount.STATUS_ACTIVE:
            raise ValidationError("The buying-power account is not active; allocation cannot be activated.")

        available = r2(ca.credit_available)
        target = r2(self.credit_used)
        if target > available:
            raise ValidationError(
                f"Insufficient buying power. Available: R{available:.2f}; required: R{target:.2f}."
            )

        entry = self.ensure_credit_usage_entry()
        if not entry:
            raise ValidationError("The TA-funded ledger allocation could not be created.")

        self.allocation_status = "active"
        self.settlement_status = "outstanding"
        self.settlement_outstanding = target
        self.save(using=db, update_fields=[
            "allocation_status", "settlement_status",
            "settlement_outstanding", "updated_at",
        ])
        self.ensure_credit_issue_txn()
        self.sync_account_next_due()
        return entry

    # ---------- TDM transaction bookkeeping (intentionally retained) ----------
    def ensure_invoice_out_txn(self):
        from transactions.models import Transaction
        db = self._state.db or "default"
        if not self.pk:
            self.save(using=db)
        txn, created = Transaction.objects.using(db).get_or_create(
            invoice=self, transaction_type="invoice",
            defaults={
                "client": self.client, "amount": self.order_total_inc,
                "reference": f"INV-{self.id}", "note": "Invoice issued",
            },
        )
        if not created and txn.amount != self.order_total_inc:
            txn.amount = self.order_total_inc
            txn.save(using=db, update_fields=["amount"])
        return txn

    def ensure_credit_issue_txn(self):
        from transactions.models import Transaction
        db = self._state.db or "default"
        if self.allocation_status not in {"active", "settled"} or self.credit_used <= 0:
            return None
        tx, created = Transaction.objects.using(db).get_or_create(
            invoice=self, transaction_type="credit_issue",
            defaults={
                "client": self.client, "amount": self.credit_used,
                "reference": f"INV-{self.id} credit funded",
                "note": "TradeAssist funded portion of invoice",
            },
        )
        if not created and r2(tx.amount) != r2(self.credit_used):
            tx.amount = self.credit_used
            tx.save(using=db, update_fields=["amount"])
        return tx

    def remove_credit_issue_txn(self):
        # Retain historical duplicate bookkeeping; do not erase a posted
        # funding transaction merely because account settings later change.
        return None

    def sync_account_next_due(self):
        CreditAccount = apps.get_model("credit", "CreditAccount")
        db = self._state.db or "default"
        ca = CreditAccount.objects.using(db).filter(client_id=self.client_id).first()
        if not ca:
            return
        next_due = (
            Invoice.objects.using(db)
            .filter(
                client_id=self.client_id,
                allocation_status="active",
                settlement_outstanding__gt=0,
                settlement_due_date__isnull=False,
            )
            .order_by("settlement_due_date")
            .values_list("settlement_due_date", flat=True)
            .first()
        )
        ca.next_due_date = next_due
        ca.save(using=db, update_fields=["next_due_date", "updated_at"])

    def ensure_credit_usage_entry(self):
        db = self._state.db or "default"
        existing = CreditEntry.objects.using(db).filter(
            invoice=self, kind=CreditEntry.USAGE,
        ).order_by("-posted_at", "-id").first()
        if existing:
            return existing
        return CreditEntry.record_usage(
            client=self.client, amount=r2(self.credit_used), invoice=self,
            reference=f"INV-{self.id} credit usage",
            note="TradeAssist buying-power allocation after verified contribution",
            using=db,
        )

    def remove_credit_usage_entry(self):
        # Activated ledger entries are financial history. Reverse them with
        # an explicit repayment/reversal process, never by ordinary recalculation.
        return None

    # ---------- Customer contribution payments ----------
    def recalc_deposit_from_transactions(self, save=True):
        total_in = (
            self.transactions.filter(transaction_type__in=self.PAYMENT_TYPES)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )
        self.deposit_paid = r2(total_in)
        self.update_status(save=save)
        self.ensure_credit_after_deposit()

    def record_payment(self, amount, *, reference="", note="", when=None):
        from transactions.models import Transaction
        amt = r2(Decimal(amount))
        if amt <= 0:
            raise ValueError("Amount must be a positive decimal.")
        if self.deposit_paid + amt > self.deposit_required and self.deposit_required > 0:
            # Allow overpayment to be recorded; the excess remains visible in
            # cash transactions, but does not increase TA buying power.
            pass
        self.ensure_invoice_out_txn()
        Transaction.objects.using(self._state.db or "default").create(
            client=self.client, invoice=self, transaction_type="payment",
            amount=amt, reference=reference or f"INV-{self.id} payment",
            note=note, created_at=when or now(),
        )
        self.recalc_deposit_from_transactions(save=True)
        if self.is_fully_paid():
            payment_day = (when or now()).date()
            if self.paid_date != payment_day:
                self.paid_date = payment_day
                self.save(update_fields=["paid_date", "updated_at"])
            # Customer contribution paid = fulfilment may proceed. The TA
            # settlement remains a separate obligation.
            order = self.order
            if order:
                order.refresh_from_db()
                terminal = {"at_warehouse", "ready_for_delivery", "out_for_delivery", "complete", "cancelled"}
                if order.status not in terminal:
                    order.status = "at_warehouse"
                    order.save(update_fields=["status", "updated_at"])

    # ---------- TA settlement / repayments ----------
    def _recalculate_settlement_from_ledger(self):
        db = self._state.db or "default"
        repayments = CreditEntry.objects.using(db).filter(
            invoice=self, kind=CreditEntry.REPAYMENT
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        self.settlement_paid = r2(repayments)
        self.settlement_outstanding = max(
            r2(self.credit_used - self.settlement_paid), Decimal("0.00")
        )
        if self.allocation_status == "active" and self.settlement_outstanding == 0:
            self.allocation_status = "settled"
            self.settlement_status = "settled"
        elif self.allocation_status == "active" and self.settlement_paid > 0:
            self.settlement_status = "partial"
        elif self.allocation_status == "active":
            self.settlement_status = "outstanding"
        self.save(using=db, update_fields=[
            "settlement_paid", "settlement_outstanding",
            "allocation_status", "settlement_status", "updated_at",
        ])

    def record_credit_repayment(self, amount, *, reference="", note="", when=None):
        amt = r2(Decimal(amount))
        if amt <= 0:
            raise ValueError("Amount must be a positive decimal.")
        if self.allocation_status != "active":
            raise ValidationError("This invoice has no active TA-funded balance.")
        if amt > self.settlement_outstanding:
            raise ValidationError("Repayment exceeds this invoice's outstanding TA balance.")
        entry = CreditEntry.record_repayment(
            client=self.client, amount=amt, invoice=self,
            transaction=None, reference=reference or f"INV-{self.id} credit repayment",
            note=note, using=self._state.db or "default",
        )
        self._recalculate_settlement_from_ledger()
        self.sync_account_next_due()
        self.refresh_settlement_status()
        return entry

    def refresh_settlement_status(self, today=None):
        """
        Refresh this invoice's due/grace state and the account's aggregate
        overdue/suspension state. Call from a daily scheduled sweep as well
        as from payment workflows.
        """
        today = today or localdate()
        if self.allocation_status not in {"active", "settled"}:
            return self.settlement_status

        if self.settlement_outstanding <= 0:
            self.settlement_status = "settled"
        elif self.settlement_due_date and today > self.settlement_due_date:
            if self.settlement_grace_end_date and today > self.settlement_grace_end_date:
                self.settlement_status = "suspended"
            else:
                self.settlement_status = "overdue"
        elif self.settlement_paid > 0:
            self.settlement_status = "partial"
        else:
            self.settlement_status = "outstanding"
        self.save(update_fields=["settlement_status", "updated_at"])

        CreditAccount = apps.get_model("credit", "CreditAccount")
        db = self._state.db or "default"
        ca = CreditAccount.objects.using(db).filter(client_id=self.client_id).first()
        if ca and ca.status not in {CreditAccount.STATUS_CLOSED}:
            invoices = Invoice.objects.using(db).filter(
                client_id=self.client_id, allocation_status="active",
                settlement_outstanding__gt=0,
            )
            suspended = any(
                inv.settlement_grace_end_date and today > inv.settlement_grace_end_date
                for inv in invoices
            )
            overdue = any(
                inv.settlement_due_date and today > inv.settlement_due_date
                for inv in invoices
            )
            target_status = (
                CreditAccount.STATUS_SUSPENDED
                if ca.status == CreditAccount.STATUS_SUSPENDED or suspended else
                CreditAccount.STATUS_OVERDUE if overdue else
                CreditAccount.STATUS_ACTIVE
            )
            if ca.status != target_status:
                ca.status = target_status
                ca.status_reason = (
                    "One or more invoice settlements passed the grace period."
                    if suspended else
                    "One or more invoice settlements are overdue."
                    if overdue else
                    "All invoice settlements are within their approved terms."
                )
                ca.save(update_fields=["status", "status_reason", "updated_at"])
        return self.settlement_status

    @classmethod
    def refresh_all_settlement_statuses(cls, today=None, using="default"):
        """
        Daily sweep entry point. Schedule this from the existing task/beat
        configuration so due dates and account suspensions update even when
        no payment event occurs.
        """
        today = today or localdate()
        invoice_ids = cls.objects.using(using).filter(
            allocation_status="active",
            settlement_outstanding__gt=0,
        ).values_list("pk", flat=True)
        for invoice in cls.objects.using(using).filter(pk__in=invoice_ids).iterator():
            invoice.refresh_settlement_status(today=today)

    # ---------- Status helpers: customer contribution ----------
    def is_fully_paid(self):
        return self.deposit_paid >= self.amount_due

    @property
    def is_overdue(self):
        return bool(
            self.due_date and localdate() > self.due_date and not self.is_fully_paid()
        )

    def update_status(self, save=False):
        today = localdate()
        if self.is_fully_paid():
            new_status = "paid"
            if self.paid_date is None:
                self.paid_date = today
        elif self.due_date and today > self.due_date:
            new_status = "overdue"
            self.paid_date = None
        elif self.deposit_paid > 0:
            new_status = "partial"
            self.paid_date = None
        else:
            new_status = "unpaid"
            self.paid_date = None
        self.status = new_status
        if save:
            self.save(update_fields=["status", "deposit_paid", "paid_date", "updated_at"])

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self.allocation_status in {"active", "settled"} or self.credit_entries.exists():
            raise ValidationError(
                "This invoice has TA ledger history. It cannot be deleted; use a controlled reversal process."
            )
        for tx in self.transactions.all().order_by("-created_at", "-id"):
            tx.delete()
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
    # CreditAccount/CreditEntry owns the net exposure calculation.
    # This invoice signal only synchronises the earliest settlement date.
    next_due = (
        Invoice.objects.using(instance._state.db or "default")
        .filter(
            client_id=ca.client_id,
            allocation_status="active",
            settlement_outstanding__gt=0,
            settlement_due_date__isnull=False,
        )
        .order_by("settlement_due_date")
        .values_list("settlement_due_date", flat=True)
        .first()
    )
    ca.next_due_date = next_due
    ca.save(update_fields=["next_due_date"])



@receiver(post_delete, sender=CreditEntry)
def reverse_credit_next_due(sender, instance, **kwargs):
    ca = instance.credit_account
    # CreditAccount/CreditEntry owns the net exposure calculation.
    # This signal only synchronises the earliest settlement date.
    next_due = (
        Invoice.objects.using(instance._state.db or "default")
        .filter(
            client_id=ca.client_id,
            allocation_status="active",
            settlement_outstanding__gt=0,
            settlement_due_date__isnull=False,
        )
        .order_by("settlement_due_date")
        .values_list("settlement_due_date", flat=True)
        .first()
    )
    ca.next_due_date = next_due
    ca.save(update_fields=["next_due_date"])



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
    - is_new_business: whether this is the client's first fully paid invoice for this rep.
    """

    COMMISSION_RATE_CHOICES = [
        (Decimal("1.00"), "1%"),
        (Decimal("1.50"), "1.5%"),
        (Decimal("1.75"), "1.75%"),
        (Decimal("2.00"), "2%"),
        (Decimal("2.25"), "2.25%"),
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

    territory = models.ForeignKey(
        "clients.Territory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
        help_text="Territory of the client at the time of commission.",
    )

    area = models.ForeignKey(
        "clients.Area",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commission_entries",
        help_text="Area of the client at the time of commission.",
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
        default=Decimal("2.25"),  # default 2.25% (new business)
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
        default=Decimal("1.75"),  # default 1.75% (new business)
        help_text="Commission percent for supervisor (on cost).",
    )

    supervisor_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    is_new_business = models.BooleanField(default=False)

    
    created_at = models.DateTimeField(auto_now_add=True)

    period = models.CharField(
        max_length=50,
        blank=True,
        editable=False,
        help_text="Commission period, e.g. 15 Aug - 14 Sep.",
    )

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
        - Copy client from the linked invoice if missing.
        - Copy territory and area from the invoice's client.
        - Automatically determine the supervisor from the rep's SalesRepProfile.
        - Determine the commission period.
        - Keep commission amounts in sync.
        """

        # ---------------------------------------------------------
        # 1. Get invoice and client
        # ---------------------------------------------------------
        invoice = None

        if self.invoice_id:
            invoice = getattr(self, "invoice", None)

            if invoice is None:
                invoice = (
                    Invoice.objects
                    .select_related(
                        "client",
                        "client__territory",
                        "client__area",
                    )
                    .get(pk=self.invoice_id)
                )

        # ---------------------------------------------------------
        # 2. Copy client, territory and area from invoice client
        # ---------------------------------------------------------
        if invoice and invoice.client_id:

            client = invoice.client

            # Client
            if not self.client_id:
                self.client = client

            # Territory
            self.territory = getattr(
                client,
                "territory",
                None,
            )

            # Area
            self.area = getattr(
                client,
                "area",
                None,
            )

        # ---------------------------------------------------------
        # 3. Automatically get supervisor from Rep profile
        # ---------------------------------------------------------
        if self.rep_id:
            from profiles.models import SalesRepProfile

            rep_profile = (
                SalesRepProfile.objects
                .filter(user_id=self.rep_id)
                .select_related("supervisor")
                .first()
            )

            if rep_profile:
                self.supervisor = (
                    rep_profile.supervisor.user
                    if rep_profile.supervisor
                    else None
                )
            else:
                self.supervisor = None

        else:
            self.supervisor = None

        # ---------------------------------------------------------
        # 4. Determine commission period
        #
        # Commission cycle:
        #
        # 15 Aug - 15 Sep
        # 15 Sep - 15 Oct
        # 15 Oct - 15 Nov
        #
        # The invoice date determines the period.
        # ---------------------------------------------------------
        if invoice:

            invoice_date = getattr(invoice, "invoice_date", None)

            if invoice_date:

                if invoice_date.day >= 15:
                    # Period starts on the 15th of the invoice month
                    period_start = invoice_date.replace(day=15)

                    # Period ends on the 15th of the following month
                    if invoice_date.month == 12:
                        period_end = invoice_date.replace(
                            year=invoice_date.year + 1,
                            month=1,
                            day=15,
                        )
                    else:
                        period_end = invoice_date.replace(
                            month=invoice_date.month + 1,
                            day=15,
                        )

                else:
                    # Period started on the 15th of the previous month
                    if invoice_date.month == 1:
                        period_start = invoice_date.replace(
                            year=invoice_date.year - 1,
                            month=12,
                            day=15,
                        )
                    else:
                        period_start = invoice_date.replace(
                            month=invoice_date.month - 1,
                            day=15,
                        )

                    # Period ends on the 15th of the invoice month
                    period_end = invoice_date.replace(day=15)

                self.period = (
                    f"{period_start.strftime('%d %b')} - "
                    f"{period_end.strftime('%d %b')}"
                )

        # ---------------------------------------------------------
        # 5. Calculate commission amounts
        # ---------------------------------------------------------
        self.recompute_amounts()

        # ---------------------------------------------------------
        # 6. Save
        # ---------------------------------------------------------
        super().save(*args, **kwargs)



@receiver(post_save, sender=CommissionEntry)
def commission_entry_post_save_update_targets(
    sender,
    instance: CommissionEntry,
    **kwargs
):
    """
    After a commission entry is saved:

    - Find the rep's MonthlyTargetAllocation
      for the invoice's territory and reporting month.
    - Update the rep allocation target status.
    - Update the territory MonthlyTarget status.
    """

    invoice = instance.invoice
    rep = instance.rep

    if not invoice or not invoice.paid_date or not rep:
        return

    # ---------------------------------------------------------
    # Invoice reporting period
    # ---------------------------------------------------------

    paid_day = invoice.paid_date
    month_code = paid_day.strftime("%b").upper()[:3]

    # ---------------------------------------------------------
    # Client territory
    # ---------------------------------------------------------

    territory_id = invoice.client.territory_id

    if not territory_id:
        return

    # ---------------------------------------------------------
    # Find this rep's allocation for this territory/month
    # ---------------------------------------------------------

    allocation = (
        MonthlyTargetAllocation.objects
        .filter(
            sales_rep=rep,
            monthly_target__year=paid_day.year,
            monthly_target__month=month_code,
            monthly_target__territory_id=territory_id,
        )
        .first()
    )

    # ---------------------------------------------------------
    # Update target statuses
    # ---------------------------------------------------------

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

def get_commission_period_for_date(paid_day):
    """
    Return the 15th-to-15th commission period
    containing the supplied date.
    """

    if paid_day.day >= 15:
        if paid_day.month == 12:
            start_date = date(
                paid_day.year,
                paid_day.month,
                15,
            )
            end_date = date(
                paid_day.year + 1,
                1,
                15,
            )
        else:
            start_date = date(
                paid_day.year,
                paid_day.month,
                15,
            )
            end_date = date(
                paid_day.year,
                paid_day.month + 1,
                15,
            )

    else:
        if paid_day.month == 1:
            start_date = date(
                paid_day.year - 1,
                12,
                15,
            )
        else:
            start_date = date(
                paid_day.year,
                paid_day.month - 1,
                15,
            )

        end_date = date(
            paid_day.year,
            paid_day.month,
            15,
        )

    return start_date, end_date



def get_commission_period(year: int, month: int):
    """
    Return the commission period for a reporting month.

    The commission month runs from the 15th of the
    previous calendar month through the 15th of
    the requested calendar month, inclusive.

    Example:
        August 2026
        = 15 July 2026 -> 15 August 2026
    """

    if month == 1:
        previous_month = 12
        previous_year = year - 1
    else:
        previous_month = month - 1
        previous_year = year

    start_date = date(previous_year, previous_month, 15)
    end_date = date(year, month, 15)

    return start_date, end_date


def weeks_in_month(year: int, month: int) -> Decimal:
    """Return a reasonable week count for a month (ceil(days/7))."""
    days = monthrange(year, month)[1]
    return Decimal(str(math.ceil(days / 7)))


def invoice_qualifies_for_new_business_bonus(invoice: Invoice, rep) -> bool:
    """
    A commission entry qualifies as new business when this is the
    client's first fully paid, commission-generating invoice for this rep.

    Rules:
    1. The invoice must have a paid_date.
    2. A rep must exist.
    3. The client must not have any previous commission-generating
       invoice for this same rep.
    4. The month or target achievement does not affect whether the
       invoice is new business.

    First paid invoice = New Business.
    All subsequent paid invoices = Repeat Business.
    """

    if not invoice.paid_date or not rep:
        return False

    client = invoice.client

    # --------------------------------------------------
    # Check whether this client has previously generated
    # a commission entry for this same rep.
    #
    # If a previous paid commission exists, this is
    # repeat business.
    # --------------------------------------------------
    prior_commission_exists = (
        CommissionEntry.objects
        .filter(
            rep=rep,
            invoice__client=client,
        )
        .exclude(invoice=invoice)
        .filter(
            models.Q(invoice__paid_date__lt=invoice.paid_date)
            |
            models.Q(
                invoice__paid_date=invoice.paid_date,
                invoice_id__lt=invoice.id,
            )
        )
        .exists()
    )

    # No previous paid commission = first paid invoice
    # = new business.
    return not prior_commission_exists



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
    - Supervisor: taken from the rep's SalesRepProfile.supervisor.
    - SalesRepProfile.supervisor is a StaffProfile, so we convert it
      to the linked User before assigning it to CommissionEntry.supervisor.
    """

    client = invoice.client

    # ---------------------------------------------------------
    # 1. Main sales rep
    # ---------------------------------------------------------
    # Client.account_manager is already a User.
    rep = getattr(client, "account_manager", None)

    # ---------------------------------------------------------
    # 2. Supervisor
    # ---------------------------------------------------------
    supervisor = None

    if rep is not None:

        # SalesRepProfile linked to the rep's User
        sales_profile = getattr(
            rep,
            "sales_rep_profile",
            None,
        )

        if sales_profile:

            # SalesRepProfile.supervisor is a StaffProfile.
            staff_profile = getattr(
                sales_profile,
                "supervisor",
                None,
            )

            if staff_profile:

                # CommissionEntry.supervisor expects a User.
                supervisor = getattr(
                    staff_profile,
                    "user",
                    None,
                )

    return rep, supervisor


def create_or_update_commission_entry_for_invoice(invoice: Invoice) -> CommissionEntry:
    """
    Create or update CommissionEntry for a fully paid invoice.

        New logic:
        - Rep is resolved from client.account_manager.
        - The client's first fully paid invoice for that rep is new business.
        - All subsequent fully paid invoices for that client are repeat business.
        - New-business Rep rate = 2.25%.
        - Repeat-business Rep rate = 1.50%.
        - New-business Supervisor rate = 1.75%.
        - Repeat-business Supervisor rate = 1.00%.
    """

    rep, supervisor = resolve_rep_and_supervisor_for_invoice(invoice)

    cost_total = compute_invoice_cost_excl(invoice)

    is_new = invoice_qualifies_for_new_business_bonus(invoice, rep)

    rep_rate_pct = Decimal("2.25") if is_new else Decimal("1.50")
    supervisor_rate_pct = Decimal("1.75") if is_new else Decimal("1.00")

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
    first_day, last_day = get_commission_period(year, month)

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
    Master target for a territory and reporting period.

    Example:
        Soweto Territory 1 - August 2026
            Reporting Period: 15 July - 15 August 2026
            Total Revenue Target: R50,000
            Total Client Target: 10

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

    
    month = models.CharField(
        max_length=3,
        choices=MONTH_CHOICES,
        help_text="Month in which the reporting period ends on the 15th."
    )
    year = models.IntegerField(choices=YEAR_CHOICES)
    quarter = models.CharField(max_length=2, choices=QUARTER_CHOICES)
    territory = models.ForeignKey(
        "clients.Territory",
        on_delete=models.PROTECT,
        related_name="monthly_targets",
        null=True,
        blank=True,
    )

    monthly_target = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total rand value target for this territory and reporting period."
    )

    total_client_target = models.PositiveIntegerField(
        default=0,
        help_text="Total new recurring client target for this territory and reporting period."
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
        unique_together = ("month", "year", "territory")
        ordering = ["-year", "month"]

    def __str__(self):
        return f"{self.territory} - {self.get_month_display()} {self.year}"

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
        """
        Number of calendar days in the 15th-to-15th
        reporting period.
        """

        start_date, end_date = self.get_period_dates()

        return (end_date - start_date).days + 1

    def get_total_working_days(self):
        """
        Count working days in the 15th-to-15th reporting period.

        Weekends and configured public holidays are excluded.
        """

        first_day, last_day = self.get_period_dates()

        holidays = PUBLIC_HOLIDAYS.get(self.year)

        if holidays is None:
            raise ValueError(
                f"No public holidays configured for year {self.year}"
            )

        working_days = 0
        current_date = first_day

        while current_date <= last_day:

            if (
                current_date.weekday() < 5
                and current_date not in holidays
            ):
                working_days += 1

            current_date += timedelta(days=1)

        return working_days

    def get_daily_target(self):
        working_days = self.get_total_working_days()

        if working_days <= 0:
            return Decimal("0.00")

        return (
            self.monthly_target / Decimal(working_days)
        ).quantize(Decimal("0.01"))

    def get_period_dates(self):
        """
        Return the 15th-to-15th reporting period for this target.

        Example:
            August 2026
            = 15 July 2026 through 15 August 2026.
        """

        month_number = self.get_month_number()

        # Start = 15th of the previous calendar month
        if month_number == 1:
            start_date = date(
                self.year - 1,
                12,
                15,
            )
        else:
            start_date = date(
                self.year,
                month_number - 1,
                15,
            )

        # End = 15th of the target month
        end_date = date(
            self.year,
            month_number,
            15,
        )

        return start_date, end_date

    def get_actual_revenue(self):
        """
        Total paid invoice revenue for this territory
        during the 15th-to-15th reporting period.
        """

        first_day, last_day = self.get_period_dates()

        total = (
            Invoice.objects.filter(
                status="paid",
                paid_date__gte=first_day,
                paid_date__lte=last_day,
                client__territory=self.territory,
            ).aggregate(
                s=Sum("order_total_inc")
            )["s"]
            or Decimal("0.00")
        )

        return total.quantize(Decimal("0.01"))

    def get_actual_clients(self):
        """
        Total unique commission-generating clients for this territory
        during the 15th-to-15th reporting period.
        """

        first_day, last_day = self.get_period_dates()

        return (
            CommissionEntry.objects
            .filter(
                invoice__paid_date__gte=first_day,
                invoice__paid_date__lte=last_day,
                invoice__client__territory=self.territory,
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

    def sync_rep_allocations(self):
        """
        Automatically create/update MonthlyTargetAllocation records
        for every active sales representative assigned to this territory.

        The territory determines which representatives belong to
        this monthly target.

        Example:

            Territory: Orlando East
            Total Revenue Target: R100,000
            Total Client Target: 20
            Representatives: 5

            Each representative receives:

                Revenue Target: R20,000
                Client Target: 4
        """

        # --------------------------------------------------
        # 1. Target must already exist and have a territory
        # --------------------------------------------------
        if not self.pk or not self.territory_id:
            return

        from profiles.models import SalesRepProfile

        # --------------------------------------------------
        # 2. Find representatives assigned to this territory
        #
        #    Requirements:
        #    - SalesRepProfile territory = this target territory
        #    - Profile is active
        #    - User has the Representative role
        # --------------------------------------------------
        rep_profiles = (
            SalesRepProfile.objects
            .filter(
                territory_id=self.territory_id,
                roles__name__iexact="Representative",
            )
            .select_related("user")
            .distinct()
            .order_by(
                "user__first_name",
                "user__last_name",
                "user__username",
            )
        )

        # --------------------------------------------------
        # 3. Get the actual Users
        # --------------------------------------------------
        reps = [
            profile.user
            for profile in rep_profiles
            if profile.user_id
        ]

        # --------------------------------------------------
        # 4. No representatives = no allocations
        # --------------------------------------------------
        if not reps:
            self.rep_allocations.all().delete()
            return

        rep_count = len(reps)

        # --------------------------------------------------
        # 5. Divide the revenue target equally
        # --------------------------------------------------
        total_value = self.monthly_target or Decimal("0.00")

        base_value = (
            total_value / Decimal(rep_count)
        ).quantize(Decimal("0.01"))

        # --------------------------------------------------
        # 6. Divide the client target equally
        # --------------------------------------------------
        total_clients = self.total_client_target or 0

        base_clients = total_clients // rep_count
        client_remainder = total_clients % rep_count

        # --------------------------------------------------
        # 7. Create/update an allocation for each rep
        # --------------------------------------------------
        existing_rep_ids = set()

        for index, rep in enumerate(reps):

            # Distribute any remainder across the first reps.
            if index < client_remainder:
                client_target = base_clients + 1
            else:
                client_target = base_clients

            existing_rep_ids.add(rep.id)

            MonthlyTargetAllocation.objects.update_or_create(
                monthly_target=self,
                sales_rep=rep,
                defaults={
                    "monthly_target_value": base_value,
                    "client_target": client_target,
                },
            )

        # --------------------------------------------------
        # 8. Fix revenue rounding
        #
        # Example:
        # R100 / 3 = R33.33 each
        #
        # R33.33 x 3 = R99.99
        #
        # Add the R0.01 remainder to the last rep.
        # --------------------------------------------------
        allocations = list(
            self.rep_allocations
            .filter(
                sales_rep_id__in=existing_rep_ids
            )
            .order_by(
                "sales_rep__first_name",
                "sales_rep__last_name",
                "sales_rep__username",
            )
        )

        allocated_total = sum(
            allocation.monthly_target_value
            for allocation in allocations
        )

        difference = (
            total_value - allocated_total
        ).quantize(Decimal("0.01"))

        if difference and allocations:

            last_allocation = allocations[-1]

            last_allocation.monthly_target_value = (
                last_allocation.monthly_target_value + difference
            )

            last_allocation.save(
                update_fields=[
                    "monthly_target_value",
                    "updated_at",
                ]
            )

        # --------------------------------------------------
        # 9. Remove allocations for reps who are no longer
        #    assigned to this territory.
        # --------------------------------------------------
        self.rep_allocations.exclude(
            sales_rep_id__in=existing_rep_ids
        ).delete()   



    def check_and_set_target_reached(self):
        """
        Automatically sets timestamps once territory-level targets are achieved.
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

    

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        # Automatically rebuild rep allocations
        # whenever the monthly target is saved.
        self.sync_rep_allocations()


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
                client__territory=self.monthly_target.territory,
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
                invoice__client__territory=self.monthly_target.territory,
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