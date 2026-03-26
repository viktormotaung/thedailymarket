# credit/models.py
from __future__ import annotations
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from decimal import Decimal
from typing import Dict, Tuple, Optional
from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete

from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils.timezone import now

from clients.models import Client
import logging

logger = logging.getLogger(__name__)

# ============================================================
# Helpers
# ============================================================

def r2(x: Decimal | None) -> Decimal:
    """Round to 2 decimals safely."""
    if x is None:
        x = Decimal("0.00")
    return Decimal(x).quantize(Decimal("0.01"))


def monday_of(d: date) -> date:
    """Return ISO-week Monday for a given date."""
    return d - timedelta(days=d.weekday())

def update_funder_week_summary(entry):
    """
    Recalculate weekly funder summary (idempotent & multi-DB safe).

    Always derives values from CreditEntry (source of truth),
    preventing double counting and ensuring correctness.
    """

    from decimal import Decimal
    from datetime import timedelta
    from django.db.models import Sum
    from django.db.models.functions import Coalesce

    # --------------------------------------------------
    # Resolve funder
    # --------------------------------------------------
    ca = entry.credit_account
    funder = ca.funder

    if not funder:
        return

    db = entry._state.db or "default"

    # --------------------------------------------------
    # Determine week range
    # --------------------------------------------------
    week_start = monday_of(entry.posted_at.date())
    week_end = week_start + timedelta(days=7)

    # --------------------------------------------------
    # 🔥 RECOMPUTE FROM LEDGER (SOURCE OF TRUTH)
    # --------------------------------------------------
    total_usage = (
        CreditEntry.objects.using(db)
        .filter(
            credit_account__funder=funder,
            kind=CreditEntry.USAGE,
            posted_at__gte=week_start,
            posted_at__lt=week_end,
        )
        .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
    )

    total_usage = r2(total_usage)

    # --------------------------------------------------
    # Capital cap (allocation constraint)
    # --------------------------------------------------
    allocated_capital = funder.total_allocated()

    visible_utilization = min(total_usage, allocated_capital)

    # --------------------------------------------------
    # Weekly return calculation
    # --------------------------------------------------
    existing = (
        FunderWeekSummary.objects.using(db)
        .filter(funder=funder, week_start=week_start)
        .only("weekly_rate_pct_snapshot")
        .first()
    )

    weekly_rate = (
        existing.weekly_rate_pct_snapshot
        if existing
        else funder.weekly_rate_pct
    )

    weekly_return = r2(
        visible_utilization * (weekly_rate / Decimal("100"))
    )

    # --------------------------------------------------
    # Save (idempotent)
    # --------------------------------------------------
    FunderWeekSummary.objects.using(db).update_or_create(
        funder=funder,
        week_start=week_start,
        defaults={
            "raw_weekly_usage": total_usage,
            "visible_utilization_total": visible_utilization,
            "weekly_rate_pct_snapshot": weekly_rate,
            "weekly_return": weekly_return,
        },
    )



from contextlib import contextmanager
import threading

_credit_ledger_ctx = threading.local()

@contextmanager
def bypass_ledger():
    _credit_ledger_ctx.bypass = True
    try:
        yield
    finally:
        _credit_ledger_ctx.bypass = False

def is_bypassing_ledger():
    return getattr(_credit_ledger_ctx, "bypass", False)

# ============================================================
# FUNDER (capital owner)
# ============================================================

