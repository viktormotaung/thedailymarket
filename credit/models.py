# credit/models.py
from __future__ import annotations
from decimal import Decimal
from typing import Tuple, Optional
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
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


def settlement_due_date(start_date: date, payment_term: str) -> date:
    """Calculate a fixed invoice due date; invoice date is Day 1."""
    days = {"0D": 1, "1D": 1, "3D": 3, "7D": 7}.get(payment_term, 1)
    return start_date + timedelta(days=days - 1)

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
    PROFIT_MODE_CHOICES = [
        ("PAYOUT", "Payout"),
        ("REINVEST", "Reinvest"),
    ]

    PROFIT_FREQUENCY_CHOICES = [
        ("WEEKLY", "Weekly"),
        ("MONTHLY", "Monthly"),
        ("MANUAL", "Manual"),
    ]

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

    is_active_for_new_business = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Only funders explicitly activated here may support new buying-power "
            "approvals. Existing historical funder records are preserved."
        ),
    )

    allocated_clients = models.ManyToManyField(
        Client,
        through="FunderAllocation",
        related_name="funders",
        blank=True,
    )

    profit_mode = models.CharField(
        max_length=12,
        choices=PROFIT_MODE_CHOICES,
        default="PAYOUT",
        help_text="Determines whether profit is paid out or added back into the funder balance.",
    )

    profit_frequency = models.CharField(
        max_length=12,
        choices=PROFIT_FREQUENCY_CHOICES,
        default="WEEKLY",
        help_text="How often this funder expects profit processing.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active_for_new_business"],
                condition=models.Q(is_active_for_new_business=True),
                name="uniq_active_new_business_funder",
            )
        ]

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
        amount = (
            self.allocations.using(db)
            .filter(client=client)
            .values_list("amount", flat=True)
            .first()
        )
        return r2(amount or Decimal("0.00"))

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
        return f"{self.user} - {self.funder or 'No Funder'} ({self.role})"

    
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

        # An allocation cannot be reduced below money already outstanding.
        existing_account = (
            CreditAccount.objects.using(db)
            .filter(client=self.client)
            .first()
        )
        if (
            existing_account
            and r2(self.amount) < r2(existing_account.credit_used)
        ):
            raise ValidationError(
                "Allocation cannot be lower than the client's outstanding "
                "buying-power usage."
            )

    # --------------------------------------------------
    # LINK ACCOUNT TO FUNDER AND SYNCHRONISE BUYING POWER
    # --------------------------------------------------
    def apply_to_credit_account(self):
        """
        Link the account to its funder and synchronise its limit to the
        reserved allocation. This does not activate a pending account or
        change its contribution percentage or settlement term.
        """
        db = self._state.db or "default"
        ca, _ = CreditAccount.objects.using(db).get_or_create(
            client=self.client,
            defaults={"status": CreditAccount.STATUS_PENDING},
        )

        if ca.funder_id != self.funder_id:
            ca.funder = self.funder
            ca.save(using=db, update_fields=["funder", "updated_at"])

        allocation_amount = r2(self.amount)
        current_limit = r2(ca.credit_limit)

        # Idempotent: do not create duplicate audit/ledger entries if the
        # allocation and approved account limit already agree.
        if current_limit != allocation_amount:
            ca.set_limit(
                new_limit=allocation_amount,
                note=(
                    f"Buying-power limit synchronised from FunderAllocation "
                    f"#{self.pk}."
                ),
            )

    # SAVE (ENTRY POINT)
    # --------------------------------------------------
    @db_transaction.atomic
    def save(self, *args, **kwargs):
        db = kwargs.pop("using", None) or self._state.db or "default"
        self.full_clean()
        super().save(*args, using=db, **kwargs)
        self._state.db = db
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

    profit_links = models.ManyToManyField(
        "credit.FunderProfit",
        blank=True,
        related_name="movements",
        help_text="Optional profit entries linked to this movement.",
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

    @db_transaction.atomic
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

    @db_transaction.atomic
    def delete(self, *args, **kwargs):
        self.funder.apply_delta(-self.signed_amount())
        super().delete(*args, **kwargs)


# ============================================================
# CREDIT ACCOUNT (per client)
# ============================================================


class CreditAccount(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_OVERDUE = "OVERDUE"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending Approval"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_OVERDUE, "Overdue"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_CLOSED, "Closed"),
    ]

    TERM_CHOICES = [
        ("0D", "0 Day (Cash)"),
        ("1D", "1 Day Credit"),
        ("3D", "3 Day Credit"),
        ("7D", "7 Day Credit"),
    ]

    # Customer contribution percentages available for buying-power terms.
    # The remaining percentage of each invoice is the TradeAssist-funded portion.
    DEPOSIT_CHOICES = [
        (Decimal("100.00"), "100%"),
        (Decimal("85.00"), "85%"),
        (Decimal("80.00"), "80%"),
        (Decimal("75.00"), "75%"),
        (Decimal("70.00"), "70%"),
        (Decimal("65.00"), "65%"),
        (Decimal("60.00"), "60%"),
        (Decimal("55.00"), "55%"),
        (Decimal("50.00"), "50%"),
        (Decimal("45.00"), "45%"),
        (Decimal("40.00"), "40%"),
        (Decimal("35.00"), "35%"),
        (Decimal("30.00"), "30%"),
        (Decimal("25.00"), "25%"),
        (Decimal("20.00"), "20%"),
        (Decimal("15.00"), "15%"),
        (Decimal("10.00"), "10%"),
        (Decimal("0.00"), "0%"),
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

    # Legacy account-level date retained for compatibility. New settlement
    # deadlines must be stored per invoice/allocation, not here.
    next_due_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
        help_text=(
            "ACTIVE is retained as the model default for existing workflows. "
            "Newly opened accounts should explicitly start as PENDING."
        ),
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    last_assessed_at = models.DateTimeField(null=True, blank=True)
    status_reason = models.TextField(blank=True)

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

    @property
    def can_allocate(self) -> bool:
        return self.status == self.STATUS_ACTIVE and self.credit_available > 0

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
    @db_transaction.atomic
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
# ============================================================
# CREDIT ASSESSMENT (HISTORICAL CUSTOMER RISK SNAPSHOT)
# ============================================================

class CreditAssessment(models.Model):
    """Dated snapshot of a client's suitability for buying power."""

    STATUS_CHOICES = [
        ("DRAFT", "Draft"), ("SUBMITTED", "Submitted"),
        ("ASSESSED", "Assessed"), ("APPROVED", "Approved"),
        ("DECLINED", "Declined"), ("WITHDRAWN", "Withdrawn"),
    ]
    RISK_CHOICES = [
        ("LOW", "Low"), ("MEDIUM", "Medium"),
        ("HIGH", "High"), ("UNRATED", "Not Rated"),
    ]

    credit_account = models.ForeignKey(
        "credit.CreditAccount", on_delete=models.PROTECT,
        related_name="assessments",
    )
    assessment_date = models.DateField(default=now)
    trading_period_start = models.DateField(null=True, blank=True)
    trading_period_end = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default="DRAFT", db_index=True)

    business_registration_number = models.CharField(max_length=80, blank=True)
    business_registered = models.BooleanField(default=False)
    active_business_bank_account = models.BooleanField(default=False)
    banking_verified = models.BooleanField(default=False)
    documents_verified = models.BooleanField(default=False)
    compliance_notes = models.TextField(blank=True)

    estimated_daily_spend = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    estimated_weekly_spend = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    estimated_monthly_spend = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    estimated_purchases_per_week = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # Trading-system metrics frozen at the time of assessment.
    system_invoice_count = models.PositiveIntegerField(default=0)
    system_invoice_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    system_average_invoice = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    system_average_weekly_spend = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    on_time_payment_pct = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Verified payment performance percentage, from 0 to 100.",
    )
    overdue_invoice_count = models.PositiveIntegerField(default=0)
    average_days_to_settle = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    trading_data_notes = models.TextField(blank=True)

    risk_rating = models.CharField(max_length=10, choices=RISK_CHOICES,
                                   default="UNRATED")
    recommended_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    recommended_customer_contribution_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        choices=CreditAccount.DEPOSIT_CHOICES,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=(
            "Recommended percentage of each invoice payable upfront by the "
            "customer. The remaining percentage is the TradeAssist-funded portion."
        ),
    )
    recommended_settlement_term = models.CharField(
        max_length=3, choices=CreditAccount.TERM_CHOICES, blank=True
    )
    recommendation_notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_assessments_created",
    )
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_assessments_reviewed",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    assessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assessment_date", "-created_at"]
        indexes = [
            models.Index(fields=["credit_account", "assessment_date"]),
            models.Index(fields=["status", "assessment_date"]),
        ]

    def __str__(self):
        return (f"Assessment #{self.pk} · {self.credit_account.client} · "
                f"{self.assessment_date} · {self.status}")

    def clean(self):
        super().clean()
        if (self.trading_period_start and self.trading_period_end
                and self.trading_period_end < self.trading_period_start):
            raise ValidationError({
                "trading_period_end": "Trading period end cannot be before start."
            })
        if (self.recommended_customer_contribution_pct is not None
                and self.recommended_customer_contribution_pct > 100):
            raise ValidationError({
                "recommended_customer_contribution_pct":
                    "Customer contribution cannot exceed 100%."
            })
        if self.on_time_payment_pct is not None and self.on_time_payment_pct > 100:
            raise ValidationError({
                "on_time_payment_pct": "Payment percentage cannot exceed 100%."
            })


# ============================================================
# CREDIT APPROVAL (FORMAL AUTHORISATION OF COMMERCIAL TERMS)
# ============================================================

class CreditApproval(models.Model):
    """Formal approval; an assessment or recommendation never activates buying power."""

    STATUS_CHOICES = [
        ("PENDING", "Pending Approval"), ("APPROVED", "Approved"),
        ("DECLINED", "Declined"), ("REVOKED", "Revoked"),
    ]

    credit_account = models.ForeignKey(
        "credit.CreditAccount", on_delete=models.PROTECT,
        related_name="approvals",
    )
    assessment = models.ForeignKey(
        "credit.CreditAssessment", null=True, blank=True,
        on_delete=models.PROTECT, related_name="approval_records",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default="PENDING", db_index=True)
    requested_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    approved_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    customer_contribution_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("70.00"),
        choices=CreditAccount.DEPOSIT_CHOICES,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=(
            "Percentage of each invoice payable upfront by the customer. "
            "The remaining percentage is the TradeAssist-funded portion."
        ),
    )
    settlement_term = models.CharField(max_length=3,
        choices=CreditAccount.TERM_CHOICES, default="3D")
    decision_notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_approvals_requested",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_approvals_authorised",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["credit_account", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"Approval #{self.pk} · {self.credit_account.client} · {self.status}"

    def clean(self):
        super().clean()
        if self.customer_contribution_pct > 100:
            raise ValidationError({
                "customer_contribution_pct":
                    "Customer contribution cannot exceed 100%."
            })
        if (self.assessment_id
                and self.assessment.credit_account_id != self.credit_account_id):
            raise ValidationError({
                "assessment": "Assessment must belong to this credit account."
            })
        if (self.effective_from and self.effective_until
                and self.effective_until < self.effective_from):
            raise ValidationError({
                "effective_until": "End date cannot be before start date."
            })

    @db_transaction.atomic
    def approve(self, *, authorised_by, using=None):
        """Approve terms after verifying funder allocation; do not create allocation."""
        if not authorised_by:
            raise ValidationError("An authorised approver is required.")
        db = using or self._state.db or "default"
        account = (CreditAccount.objects.using(db).select_for_update()
                   .get(pk=self.credit_account_id))

        if self.status != "PENDING":
            raise ValidationError("Only pending approvals can be approved.")
        if self.approved_limit is None or self.approved_limit <= 0:
            raise ValidationError("Enter an approved buying-power amount.")
        if not account.funder_id:
            raise ValidationError("Assign a funder before approval.")
        if not account.funder.is_active_for_new_business:
            raise ValidationError("This funder is not active for new business.")
        if account.funder.weekly_rate_pct != Decimal("0.00"):
            raise ValidationError(
                "The active buying-power funder must have a 0% weekly rate. "
                "Legacy profit settings must not apply to new approvals."
            )

        allocation = FunderAllocation.objects.using(db).filter(
            funder_id=account.funder_id, client_id=account.client_id
        ).first()
        if not allocation or r2(allocation.amount) < r2(self.approved_limit):
            raise ValidationError(
                "Approved limit exceeds the capital allocated to this client."
            )
        if r2(self.approved_limit) < r2(account.credit_used):
            raise ValidationError(
                "Approved limit cannot be lower than current outstanding usage."
            )

        self.status = "APPROVED"
        self.approved_by = authorised_by
        self.decided_at = now()
        self.effective_from = self.effective_from or now()
        self.full_clean()
        self.save(using=db)

        account.payment_term = self.settlement_term
        account.credit_deposit_pct = self.customer_contribution_pct
        account.status = CreditAccount.STATUS_ACTIVE
        account.activated_at = account.activated_at or now()
        account.status_reason = f"Activated through CreditApproval #{self.pk}."
        account.save(update_fields=[
            "payment_term", "credit_deposit_pct", "status",
            "activated_at", "status_reason", "updated_at",
        ])
        if r2(account.credit_limit) != r2(self.approved_limit):
            account.set_limit(
                new_limit=self.approved_limit,
                authorised_by=authorised_by,
                note=f"Approved under CreditApproval #{self.pk}",
            )
        return account


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
            .filter(client=ca.client, funder=ca.funder)
            .aggregate(
                s=Coalesce(Sum("amount"), Decimal("0.00"))
            )["s"]
        )

        if r2(self.new_limit) > r2(allocated):
            raise ValidationError(
                f"Proposed limit R{self.new_limit:.2f} exceeds allocated capital "
                f"R{allocated:.2f}."
            )

    @db_transaction.atomic
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

    # Immutable snapshot of the account term at the time buying power was used.
    due_date = models.DateField(null=True, blank=True, db_index=True)

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
    @db_transaction.atomic
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
        amount = r2(amount)
        if amount <= Decimal("0.00"):
            raise ValidationError("Usage amount must be greater than zero.")

        ca, _ = CreditAccount.objects.using(db).get_or_create(client=client)
        ca = CreditAccount.objects.using(db).select_for_update().get(pk=ca.pk)

        if ca.status != CreditAccount.STATUS_ACTIVE:
            raise ValidationError(
                f"Buying-power account is {ca.get_status_display().lower()}."
            )

        available = ca.credit_available
        if amount > available:
            raise ValidationError(
                f"Insufficient buying power. Available: R{available:.2f}; "
                f"requested: R{amount:.2f}."
            )

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
    @db_transaction.atomic
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
        amount = r2(amount)
        if amount <= Decimal("0.00"):
            raise ValidationError("Repayment amount must be greater than zero.")

        ca, _ = CreditAccount.objects.using(db).get_or_create(client=client)

        return cls.objects.using(db).create(
            credit_account=ca,
            kind=cls.REPAYMENT,
            amount=amount,
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

            # Snapshot the agreed settlement deadline when usage is posted.
            # Existing terms are never recalculated if the account is edited later.
            if self.kind == self.USAGE and self.due_date is None:
                account = self.credit_account
                term = account.payment_term or "0D"
                self.due_date = settlement_due_date(
                    self.posted_at.date(), term
                )

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

        # Every usage entry creates one invoice-level settlement obligation.
        # get_or_create makes this safe if the save path is retried.
        if is_create and self.kind == self.USAGE:
            CreditSettlement.objects.using(self._state.db or "default").get_or_create(
                usage_entry=self,
                defaults={
                    "credit_account": self.credit_account,
                    "invoice": self.invoice,
                    "original_amount": self.amount,
                    "due_date": self.due_date,
                    "grace_date": self.due_date + timedelta(days=1),
                    "status": CreditSettlement.STATUS_OUTSTANDING,
                },
            )

        # ---------------------------------------------------
        # Update weekly funder summary
        # ---------------------------------------------------
        if is_create and self.kind == self.USAGE:
            update_funder_week_summary(self)



# ============================================================
# CREDIT SETTLEMENT (ONE OBLIGATION PER USAGE / INVOICE)
# ============================================================

class CreditSettlement(models.Model):
    STATUS_OUTSTANDING = "OUTSTANDING"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_OVERDUE = "OVERDUE"
    STATUS_SETTLED = "SETTLED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_OUTSTANDING, "Outstanding"),
        (STATUS_PARTIAL, "Partially Settled"),
        (STATUS_OVERDUE, "Overdue"),
        (STATUS_SETTLED, "Settled"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    credit_account = models.ForeignKey(
        CreditAccount,
        on_delete=models.PROTECT,
        related_name="settlements",
    )
    usage_entry = models.OneToOneField(
        CreditEntry,
        on_delete=models.PROTECT,
        related_name="settlement",
    )
    invoice = models.ForeignKey(
        "invoices.Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_settlements",
    )
    original_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    repaid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    outstanding_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    due_date = models.DateField(db_index=True)
    grace_date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_OUTSTANDING,
        db_index=True,
    )
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "created_at", "id"]
        indexes = [
            models.Index(fields=["credit_account", "status", "due_date"]),
            models.Index(fields=["status", "grace_date"]),
            models.Index(fields=["invoice"]),
        ]

    def __str__(self):
        return (
            f"Settlement #{self.pk} · {self.credit_account.client} · "
            f"R{self.outstanding_amount:.2f} · {self.status}"
        )

    @property
    def is_fully_settled(self):
        return self.outstanding_amount <= Decimal("0.00")

    def clean(self):
        super().clean()
        if self.grace_date < self.due_date:
            raise ValidationError("Grace date cannot be before the due date.")
        if self.repaid_amount > self.original_amount:
            raise ValidationError("Repaid amount cannot exceed the original amount.")

    def refresh_amounts(self, *, save=True):
        self.original_amount = r2(self.original_amount)
        self.repaid_amount = min(r2(self.repaid_amount), self.original_amount)
        self.outstanding_amount = r2(self.original_amount - self.repaid_amount)

        if self.outstanding_amount <= Decimal("0.00"):
            self.outstanding_amount = Decimal("0.00")
            self.status = self.STATUS_SETTLED
            self.settled_at = self.settled_at or now()
        elif self.repaid_amount > Decimal("0.00"):
            self.status = self.STATUS_PARTIAL
            self.settled_at = None
        elif self.status not in {self.STATUS_OVERDUE, self.STATUS_CANCELLED}:
            self.status = self.STATUS_OUTSTANDING

        if save:
            self.save(update_fields=[
                "original_amount", "repaid_amount", "outstanding_amount",
                "status", "settled_at", "updated_at",
            ])
        return self.outstanding_amount

    @db_transaction.atomic
    def allocate_repayment(self, amount: Decimal, *, using=None):
        """Allocate a verified repayment to this invoice settlement."""
        db = using or self._state.db or "default"
        settlement = (
            CreditSettlement.objects.using(db)
            .select_for_update()
            .get(pk=self.pk)
        )
        amount = r2(amount)
        if amount <= Decimal("0.00"):
            raise ValidationError("Repayment must be greater than zero.")
        if settlement.status == self.STATUS_CANCELLED:
            raise ValidationError("A cancelled settlement cannot receive repayment.")
        applied = min(amount, settlement.outstanding_amount)
        settlement.repaid_amount = r2(settlement.repaid_amount + applied)
        settlement.refresh_amounts(save=True)
        self.refresh_from_db(using=db)
        return applied

    @classmethod
    @db_transaction.atomic
    def allocate_account_repayment(cls, *, credit_account, amount, invoice=None, using=None):
        """Allocate a verified account repayment to matching or oldest obligations."""
        db = using or credit_account._state.db or "default"
        remaining = r2(amount)
        if remaining <= Decimal("0.00"):
            raise ValidationError("Repayment must be greater than zero.")

        qs = cls.objects.using(db).select_for_update().filter(
            credit_account=credit_account,
            status__in=[
                cls.STATUS_OUTSTANDING,
                cls.STATUS_PARTIAL,
                cls.STATUS_OVERDUE,
            ],
            outstanding_amount__gt=0,
        )
        if invoice is not None:
            qs = qs.filter(invoice=invoice)
        settlements = list(qs.order_by("due_date", "created_at", "id"))
        if invoice is not None and not settlements:
            raise ValidationError("No outstanding Trade Assist settlement exists for this invoice.")

        applied_total = Decimal("0.00")
        for settlement in settlements:
            if remaining <= 0:
                break
            applied = min(remaining, settlement.outstanding_amount)
            settlement.repaid_amount = r2(settlement.repaid_amount + applied)
            settlement.refresh_amounts(save=True)
            remaining = r2(remaining - applied)
            applied_total = r2(applied_total + applied)

        if applied_total <= 0:
            raise ValidationError("There are no outstanding Trade Assist settlements to allocate this payment to.")
        return applied_total

    @classmethod
    def assess_overdue(cls, *, today=None, using="default"):
        """Update settlement and account statuses; call from a daily scheduled task."""
        today = today or now().date()
        db = using or "default"
        assessed = 0
        overdue_accounts = set()
        suspended_accounts = set()

        settlements = cls.objects.using(db).select_related("credit_account").filter(
            outstanding_amount__gt=0,
            status__in=[cls.STATUS_OUTSTANDING, cls.STATUS_PARTIAL, cls.STATUS_OVERDUE],
        )

        for settlement in settlements.iterator():
            if today > settlement.grace_date:
                new_status = cls.STATUS_OVERDUE
                suspended_accounts.add(settlement.credit_account_id)
            elif today > settlement.due_date:
                new_status = cls.STATUS_OVERDUE
                overdue_accounts.add(settlement.credit_account_id)
            else:
                new_status = (
                    cls.STATUS_PARTIAL
                    if settlement.repaid_amount > 0
                    else cls.STATUS_OUTSTANDING
                )

            if settlement.status != new_status:
                cls.objects.using(db).filter(pk=settlement.pk).update(
                    status=new_status, updated_at=now()
                )
                assessed += 1

        # Do not automatically reactivate overdue/suspended accounts after payment.
        for account_id in overdue_accounts:
            CreditAccount.objects.using(db).filter(
                pk=account_id, status=CreditAccount.STATUS_ACTIVE
            ).update(
                status=CreditAccount.STATUS_OVERDUE,
                status_reason="At least one Trade Assist invoice settlement is overdue.",
                updated_at=now(),
            )

        for account_id in suspended_accounts:
            CreditAccount.objects.using(db).filter(
                pk=account_id,
                status__in=[CreditAccount.STATUS_ACTIVE, CreditAccount.STATUS_OVERDUE],
            ).update(
                status=CreditAccount.STATUS_SUSPENDED,
                status_reason="An outstanding Trade Assist settlement passed its grace date.",
                updated_at=now(),
            )

        return {
            "settlements_updated": assessed,
            "accounts_marked_overdue": len(overdue_accounts),
            "accounts_suspended": len(suspended_accounts),
        }