class Funder(models.Model):
    name = models.CharField(max_length=120, unique=True)

    weekly_rate_pct = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Weekly percentage return charged on capped utilization.",
    )

    balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Live balance held for this funder.",
    )

    is_dummy = models.BooleanField(
        default=False,
        help_text="Indicates whether this funder is for internal/dummy use only."
    )

    allocated_clients = models.ManyToManyField(
        Client,
        through="FunderAllocation",
        related_name="funders",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} · Balance R{self.balance:.2f}"

    # ---------------------------
    # Balance mutations
    # ---------------------------

    def apply_delta(self, delta: Decimal) -> None:
        """Apply a signed balance change."""
        if not delta:
            return
        self.balance = r2((self.balance or Decimal("0.00")) + r2(delta))

        self.save(update_fields=["balance", "updated_at"])

    # ---------------------------
    # Allocation helpers
    # ---------------------------

    def allocation_for(self, client: Client) -> Decimal:
        db = self._state.db or "default"

        amt = (
            self.allocations.using(db)
            .filter(client=client)
            .values_list("amount", flat=True)
            .first()
        )
        return r2(amt or Decimal("0.00"))

    @property
    def allocatable_balance(self) -> Decimal:
        return r2(self.balance - self.total_allocated())

    def allocation_for(self, client: Client) -> Decimal:
        amt = (
            self.allocations
            .filter(client=client)
            .values_list("amount", flat=True)
            .first()
        )
        return r2(amt or Decimal("0.00"))
    
    def total_allocated(self):
        db = self._state.db or "default"

        return r2(
            self.allocations.using(db).aggregate(
                s=Coalesce(Sum("amount"), Decimal("0.00"))
            )["s"]
        )

    # ---------------------------
    # Membership helpers
    # ---------------------------

    def users(self):
        User = get_user_model()
        return User.objects.filter(
            funder_memberships__funder=self,
            funder_memberships__is_active=True,
        ).distinct()

    def has_user(self, user) -> bool:
        return FunderMember.objects.filter(
            funder=self, user=user, is_active=True
        ).exists()

# ============================================================
# FUNDER MEMBERSHIP (users linked to funder)
# ============================================================

ROLE_CHOICES = (
    ("OWNER", "Owner"),
    ("MANAGER", "Manager"),
    ("VIEWER", "Viewer"),
)


class ActiveMembershipManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)