from django.db.models.signals import post_delete
from django.dispatch import receiver


@receiver(post_save, sender=CreditEntry)
def allocate_repayment_to_settlements(sender, instance, created, **kwargs):
    if not created or instance.kind != CreditEntry.REPAYMENT:
        return
    try:
        CreditSettlement.allocate_account_repayment(
            credit_account=instance.credit_account,
            amount=instance.amount,
            invoice=instance.invoice,
            using=instance._state.db or "default",
        )
    except ValidationError:
        logger.exception(
            "Could not allocate repayment CreditEntry #%s to a Trade Assist settlement.",
            instance.pk,
        )


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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        db = self._state.db or "default"
        period_end = self.week_start + timedelta(days=6)

        profit = (
            FunderProfit.objects.using(db)
            .filter(week_summary=self)
            .first()
        )

        if not profit:
            FunderProfit.objects.using(db).create(
                funder=self.funder,
                week_summary=self,
                source_type="WEEKLY",
                period_start=self.week_start,
                period_end=period_end,
                amount=self.weekly_return,
                status="PENDING",
                reference=f"WEEK-{self.week_start}",
                note=f"Auto-created from weekly summary for {self.week_start}",
            )
            return

        if profit.status == "PENDING":
            profit.funder = self.funder
            profit.source_type = "WEEKLY"
            profit.period_start = self.week_start
            profit.period_end = period_end
            profit.amount = self.weekly_return
            profit.save(
                using=db,
                update_fields=[
                    "funder",
                    "source_type",
                    "period_start",
                    "period_end",
                    "amount",
                    "updated_at",
                ],
            )