class FunderMember(models.Model):
    funder = models.ForeignKey(
        "credit.Funder",
        on_delete=models.CASCADE,
        related_name="memberships",
        null=True,
        blank=True,
    )

    # ✅ BACK TO CLEAN FK
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="funder_memberships",
    )

    ROLE_CHOICES = [
        ("OWNER", "Owner"),
        ("ADMIN", "Admin"),
        ("VIEWER", "Viewer"),
    ]

    role = models.CharField(
        max_length=16,
        choices=ROLE_CHOICES,
        default="VIEWER",
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["funder", "user"],
                name="uniq_funder_user",
                condition=models.Q(funder__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=["funder"]),
            models.Index(fields=["user"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.user} → {self.funder or 'No Funder'} ({self.role})"
    
# ============================================================
# FUNDER ALLOCATION (capital reserved per client)
# ============================================================

class FunderAllocation(models.Model):
    funder = models.ForeignKey(
        "credit.Funder",
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.CASCADE,
        related_name="funder_allocations",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("funder", "client")]
        ordering = ["funder_id", "client_id"]

    def __str__(self):
        return f"{self.funder.name} → {self.client} · R{self.amount:.2f}"

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------
    def clean(self):
        db = self._state.db or "default"

        others = (
            FunderAllocation.objects.using(db)
            .filter(funder=self.funder)
            .exclude(pk=self.pk)
            .aggregate(s=Coalesce(Sum("amount"), Decimal("0.00")))["s"]
        )

        proposed = (others or Decimal("0.00")) + self.amount

        if proposed > self.funder.balance:
            raise ValidationError(
                "Allocation exceeds available funder balance."
            )

    # --------------------------------------------------
    # APPLY TO CREDIT ACCOUNT (CORE LOGIC)
    # --------------------------------------------------
    def apply_to_credit_account(self):
        db = self._state.db or "default"

        from credit.models import CreditAccount

        ca, _ = CreditAccount.objects.using(db).get_or_create(
            client=self.client
        )

        # ---------------------------------------------
        # 1. Link funder
        # ---------------------------------------------
        if ca.funder != self.funder:
            ca.funder = self.funder
            ca.save(update_fields=["funder", "updated_at"])

        # ---------------------------------------------
        # 2. 🔥 ALWAYS use ledger system
        # ---------------------------------------------
        ca.set_limit(
            new_limit=self.amount,
            authorised_by=None,
            note=f"Auto allocation from funder {self.funder.name}",
        )

    # --------------------------------------------------
    # SAVE (ENTRY POINT)
    # --------------------------------------------------
    @transaction.atomic
    def save(self, *args, **kwargs):
        db = kwargs.pop("using", None) or self._state.db or "default"

        self.full_clean()

        super().save(*args, **kwargs)

        # 🔥 Ensure correct DB context
        self._state.db = db

        # 🔥 Apply allocation AFTER save
        self.apply_to_credit_account()



# ============================================================
# FUNDER MOVEMENTS (top-ups / payouts)
# ============================================================

class FunderMovement(models.Model):
    TOPUP = "topup"
    PAYOUT = "payout"
    ADJUST = "adjustment"

    KIND_CHOICES = [
        (TOPUP, "Top-up"),
        (PAYOUT, "Payout"),
        (ADJUST, "Manual Adjustment"),
    ]

    funder = models.ForeignKey(
        Funder,
        on_delete=models.CASCADE,
        related_name="movements",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["funder", "created_at"])]

    def __str__(self):
        sign = "+" if self.kind in {self.TOPUP, self.ADJUST} else "-"
        return f"{self.funder.name} · {self.kind} · {sign}R{self.amount:.2f}"

    def signed_amount(self) -> Decimal:
        amt = r2(self.amount)
        if self.kind == self.PAYOUT:
            return -amt
        return amt

    @transaction.atomic
    def save(self, *args, **kwargs):
        creating = self.pk is None
        previous = None
        if not creating:
            db = self._state.db or "default"

            previous = FunderMovement.objects.using(db).get(pk=self.pk)

        super().save(*args, **kwargs)

        if creating:
            self.funder.apply_delta(self.signed_amount())
        else:
            delta = self.signed_amount() - previous.signed_amount()
            if delta:
                self.funder.apply_delta(delta)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        self.funder.apply_delta(-self.signed_amount())
        super().delete(*args, **kwargs)

# ============================================================
# CREDIT ACCOUNT (per client)
# ============================================================


class CreditAccount(models.Model):
    TERM_CHOICES = [
        ("0D", "0 Day (Cash)"),
        ("3D", "3 Day Credit"),
        ("7D", "7 Day Credit"),
    ]

    DEPOSIT_CHOICES = [
        (Decimal("0.00"), "0%"),
        (Decimal("30.00"), "30%"),
        (Decimal("50.00"), "50%"),
        (Decimal("100.00"), "100%"),
    ]

    client = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name="credit_account",
    )

    funder = models.ForeignKey(
        Funder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_accounts",
    )

    # ---------------------------
    # Commercial terms
    # ---------------------------
    payment_term = models.CharField(
        max_length=3,
        choices=TERM_CHOICES,
        default="0D",
    )

    credit_deposit_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=DEPOSIT_CHOICES,
        default=Decimal("100.00"),
    )

    # ---------------------------
    # Ledger-controlled fields
    # ---------------------------
    credit_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    credit_used = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    next_due_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["client"]),
            models.Index(fields=["funder"]),
        ]

    def __str__(self):
        return f"{self.client} · Limit R{self.credit_limit:.2f} · Used R{self.credit_used:.2f}"

    # =====================================================
    # DERIVED VALUES
    # =====================================================
    @property
    def credit_available(self):
        return r2(self.credit_limit - self.credit_used)

    @property
    def outstanding(self):
        return r2(self.credit_used)

    # =====================================================
    # VALIDATION (🔥 FIXED)
    # =====================================================
    def clean(self):
        super().clean()

        if not self.client:
            return

        db = self._state.db or "default"

        exists = (
            CreditAccount.objects.using(db)
            .filter(client=self.client)
            .exclude(pk=self.pk)
            .exists()
        )

        if exists:
            raise ValidationError({
                "client": "Credit account with this client already exists."
            })

    # =====================================================
    # LIMIT CONTROL (AUDIT ONLY)
    # =====================================================
    @transaction.atomic
    def set_limit(
        self,
        new_limit: Decimal,
        *,
        authorised_by=None,
        note: str = "",
    ):
        prev = r2(self.credit_limit)
        new = r2(new_limit)

        if prev == new:
            return

        db = self._state.db or "default"

        CreditLog.objects.using(db).create(
            credit_account=self,
            previous_limit=prev,
            new_limit=new,
            amount_changed=r2(new - prev),
            authorised_by=authorised_by,
            note=note,
        )

    # =====================================================
    # LEDGER-BASED RECALCULATION
    # =====================================================
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        db = self._state.db or "default"

        totals = self.entries.using(db).aggregate(
            usage=Coalesce(
                Sum("amount", filter=models.Q(kind=CreditEntry.USAGE)),
                Decimal("0.00"),
            ),
            repayment=Coalesce(
                Sum("amount", filter=models.Q(kind=CreditEntry.REPAYMENT)),
                Decimal("0.00"),
            ),
            writeoff=Coalesce(
                Sum("amount", filter=models.Q(kind=CreditEntry.WRITEOFF)),
                Decimal("0.00"),
            ),
        )

        new_used = r2(
            (totals["usage"] or Decimal("0.00"))
            - (totals["repayment"] or Decimal("0.00"))
            - (totals["writeoff"] or Decimal("0.00"))
        )

        if new_used != self.credit_used:
            self.credit_used = new_used
            models.Model.save(self, update_fields=["credit_used", "updated_at"])

# ============================================================
# CREDIT LOG (limit audit trail)
# ============================================================

class CreditLog(models.Model):
    """
    Audit record for credit limit changes.
    Emits ISSUE / LIMIT_DECREASE ledger entries in Part 3.
    """

    credit_account = models.ForeignKey(
        CreditAccount,
        on_delete=models.CASCADE,
        related_name="logs",
    )

    previous_limit = models.DecimalField(max_digits=12, decimal_places=2)
    new_limit = models.DecimalField(max_digits=12, decimal_places=2)
    amount_changed = models.DecimalField(max_digits=12, decimal_places=2)

    authorised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_logs",
    )

    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["credit_account", "created_at"]),
        ]

    def __str__(self):
        sign = "+" if self.amount_changed > 0 else ""
        user = self.authorised_by.get_full_name() if self.authorised_by else "System"
        return (
            f"{self.credit_account.client} · "
            f"{sign}R{self.amount_changed:.2f} · "
            f"{user}"
        )

    # ---------------------------
    # Validation
    # ---------------------------

    def clean(self):
        delta = r2(self.new_limit - self.previous_limit)
        if delta <= 0:
            return

        ca = self.credit_account
        if not ca.funder:
            raise ValidationError(
                "Cannot increase credit limit without assigning a funder."
            )

        db = self._state.db or "default"

        allocated = (
            FunderAllocation.objects.using(db)
            .filter(client=ca.client)
            .aggregate(
                s=Coalesce(Sum("amount"), Decimal("0.00"))
            )["s"]
        )

        if r2(self.new_limit) > r2(allocated):
            raise ValidationError(
                f"Proposed limit R{self.new_limit:.2f} exceeds allocated capital "
                f"R{allocated:.2f}."
            )

    @transaction.atomic
    def save(self, *args, **kwargs):
        is_create = self.pk is None

        # Validate first
        self.full_clean()

        # Save the log
        super().save(*args, **kwargs)

        if not is_create:
            return

        # Calculate change
        delta = r2(self.new_limit - self.previous_limit)
        if delta == 0:
            return

        # 🔥 Always resolve DB AFTER save
        db = self._state.db or "default"

        ca = self.credit_account

        # ✅ Create ONE ledger entry (correct DB)
        CreditEntry.objects.using(db).create(
            credit_account=ca,
            kind=(
                CreditEntry.ISSUE
                if delta > 0
                else CreditEntry.LIMIT_DECREASE
            ),
            amount=abs(delta),
            reference=f"CREDIT-LIMIT-{self.pk}",
            note=self.note,
        )

        # ✅ Update actual account limit
        ca.credit_limit = self.new_limit
        ca.save(update_fields=["credit_limit", "updated_at"])