class FunderProfit(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PAID_OUT", "Paid Out"),
        ("REINVESTED", "Reinvested"),
        ("CANCELLED", "Cancelled"),
    ]

    SOURCE_CHOICES = [
        ("WEEKLY", "Weekly Summary"),
        ("MONTHLY", "Monthly Summary"),
        ("MANUAL", "Manual"),
    ]

    funder = models.ForeignKey(
        Funder,
        on_delete=models.CASCADE,
        related_name="profits",
    )

    week_summary = models.ForeignKey(
        "credit.FunderWeekSummary",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profit_entries",
        help_text="Optional link to the weekly summary that generated this profit.",
    )

    source_type = models.CharField(
        max_length=12,
        choices=SOURCE_CHOICES,
        default="WEEKLY",
    )

    period_start = models.DateField()
    period_end = models.DateField()

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Profit amount for the selected period.",
    )

    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default="PENDING",
    )

    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this profit was paid out or reinvested.",
    )

    reference = models.CharField(
        max_length=120,
        blank=True,
    )

    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "-created_at"]
        indexes = [
            models.Index(fields=["funder", "status"]),
            models.Index(fields=["funder", "period_start", "period_end"]),
        ]

    def __str__(self):
        return (
            f"{self.funder.name} · {self.period_start} to {self.period_end} · "
            f"R{self.amount:.2f} · {self.status}"
        )

    def clean(self):
        super().clean()

        if self.period_end < self.period_start:
            raise ValidationError({
                "period_end": "Period end cannot be before period start."
            })

        if self.source_type == "WEEKLY" and not self.week_summary:
            raise ValidationError({
                "week_summary": "Weekly profit entries must be linked to a weekly summary."
            })

        if self.week_summary and self.week_summary.funder_id != self.funder_id:
            raise ValidationError({
                "week_summary": "Weekly summary funder must match the profit funder."
            })

    @classmethod
    @db_transaction.atomic
    def process_monthly_reinvestment(cls, *, using="default", run_date=None):
        """
        Process MONTHLY + REINVEST funders for the previous full calendar month.

        Steps:
        1. Find funders set to REINVEST + MONTHLY.
        2. Find their weekly profit rows for the previous month that are still
           PENDING and not yet linked to any movement.
        3. Sum those profits.
        4. Create one TOPUP movement for the total.
        5. Link those profits to the movement.
        6. Mark those profits as REINVESTED.
        """

        db = using or "default"
        today = run_date or now().date()

        # --------------------------------------------------
        # Previous full calendar month
        # --------------------------------------------------
        first_day_this_month = today.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        month_start = last_day_prev_month.replace(day=1)
        month_end = last_day_prev_month

        processed_funders = 0
        processed_profits = 0
        processed_total = Decimal("0.00")

        funders = Funder.objects.using(db).filter(
            profit_mode="REINVEST",
            profit_frequency="MONTHLY",
        )

        for funder in funders:
            profits_qs = (
                cls.objects.using(db)
                .filter(
                    funder=funder,
                    source_type="WEEKLY",
                    status="PENDING",
                    period_start__gte=month_start,
                    period_end__lte=month_end,
                    movements__isnull=True,
                )
                .distinct()
                .order_by("period_start", "id")
            )

            if not profits_qs.exists():
                continue

            total_profit = profits_qs.aggregate(
                total=Coalesce(Sum("amount"), Decimal("0.00"))
            )["total"] or Decimal("0.00")

            total_profit = r2(total_profit)

            if total_profit <= Decimal("0.00"):
                continue

            reference = f"PROFIT REINVEST {month_start.strftime('%Y-%m')}"
            note = (
                f"Monthly reinvestment of weekly profits for "
                f"{month_start.strftime('%B %Y')}"
            )

            movement = FunderMovement.objects.using(db).create(
                funder=funder,
                kind=FunderMovement.TOPUP,
                amount=total_profit,
                reference=reference,
                note=note,
            )

            profit_ids = list(profits_qs.values_list("id", flat=True))
            movement.profit_links.set(profit_ids)

            processed_at = now()

            profits_qs.update(
                status="REINVESTED",
                processed_at=processed_at,
                updated_at=processed_at,
            )

            processed_funders += 1
            processed_profits += len(profit_ids)
            processed_total = r2(processed_total + total_profit)

        return {
            "month_start": month_start,
            "month_end": month_end,
            "funders_processed": processed_funders,
            "profits_processed": processed_profits,
            "total_reinvested": processed_total,
        }


    
      