# ============================================================
# CREDIT ENTRY (LEDGER — SINGLE SOURCE OF TRUTH)
# ============================================================

class CreditEntry(models.Model):
    # Ledger kinds
    USAGE          = "usage"           # credit consumed (used +)
    REPAYMENT      = "repayment"       # credit repaid (used -)
    ADJUSTMENT     = "adjustment"      # manual correction (used +/-)
    WRITEOFF       = "writeoff"        # bad debt (used -)
    ISSUE          = "issue"           # credit limit increase (limit +)
    LIMIT_DECREASE = "limit_decrease"  # credit limit decrease (limit -)

    KIND_CHOICES = [
        (USAGE, "Credit Used"),
        (REPAYMENT, "Credit Repaid"),
        (ADJUSTMENT, "Adjustment"),
        (WRITEOFF, "Write-off"),
        (ISSUE, "Limit Increase"),
        (LIMIT_DECREASE, "Limit Decrease"),
    ]

    credit_account = models.ForeignKey(
        CreditAccount,
        on_delete=models.CASCADE,
        related_name="entries",
    )

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Running available credit after this entry."
    )

    posted_at = models.DateTimeField(default=now, db_index=True)

    # Optional traceability
    invoice = models.ForeignKey(
        "invoices.Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_entries",
    )

    transaction = models.ForeignKey(
        "transactions.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_entries",
    )

    reference = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_entries_created",
    )

    class Meta:
        ordering = ["-posted_at", "-id"]
        indexes = [
            models.Index(fields=["credit_account", "posted_at"]),
            models.Index(fields=["kind", "posted_at"]),
        ]

    def __str__(self):
        return (
            f"{self.credit_account.client} · "
            f"{self.kind} · R{self.amount:.2f}"
        )

    @classmethod
    def check_50pct_rule(cls, client: Client, using="default") -> Tuple[bool, Optional[str]]:
        from invoices.models import Invoice

        db = using or "default"

        last_invoice = (
            Invoice.objects.using(db)
            .filter(client=client, credit_used__gt=0)
            .order_by("-created_at", "-id")
            .first()
        )

        if not last_invoice:
            return True, None

        ca, _ = CreditAccount.objects.using(db).get_or_create(client=client)

        last_usage = (
            cls.objects.using(db)
            .filter(credit_account=ca, kind=cls.USAGE)
            .order_by("-posted_at", "-id")
            .first()
        )

        if not last_usage:
            return False, "Missing credit usage entry."

        if r2(last_usage.amount) != r2(last_invoice.credit_used):
            return False, "Invoice and credit ledger mismatch."

        repayment = (
            cls.objects.using(db)
            .filter(
                credit_account=ca,
                kind=cls.REPAYMENT,
                posted_at__gt=last_usage.posted_at,
            )
            .order_by("posted_at", "id")
            .first()
        )

        if not repayment:
            return False, "No repayment after last credit usage."

        if r2(repayment.amount) < r2(last_usage.amount * Decimal("0.50")):
            return False, "Repayment less than 50% of last credit usage."

        return True, None
    
    # ---------------------------
    # Convenience creators
    # ---------------------------


    @classmethod
    def record_usage(
        cls,
        *,
        client: Client,
        amount: Decimal,
        invoice=None,
        reference: str = "",
        note: str = "",
        created_by=None,
        using=None,  # ✅ ADD THIS
    ) -> "CreditEntry":

        db = using or "default"

        ca, _ = CreditAccount.objects.using(db).get_or_create(client=client)

        amount = r2(amount)

        # Get latest ledger balance (available credit)
        last_entry = (
            ca.entries.using(db)
            .order_by("-id")
            .first()
        )

        current_available = last_entry.balance if last_entry else Decimal("0.00")

        # Calculate new available after this usage
        new_available = r2(current_available - amount)

        # 🚨 OPTIONAL LIMIT ENFORCEMENT
        # If you still want to prevent going beyond assigned limit:
        #
        # outstanding = ca.credit_limit - new_available
        # if outstanding > ca.credit_limit:
        #     raise ValidationError(
        #         f"Credit limit exceeded. "
        #         f"Limit: R{ca.credit_limit:.2f}, "
        #         f"Available: R{current_available:.2f}"
        #     )
        #
        # Since you allowed negative balance, we are not blocking it.

        return cls.objects.using(db).create(
            credit_account=ca,
            kind=cls.USAGE,
            amount=amount,
            invoice=invoice,
            reference=reference,
            note=note,
            created_by=created_by,
        )


    @classmethod
    def record_repayment(
        cls,
        *,
        client: Client,
        amount: Decimal,
        invoice=None,
        transaction=None,  # ✅ ADD THIS
        reference: str = "",
        note: str = "",
        created_by=None,
        using=None,
    ) -> "CreditEntry":

        db = using or "default"

        ca, _ = CreditAccount.objects.using(db).get_or_create(client=client)

        return cls.objects.using(db).create(
            credit_account=ca,
            kind=cls.REPAYMENT,
            amount=r2(amount),
            invoice=invoice,
            transaction=transaction,
            reference=reference,
            note=note,
            created_by=created_by,
        )
    
    def save(self, *args, **kwargs):
        is_create = self.pk is None

        if is_create:
            db = self._state.db or "default"

            last_entry = (
                CreditEntry.objects.using(db)
                .filter(credit_account=self.credit_account)
                .order_by("-id")
                .first()
            )

            previous_balance = last_entry.balance if last_entry else Decimal("0.00")

            if self.kind in (self.ISSUE, self.REPAYMENT, self.WRITEOFF):
                new_balance = previous_balance + self.amount

            elif self.kind in (self.USAGE, self.LIMIT_DECREASE):
                new_balance = previous_balance - self.amount

            elif self.kind == self.ADJUSTMENT:
                new_balance = previous_balance + self.amount

            else:
                new_balance = previous_balance

            self.balance = r2(new_balance)

        # Save ledger entry
        super().save(*args, **kwargs)

        # Recalculate credit account usage
        self.credit_account.save()

        # ---------------------------------------------------
        # Update weekly funder summary
        # ---------------------------------------------------
        if is_create and self.kind == self.USAGE:
            update_funder_week_summary(self)



from django.db.models.signals import post_delete
from django.dispatch import receiver


@receiver(post_delete, sender=CreditEntry)
def update_summary_on_delete(sender, instance, **kwargs):
    update_funder_week_summary(instance)

@receiver(post_save, sender=CreditEntry)
def update_summary_on_save(sender, instance, created, **kwargs):
    if instance.kind == CreditEntry.USAGE:
        update_funder_week_summary(instance)


# ============================================================
# FUNDER WEEK SUMMARY (DERIVED REPORTING MODEL)
# ============================================================

class FunderWeekSummary(models.Model):
    """
    Weekly roll-up for a funder.
    This is a REPORTING model – NOT a source of truth.
    Values are derived from CreditEntry.
    """

    funder = models.ForeignKey(
        Funder,
        on_delete=models.CASCADE,
        related_name="week_summaries",
    )

    week_start = models.DateField(
        help_text="ISO week Monday",
        db_index=True,
    )

    raw_weekly_usage = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total credit usage recorded this week before applying the funder cap.",
    )


    visible_utilization_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Sum of capped client utilization for the week.",
    )

    weekly_rate_pct_snapshot = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Weekly rate at time of calculation.",
    )

    weekly_return = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Amount owed to funder for the week.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("funder", "week_start")]
        ordering = ["-week_start", "funder_id"]
        indexes = [
            models.Index(fields=["funder", "week_start"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.week_start} · {self.funder.name} · "
            f"Return R{self.weekly_return:.2f}"
        )
