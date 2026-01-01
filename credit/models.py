# credit/models.py
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Tuple, Dict

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.utils.timezone import now
from datetime import date, timedelta

from clients.models import Client
import logging

logger = logging.getLogger(__name__)


# ---------- helpers ----------
def r2(x: Decimal | None) -> Decimal:
    """Round to 2 decimals, treating None as 0.00."""
    if x is None:
        x = Decimal("0.00")
    return Decimal(x).quantize(Decimal("0.01"))


def _r2(x: Decimal | None) -> Decimal:
    return Decimal("0.00") if x is None else Decimal(x).quantize(Decimal("0.01"))


def monday_of(d: date) -> date:
    """Return the Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


# ====================================================================
# Funder: master + live balance
# ====================================================================
class Funder(models.Model):
    name = models.CharField(max_length=120, unique=True)
    weekly_rate_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
        help_text="Weekly percentage return charged on capped utilization."
    )
    balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        help_text="Live balance you hold/owe after top-ups/payouts."
    )

    allocated_clients = models.ManyToManyField(
        Client,
        through="FunderAllocation",
        related_name="funders",
        blank=True,
        help_text="Clients this funder has capital allocated to."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} (bal R{self.balance:.2f}, {self.weekly_rate_pct}%/wk)"

    # Balance adjustments
    def apply_delta(self, delta: Decimal) -> None:
        if not delta:
            return
        self.balance = _r2((self.balance or Decimal("0.00")) + _r2(delta))
        self.save(update_fields=["balance", "updated_at"])

    # ----- allocation helpers -----
    def total_allocated(self) -> Decimal:
        return _r2(
            self.allocations.aggregate(
                s=Coalesce(Sum("amount"), Decimal("0.00"))
            )["s"] or Decimal("0.00")
        )

    @property
    def allocatable_balance(self) -> Decimal:
        return _r2((self.balance or Decimal("0.00")) - self.total_allocated())

    def allocation_for(self, client: Client) -> Decimal:
        amt = (
            self.allocations.filter(client=client)
            .values_list("amount", flat=True)
            .first()
        )
        return _r2(amt or Decimal("0.00"))

    # ---- MEMBERSHIP CONVENIENCES ----
    def users(self):
        """Active users linked to this funder."""
        User = get_user_model()
        return User.objects.filter(
            funder_memberships__funder=self,
            funder_memberships__is_active=True
        ).distinct()

    def has_user(self, user) -> bool:
        return FunderMember.objects.filter(
            funder=self, user=user, is_active=True
        ).exists()

    @transaction.atomic
    def set_allocation(self, *, client: Client, amount: Decimal) -> "FunderAllocation":
        alloc, created = FunderAllocation.objects.get_or_create(
            funder=self, client=client,
            defaults={"amount": _r2(amount)}
        )
        if not created:
            alloc.amount = _r2(amount)
        alloc.full_clean()
        alloc.save()
        return alloc

    @transaction.atomic
    def rebuild_week(self, week_start: date) -> "FunderWeekSummary":
        from credit.models import CreditEntry, CreditAccount  # avoid circulars

        ws = monday_of(week_start)
        we = ws + timedelta(days=7)

        usage_qs = (
            CreditEntry.objects
            .filter(
                kind=CreditEntry.USAGE,
                posted_at__gte=ws, posted_at__lt=we,
                credit_account__funder=self,
            )
            .select_related("credit_account__client")
        )

        per_client: Dict[int, Decimal] = {}
        for ce in usage_qs:
            cid = ce.credit_account.client_id
            per_client[cid] = _r2(per_client.get(cid, Decimal("0.00")) + _r2(ce.amount))

        rows = []
        total_visible = Decimal("0.00")
        for client_id, usage_sum in per_client.items():
            ca = CreditAccount.objects.select_related("client").get(client_id=client_id)
            cap = _r2(ca.credit_limit or Decimal("0.00"))
            visible = _r2(min(_r2(usage_sum), cap))

            fcw, _ = FunderClientWeek.objects.get_or_create(
                funder=self, client_id=client_id, week_start=ws,
                defaults={
                    "credit_limit_at_start": cap,
                    "usage_sum": _r2(usage_sum),
                    "visible_utilization": visible,
                },
            )
            changed = False
            if fcw.credit_limit_at_start != cap:
                fcw.credit_limit_at_start, changed = cap, True
            if fcw.usage_sum != _r2(usage_sum):
                fcw.usage_sum, changed = _r2(usage_sum), True
            if fcw.visible_utilization != visible:
                fcw.visible_utilization, changed = visible, True
            if changed:
                fcw.save(update_fields=[
                    "credit_limit_at_start", "usage_sum", "visible_utilization", "updated_at"
                ])
            rows.append(fcw)
            total_visible += visible

        (FunderClientWeek.objects
         .filter(funder=self, week_start=ws)
         .exclude(id__in=[r.id for r in rows])
         .delete())

        fws, _ = FunderWeekSummary.objects.get_or_create(
            funder=self, week_start=ws,
            defaults={
                "visible_utilization_total": _r2(total_visible),
                "weekly_rate_pct_snapshot": _r2(self.weekly_rate_pct),
                "weekly_return": _r2(total_visible * (self.weekly_rate_pct / Decimal("100"))),
            },
        )
        updated = False
        if fws.visible_utilization_total != _r2(total_visible):
            fws.visible_utilization_total, updated = _r2(total_visible), True
        if fws.weekly_rate_pct_snapshot != _r2(self.weekly_rate_pct):
            fws.weekly_rate_pct_snapshot, updated = _r2(self.weekly_rate_pct), True
        new_ret = _r2(total_visible * (self.weekly_rate_pct / Decimal("100")))
        if fws.weekly_return != new_ret:
            fws.weekly_return, updated = new_ret, True
        if updated:
            fws.save(update_fields=[
                "visible_utilization_total", "weekly_rate_pct_snapshot", "weekly_return", "updated_at"
            ])
        return fws

ROLE_CHOICES = (
    ("OWNER", "Owner"),
    ("MANAGER", "Manager"),
    ("VIEWER", "Viewer"),
)

class ActiveMembershipManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

class FunderMember(models.Model):
    """Links Django users to a Funder with a role + enable switch."""
    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="funder_memberships")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default="VIEWER")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    active = ActiveMembershipManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["funder", "user"], name="uniq_funder_user"),
        ]
        indexes = [
            models.Index(fields=["funder"]),
            models.Index(fields=["user"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.user} → {self.funder} ({self.role})"

# ====================================================================
# Allocation of a funder's capital to clients
# ====================================================================
class FunderAllocation(models.Model):
    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="allocations")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="funder_allocations")
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))]
    )
    # optional: add status (reserved/committed) later

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("funder", "client")]
        ordering = ["funder_id", "client_id"]

    def __str__(self):
        return f"{self.funder.name} → {self.client.name}: R{self.amount:.2f}"

    def clean(self):
        """
        Prevent total allocations from exceeding funder.balance.
        """
        others_total = (
            FunderAllocation.objects
            .filter(funder=self.funder)
            .exclude(pk=self.pk)
            .aggregate(s=Coalesce(Sum("amount"), Decimal("0.00")))["s"]
            or Decimal("0.00")
        )
        new_total = _r2(others_total + _r2(self.amount or Decimal("0.00")))
        if new_total > _r2(self.funder.balance):
            raise ValidationError("Allocation exceeds available funder capital.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


# ====================================================================
# Movements: top-ups / payouts (auto-adjust Funder.balance)
# ====================================================================
class FunderMovement(models.Model):
    TOPUP = "topup"
    PAYOUT = "payout"
    ADJUST = "adjustment"
    KIND_CHOICES = [
        (TOPUP, "Top-up (increase balance)"),
        (PAYOUT, "Payout (decrease balance)"),
        (ADJUST, "Manual Adjustment"),
    ]

    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["funder", "created_at"])]

    def __str__(self) -> str:
        sign = "+" if self.kind in {self.TOPUP, self.ADJUST} else "-"
        return f"{self.funder.name} · {self.kind} · {sign}R{self.amount:.2f}"

    def _signed(self) -> Decimal:
        amt = _r2(self.amount)
        if self.kind == self.TOPUP:
            return amt
        if self.kind == self.PAYOUT:
            return -amt
        # ADJUST: positive raises balance, negative lowers — pass through
        return amt

    @transaction.atomic
    def save(self, *args, **kwargs):
        creating = self.pk is None
        prev = None
        if not creating:
            prev = FunderMovement.objects.only("kind", "amount").get(pk=self.pk)
        super().save(*args, **kwargs)

        if creating:
            self.funder.apply_delta(self._signed())
        else:
            prev_signed = FunderMovement.signed_of(prev) if prev else Decimal("0.00")
            new_signed = self._signed()
            delta = new_signed - prev_signed
            if delta:
                self.funder.apply_delta(delta)

    @staticmethod
    def signed_of(row: "FunderMovement") -> Decimal:
        amt = _r2(row.amount)
        if row.kind == FunderMovement.TOPUP:
            return amt
        if row.kind == FunderMovement.PAYOUT:
            return -amt
        return amt

    @transaction.atomic
    def delete(self, *args, **kwargs):
        self.funder.apply_delta(-self._signed())
        super().delete(*args, **kwargs)


# ====================================================================
# Weekly client breakdown (capped per client at 100% = credit_limit)
# ====================================================================
class FunderClientWeek(models.Model):
    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="client_weeks")
    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="funder_weeks")
    week_start = models.DateField(help_text="ISO week Monday")
    credit_limit_at_start = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    usage_sum = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    visible_utilization = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Usage capped at 100% of credit_limit for this client in the week."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("funder", "client", "week_start")]
        ordering = ["-week_start", "funder_id", "client_id"]
        indexes = [
            models.Index(fields=["funder", "week_start"]),
            models.Index(fields=["client", "week_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.week_start} · {self.funder.name} · {self.client} · vis R{self.visible_utilization:.2f}"


# ====================================================================
# Weekly summary per funder (roll-up of client caps)
# ====================================================================
class FunderWeekSummary(models.Model):
    funder = models.ForeignKey(Funder, on_delete=models.CASCADE, related_name="week_summaries")
    week_start = models.DateField(help_text="ISO week Monday", db_index=True)
    visible_utilization_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    weekly_rate_pct_snapshot = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    weekly_return = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"),
        help_text="Amount owed to the funder for this week (not including your margins)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("funder", "week_start")]
        ordering = ["-week_start", "funder_id"]

    def __str__(self) -> str:
        return f"{self.week_start} · {self.funder.name} · return R{self.weekly_return:.2f}"

    def refresh_from_client_weeks(self) -> None:
        total = (
            FunderClientWeek.objects
            .filter(funder=self.funder, week_start=self.week_start)
            .aggregate(s=Sum("visible_utilization"))["s"] or Decimal("0.00")
        )
        self.visible_utilization_total = _r2(total)
        self.weekly_return = _r2(total * (self.weekly_rate_pct_snapshot / Decimal("100")))
        self.save(update_fields=["visible_utilization_total", "weekly_return", "updated_at"])


# ====================================================================
# CreditAccount: running totals + link to funder
# ====================================================================
class CreditAccount(models.Model):
    TERM_CHOICES = [
        ("0D", "0 Day Account"),
        ("3D", "3 Day Account"),
        ("7D", "7 Day Account"),
    ]

    DEPOSIT_CHOICES = [
        (Decimal("0.00"), "0%"),
        (Decimal("30.00"), "30%"),
        (Decimal("50.00"), "50%"),
        (Decimal("100.00"), "100%"),
    ]
    client       = models.OneToOneField(Client, on_delete=models.CASCADE, related_name="credit_account")
    funder       = models.ForeignKey(
        Funder, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_accounts"
    )
    # NEW: 3-day vs 7-day account
    payment_term = models.CharField(
        max_length=3,
        choices=TERM_CHOICES,
        default="0D",
        help_text="How long the client has to settle credit purchases (e.g. 3 or 7 days).",
    )

    # NEW: required credit deposit percentage
    credit_deposit_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=DEPOSIT_CHOICES,
        default=Decimal("100.00"),  # you can change this default if you prefer e.g. 30.00 or 0.00
        help_text="Deposit percentage required when using credit (0%, 30%, 50% or 100%).",
    )
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit_used  = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    # ✅ NEW FIELD
    next_due_date = models.DateField(null=True, blank=True, help_text="Next repayment due date (optional).")
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["client"]),
            models.Index(fields=["funder"]),
        ]

    def __str__(self):
        return f"{self.client} · Limit: R{self.credit_limit} · Used: R{self.credit_used}"

    @property
    def credit_available(self) -> Decimal:
        return r2((self.credit_limit or Decimal("0.00")) - (self.credit_used or Decimal("0.00")))

    @property
    def balance(self) -> Decimal:
        return self.credit_available

    @transaction.atomic
    def set_limit(self, new_limit: Decimal, *, authorised_by=None, note: str = ""):
        """
        Do NOT mutate credit_limit directly; create a CreditLog.
        Allocation cap (per funder+client AND across all funders for that client)
        is enforced in CreditLog.clean()/save().
        """
        prev = r2(self.credit_limit or Decimal("0.00"))
        new  = r2(Decimal(new_limit or 0))
        if new == prev:
            return
        CreditLog.objects.create(
            credit_account=self,
            previous_limit=prev,
            new_limit=new,
            amount_changed=r2(new - prev),
            note=note,
            authorised_by=authorised_by,
        )

    # small helpers
    def last_usage_entry(self) -> Optional["CreditEntry"]:
        return self.entries.filter(kind=CreditEntry.USAGE).order_by("-posted_at", "-id").first()

    def repaid_amount_since(self, *, start=None, invoice_id: Optional[int] = None) -> Decimal:
        qs = self.entries.filter(kind=CreditEntry.REPAYMENT)
        if invoice_id:
            qs = qs.filter(invoice_id=invoice_id)
        elif start:
            qs = qs.filter(posted_at__gte=start)
        return r2(qs.aggregate(s=Coalesce(Sum("amount"), Decimal("0.00")))["s"] or Decimal("0.00"))

    def has_paid_half_of_last_usage(self) -> bool:
        status = (getattr(self.client, "credit_status", "") or "").upper()
        if status != "ACTIVE":
            return True
        last = self.last_usage_entry()
        if not last:
            return True
        repaid = self.entries.filter(kind=CreditEntry.REPAYMENT).filter(
            Q(invoice_id=last.invoice_id) | Q(posted_at__gte=last.posted_at)
        ).aggregate(s=Coalesce(Sum("amount"), Decimal("0.00")))["s"] or Decimal("0.00")
        return Decimal(repaid) >= r2(Decimal(last.amount) * Decimal("0.50"))

    def has_met_strict_50pct_rule(self) -> Tuple[bool, Optional[str]]:
        return CreditEntry.check_50pct_rule(self.client)
    
    def recalculate_credit_used(self):
        """
        credit_used = total USAGE - total REPAYMENT
        """
        totals = self.entries.aggregate(
            usage=Coalesce(
                Sum("amount", filter=models.Q(kind="usage")),
                Decimal("0.00")
            ),
            repayment=Coalesce(
                Sum("amount", filter=models.Q(kind="repayment")),
                Decimal("0.00")
            ),
        )

        self.credit_used = totals["usage"] - totals["repayment"]
        self.save(update_fields=["credit_used"])

    @property
    def credit_available(self):
        return (self.credit_limit or Decimal("0.00")) - (self.credit_used or Decimal("0.00"))


def _sync_allocation_for_current_state(credit_account_id: int) -> None:
    """
    After commit, re-fetch the CreditAccount and ensure funder allocation ~= current credit_limit.
    Safe to call repeatedly; uses best-effort clamping.
    """
    try:
        ca = CreditAccount.objects.select_related("funder", "client").get(pk=credit_account_id)
    except CreditAccount.DoesNotExist:
        return
    if not ca.funder_id:
        return

    _ensure_allocation_or_best_effort(
        funder=ca.funder,
        client=ca.client,
        target_amount=_r2(ca.credit_limit or Decimal("0.00")),
    )

    # Non-fatal weekly refresh
    try:
        ca.funder.rebuild_week(monday_of(date.today()))
    except Exception:
        pass

@property
def outstanding(self) -> Decimal:
    return r2(self.credit_used or Decimal("0.00"))

# ====================================================================
# CreditLog: limit change audit -> emits ledger entries
# ====================================================================
class CreditLog(models.Model):
    credit_account  = models.ForeignKey(CreditAccount, on_delete=models.CASCADE, related_name='logs')
    previous_limit  = models.DecimalField(max_digits=12, decimal_places=2)
    new_limit       = models.DecimalField(max_digits=12, decimal_places=2)
    amount_changed  = models.DecimalField(max_digits=12, decimal_places=2)
    note            = models.TextField(blank=True)
    authorised_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="credit_logs",
        help_text="Who approved or made the credit change."
    )
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["credit_account", "created_at"]),
        ]

    def __str__(self):
        symbol = "+" if self.amount_changed > 0 else ""
        user = self.authorised_by.get_full_name() if self.authorised_by else "System"
        return f"{self.credit_account.client} · {symbol}R{self.amount_changed} by {user} on {self.created_at.date()}"

    def clean(self):
        """
        Enforce funder allocation cap when increasing a client's limit (if the account is tied to a funder).
        """
        delta = r2((self.new_limit or Decimal("0.00")) - (self.previous_limit or Decimal("0.00")))
        if delta <= 0:
            return  # decreases are always allowed

        ca = self.credit_account
        if getattr(ca, "funder_id", None):
            alloc = (
                FunderAllocation.objects
                .filter(funder=ca.funder, client=ca.client)
                .values_list("amount", flat=True)
                .first()
            ) or Decimal("0.00")

            # proposed_limit equals the intended new limit
            proposed_limit = _r2((ca.credit_limit or Decimal("0.00")) + delta)  # == self.new_limit (normalized)
            if proposed_limit > _r2(alloc):
                raise ValidationError(
                    f"Limit increase would exceed this client's allocation with {ca.funder.name} "
                    f"(allocation R{alloc:.2f}, proposed limit R{proposed_limit:.2f})."
                )

    @transaction.atomic
    def save(self, *args, **kwargs):
        is_create = self.pk is None

        if is_create:
            prev_lim = _r2(self.previous_limit or Decimal("0.00"))
            new_lim  = _r2(self.new_limit or Decimal("0.00"))
            delta    = _r2(new_lim - prev_lim)

            if delta > 0:
                ca = self.credit_account

                # 1) If this account is tied to a funder, try to provision allocation BEFORE validating totals
                if getattr(ca, "funder_id", None):
                    _ensure_allocation_or_best_effort(
                        funder=ca.funder,
                        client=ca.client,
                        target_amount=new_lim,   # mirror desired limit
                    )

                # 2) Validate total allocation across ALL funders covers the new limit
                total_alloc_to_client = _r2(
                    FunderAllocation.objects
                    .filter(client=ca.client)
                    .aggregate(s=Coalesce(Sum("amount"), Decimal("0.00")))["s"]
                    or Decimal("0.00")
                )
                if new_lim > total_alloc_to_client:
                    help_txt = (
                        f"Funder '{ca.funder.name}' may not have enough available balance. "
                        "Top up or adjust allocations, then try again."
                        if getattr(ca, 'funder_id', None) else
                        "Assign a funder and/or allocate capital, then try again."
                    )
                    raise ValidationError([
                        f"Proposed limit R{new_lim:.2f} exceeds the total allocated to this client "
                        f"across all funders (R{total_alloc_to_client:.2f}). {help_txt}"
                    ])

        super().save(*args, **kwargs)

        # Only emit ledger entry when first created
        if not is_create:
            return

        prev_lim = _r2(self.previous_limit or Decimal("0.00"))
        new_lim  = _r2(self.new_limit or Decimal("0.00"))
        delta    = _r2(new_lim - prev_lim)
        if delta == 0:
            return

        # Emit ledger entry which will update credit_limit via signals
        if delta > 0:
            CreditEntry.objects.create(
                credit_account=self.credit_account,
                kind=CreditEntry.ISSUE,
                amount=delta,
                reference=f"CREDIT-LIMIT-{self.pk}",
                note=(self.note or f"Credit limit increased from R{prev_lim} to R{new_lim}").strip(),
            )
        else:
            CreditEntry.objects.create(
                credit_account=self.credit_account,
                kind=CreditEntry.LIMIT_DECREASE,
                amount=abs(delta),
                reference=f"CREDIT-LIMIT-{self.pk}",
                note=(self.note or f"Credit limit decreased from R{prev_lim} to R{new_lim}").strip(),
            )

        # Ensure final state has a matching allocation even if the view saved funder AFTER this log
        transaction.on_commit(lambda: _sync_allocation_for_current_state(self.credit_account_id))

    @staticmethod
    def _sync_allocation_for_current_state(credit_account_id: int) -> None:
        """
        After commit, re-fetch the CreditAccount and ensure funder allocation ~= current credit_limit.
        Safe to call repeatedly; uses best-effort clamping.
        """
        try:
            ca = CreditAccount.objects.select_related("funder", "client").get(pk=credit_account_id)
        except CreditAccount.DoesNotExist:
            return
        if not ca.funder_id:
            return
        _ensure_allocation_or_best_effort(
            funder=ca.funder,
            client=ca.client,
            target_amount=_r2(ca.credit_limit or Decimal("0.00")),
        )
        # Also refresh this week's summary so caps match the limit
        try:
            ca.funder.rebuild_week(monday_of(date.today()))
        except Exception:
            pass


# ====================================================================
# CreditEntry: append-only ledger of all credit movements
#   - Affects credit_used: USAGE, REPAYMENT, ADJUSTMENT, WRITEOFF
#   - Affects credit_limit: ISSUE (increase), LIMIT_DECREASE (decrease)
# ====================================================================
class CreditEntry(models.Model):
    USAGE          = "usage"           # credit consumed on an invoice (credit_used +)
    REPAYMENT      = "repayment"       # client pays down credit (credit_used -)
    ADJUSTMENT     = "adjustment"      # manual correction on used (credit_used +)
    WRITEOFF       = "writeoff"        # write-off reduces used (credit_used -)
    ISSUE          = "issue"           # credit issued / limit increase (credit_limit +)
    LIMIT_DECREASE = "limit_decrease"  # limit decrease (credit_limit -)

    KIND_CHOICES = [
        (USAGE, "Credit Used"),
        (REPAYMENT, "Credit Repaid"),
        (ADJUSTMENT, "Adjustment (Used)"),
        (WRITEOFF, "Write-off"),
        (ISSUE, "Credit Issued (Limit +)"),
        (LIMIT_DECREASE, "Limit Decrease (Limit -)"),
    ]

    credit_account = models.ForeignKey(
        CreditAccount, on_delete=models.CASCADE, related_name="entries"
    )
    kind   = models.CharField(max_length=16, choices=KIND_CHOICES)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    posted_at = models.DateTimeField(default=now, db_index=True)

    # Optional links for traceability
    invoice = models.ForeignKey(
        "invoices.Invoice", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_entries"
    )
    transaction = models.ForeignKey(
        "transactions.Transaction", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_entries"
    )
    reference = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)

    # Who created this entry (optional, useful for admin/ops)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_entries_created"
    )

    class Meta:
        ordering = ["-posted_at", "-id"]
        indexes = [
            models.Index(fields=["credit_account", "posted_at"]),
            models.Index(fields=["kind", "posted_at"]),
            models.Index(fields=["invoice"]),
        ]

    def __str__(self):
        return f"{self.credit_account.client} · {self.kind} · R{self.amount} on {self.posted_at.date()}"

    # ---------- strict 50% rule checker (used by Order creation gate) ----------
    @classmethod
    def check_50pct_rule(cls, client: Client) -> Tuple[bool, Optional[str]]:
        """
        Rule:
        - Find the client's last invoice that used credit (credit_used > 0).
        - Find the client's last USAGE (credit out) entry.
        - The two amounts must match.
        - The *next* credit movement AFTER that USAGE (consider only USAGE/REPAYMENT)
          must be a REPAYMENT and its single-transaction amount must be >= 50% of the USAGE.
        """
        from invoices.models import Invoice  # lazy import

        # Last invoice that actually used credit
        last_inv = (
            Invoice.objects.filter(client=client, credit_used__gt=0)
            .order_by("-created_at", "-id")
            .first()
        )
        if not last_inv:
            # No historical credit usage: allow
            return True, None

        ca, _ = CreditAccount.objects.get_or_create(client=client)

        # Latest OUT on the ledger
        last_out = (
            cls.objects.filter(credit_account=ca, kind=cls.USAGE)
            .order_by("-posted_at", "-id")
            .first()
        )
        if not last_out:
            return False, "No 'credit used' entry found to match the last credit-using invoice."

        out_amt = r2(last_out.amount)
        inv_used = r2(last_inv.credit_used)

        if out_amt != inv_used:
            return (
                False,
                f"Credit mismatch: last credit-out is R{out_amt:.2f} but the last invoice shows credit-used R{inv_used:.2f}. "
                "Please reconcile the credit ledger or the invoice snapshots."
            )

        # The *next* credit movement AFTER that OUT (only IN/OUT types, ignore adjustments/writeoffs)
        next_move = (
            cls.objects.filter(
                credit_account=ca,
                kind__in=[cls.USAGE, cls.REPAYMENT],
                posted_at__gt=last_out.posted_at,
            )
            .order_by("posted_at", "id")
            .first()
        )

        if not next_move:
            return (
                False,
                "No repayment recorded after the last credit-out. "
                "At least 50% repayment must be received before placing a new order."
            )

        if next_move.kind != cls.REPAYMENT:
            return (
                False,
                "The next credit movement after the last credit-out is not a repayment. "
                "A repayment of at least 50% is required before placing a new order."
            )

        threshold = r2(out_amt * Decimal("0.50"))
        repaid = r2(next_move.amount)

        if repaid < threshold:
            return (
                False,
                f"Repayment too low: next credit-in is R{repaid:.2f}, but at least R{threshold:.2f} "
                "is required (50% of the last credit-out) before placing a new order."
            )

        return True, None

    # ---------- convenience creators ----------
    @classmethod
    def record_usage(
        cls,
        *,
        client: Client,
        amount: Decimal,
        invoice=None,
        reference: str = "",
        note: str = "",
        when=None,
        created_by=None,
    ) -> "CreditEntry":
        ca, _ = CreditAccount.objects.get_or_create(client=client)
        return cls.objects.create(
            credit_account=ca,
            kind=cls.USAGE,
            amount=r2(amount),
            posted_at=when or now(),
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
        transaction=None,
        reference: str = "",
        note: str = "",
        when=None,
        created_by=None,
    ) -> "CreditEntry":
        ca, _ = CreditAccount.objects.get_or_create(client=client)
        return cls.objects.create(
            credit_account=ca,
            kind=cls.REPAYMENT,
            amount=r2(amount),
            posted_at=when or now(),
            invoice=invoice,
            transaction=transaction,
            reference=reference,
            note=note,
            created_by=created_by,
        )

    @classmethod
    def record_adjustment(
        cls,
        *,
        client: Client,
        amount: Decimal,
        reference: str = "",
        note: str = "",
        when=None,
        created_by=None,
    ) -> "CreditEntry":
        ca, _ = CreditAccount.objects.get_or_create(client=client)
        return cls.objects.create(
            credit_account=ca,
            kind=cls.ADJUSTMENT,
            amount=r2(amount),
            posted_at=when or now(),
            reference=reference,
            note=note,
            created_by=created_by,
        )

    @classmethod
    def record_writeoff(
        cls,
        *,
        client: Client,
        amount: Decimal,
        reference: str = "",
        note: str = "",
        when=None,
        created_by=None,
    ) -> "CreditEntry":
        ca, _ = CreditAccount.objects.get_or_create(client=client)
        return cls.objects.create(
            credit_account=ca,
            kind=cls.WRITEOFF,
            amount=r2(amount),
            posted_at=when or now(),
            reference=reference,
            note=note,
            created_by=created_by,
        )


# ====================================================================
# Signals: keep CreditAccount.credit_used & credit_limit in sync
# ====================================================================
def _apply_entry_delta(ca: CreditAccount, entry: CreditEntry, reverse: bool = False):
    """
    Apply or unapply a CreditEntry to the account's running totals:
    - credit_used is affected by USAGE / REPAYMENT / ADJUSTMENT / WRITEOFF
    - credit_limit is affected by ISSUE / LIMIT_DECREASE
    Safe: wrapped in transaction.on_commit.
    """
    try:
        with transaction.atomic():
            used  = r2(ca.credit_used or Decimal("0.00"))
            limit = r2(ca.credit_limit or Decimal("0.00"))
            amt   = r2(entry.amount or Decimal("0.00"))
            sgn   = Decimal("-1.00") if reverse else Decimal("1.00")

            if entry.kind == CreditEntry.USAGE:
                used += sgn * amt
            elif entry.kind in (CreditEntry.REPAYMENT, CreditEntry.WRITEOFF):
                used -= sgn * amt
            elif entry.kind == CreditEntry.ADJUSTMENT:
                used += sgn * amt
            elif entry.kind == CreditEntry.ISSUE:
                limit += sgn * amt
            elif entry.kind == CreditEntry.LIMIT_DECREASE:
                limit -= sgn * amt

            used = max(used, Decimal("0.00"))
            limit = max(limit, Decimal("0.00"))

            ca.credit_used  = r2(used)
            ca.credit_limit = r2(limit)
            ca.save(update_fields=["credit_used", "credit_limit", "updated_at"])
            logger.debug(f"Applied CreditEntry {entry.pk} ({entry.kind}) -> Used: {used}, Limit: {limit}")
    except Exception as e:
        logger.exception(f"Failed to apply CreditEntry {entry.pk}: {e}")
        raise

# Ensure this always runs after DB commit
@receiver(post_save, sender=CreditEntry)
def creditentry_apply(sender, instance: CreditEntry, created, **kwargs):
    if not created:
        return

    transaction.on_commit(lambda: _apply_entry_delta(instance.credit_account, instance))

# Keep FunderAllocation in sync safely
@receiver(post_save, sender=CreditEntry)
def sync_allocation_on_limit_change(sender, instance: CreditEntry, created, **kwargs):
    if not created:
        return
    if instance.kind not in (CreditEntry.ISSUE, CreditEntry.LIMIT_DECREASE):
        return
    ca = instance.credit_account
    if not ca.funder_id:
        return

    def _sync():
        try:
            _ensure_allocation_or_best_effort(
                funder=ca.funder,
                client=ca.client,
                target_amount=_r2(ca.credit_limit or Decimal("0.00")),
            )
            # Rebuild this week's summary
            ws = monday_of(instance.posted_at.date())
            ca.funder.rebuild_week(ws)
        except Exception as e:
            logger.exception(f"Failed to sync allocation for CreditEntry {instance.pk}: {e}")

    transaction.on_commit(_sync)

# ---------- creators (usage, repayment, adjustment, writeoff) ----------
# Ensure the delta is applied immediately, even if bulk_create is used
def _create_credit_entry_safe(cls, ca: CreditAccount, kind: str, amount: Decimal, **kwargs) -> CreditEntry:
    entry = cls.objects.create(credit_account=ca, kind=kind, amount=r2(amount), **kwargs)
    # Immediately apply delta after commit
    transaction.on_commit(lambda: _apply_entry_delta(ca, entry))
    return entry

# Example usage:
@classmethod
def record_usage(cls, *, client: Client, amount: Decimal, **kwargs):
    ca, _ = CreditAccount.objects.get_or_create(client=client)
    return _create_credit_entry_safe(cls, ca, cls.USAGE, amount, **kwargs)

@classmethod
def record_repayment(cls, *, client: Client, amount: Decimal, **kwargs):
    ca, _ = CreditAccount.objects.get_or_create(client=client)
    return _create_credit_entry_safe(cls, ca, cls.REPAYMENT, amount, **kwargs)

@classmethod
def record_adjustment(cls, *, client: Client, amount: Decimal, **kwargs):
    ca, _ = CreditAccount.objects.get_or_create(client=client)
    return _create_credit_entry_safe(cls, ca, cls.ADJUSTMENT, amount, **kwargs)

@classmethod
def record_writeoff(cls, *, client: Client, amount: Decimal, **kwargs):
    ca, _ = CreditAccount.objects.get_or_create(client=client)
    return _create_credit_entry_safe(cls, ca, cls.WRITEOFF, amount, **kwargs)
# NEW: keep FunderAllocation in sync when credit_limit changes (ISSUE / LIMIT_DECREASE)
@receiver(post_save, sender=CreditEntry)
def sync_allocation_on_limit_change(sender, instance: CreditEntry, created, **kwargs):
    """
    When credit_limit changes via ledger entries (ISSUE / LIMIT_DECREASE),
    mirror the allocation on the current funder to ~= credit_limit (best-effort).
    Also refresh this week's funder summary since caps depend on credit_limit.
    """
    if not created:
        return
    if instance.kind not in (CreditEntry.ISSUE, CreditEntry.LIMIT_DECREASE):
        return

    ca = instance.credit_account
    if not ca.funder_id:
        return

    # Keep allocation ≈ current limit, with cap/validation handled inside helper
    _ensure_allocation_or_best_effort(
        funder=ca.funder,
        client=ca.client,
        target_amount=_r2(ca.credit_limit or Decimal("0.00")),
    )

    # Rebuild this week's summary so visible utilization aligns with new caps
    try:
        ws = monday_of(instance.posted_at.date())
        ca.funder.rebuild_week(ws)
    except Exception:
        # don't block the save path on reporting; log if you have logging in place
        pass
    
# NEW: refresh funder week on USAGE/REPAYMENT/ADJUSTMENT/WRITEOFF as activity occurs
@receiver(post_save, sender=CreditEntry)
def refresh_funder_week_on_usage_like(sender, instance: CreditEntry, created, **kwargs):
    """
    For operational visibility, rebuild the funder's weekly snapshot when credit
    usage-like movements are recorded. Repayments do not reduce 'visible utilization'
    (which is capped against the week's credit_limit), but rebuilding is harmless
    and keeps reports up to date in case your policy changes.
    """
    if not created:
        return
    if instance.kind not in (CreditEntry.USAGE, CreditEntry.REPAYMENT, CreditEntry.ADJUSTMENT, CreditEntry.WRITEOFF):
        return
    ca = instance.credit_account
    if not getattr(ca, "funder_id", None):
        return
    try:
        ws = monday_of(instance.posted_at.date())
        ca.funder.rebuild_week(ws)
    except Exception:
        pass


@receiver(post_delete, sender=CreditEntry)
def creditentry_unapply(sender, instance: CreditEntry, **kwargs):
    _apply_entry_delta(instance.credit_account, instance, reverse=True)


# Also refresh funder week if an entry is deleted (e.g., correction)
@receiver(post_delete, sender=CreditEntry)
def refresh_funder_week_on_entry_delete(sender, instance: CreditEntry, **kwargs):
    ca = instance.credit_account
    if not getattr(ca, "funder_id", None):
        return
    try:
        ws = monday_of(instance.posted_at.date())
        ca.funder.rebuild_week(ws)
    except Exception:
        pass


# ====================================================================
# NEW: Keep Funder side in sync when CreditAccount.funder changes
# ====================================================================

def _ensure_allocation_or_best_effort(*, funder: Funder, client: Client, target_amount: Decimal) -> None:
    """
    Try to set FunderAllocation to target_amount. If validation says we exceed
    funder.balance, fall back to the maximum feasible amount (allocatable_balance + current).
    This avoids raising from inside a post_save signal.
    """
    target_amount = _r2(target_amount or Decimal("0.00"))

    alloc, created = FunderAllocation.objects.get_or_create(
        funder=funder, client=client, defaults={"amount": target_amount}
    )
    if created:
        try:
            alloc.full_clean()
            alloc.save(update_fields=["amount", "updated_at"])
            return
        except ValidationError:
            pass  # fall through to best-effort path

    current = _r2(alloc.amount or Decimal("0.00"))
    try:
        alloc.amount = target_amount
        alloc.full_clean()
        alloc.save(update_fields=["amount", "updated_at"])
        return
    except ValidationError:
        # Best-effort: don't exceed funder.balance across all allocations.
        # Max extra we can add = funder.allocatable_balance + current allocation for this client
        # (since allocatable_balance excludes this row)
        max_total_for_this_client = _r2(current + funder.allocatable_balance)
        alloc.amount = max(Decimal("0.00"), min(target_amount, max_total_for_this_client))
        try:
            alloc.full_clean()
            alloc.save(update_fields=["amount", "updated_at"])
        except ValidationError:
            # If it STILL fails, keep the current amount (last known valid) and swallow.
            pass


@receiver(pre_save, sender=CreditAccount)
def creditaccount_capture_previous_funder(sender, instance: CreditAccount, **kwargs):
    """
    Before saving, capture the previous funder_id so post_save can compare.
    """
    if instance.pk:
        try:
            prev = CreditAccount.objects.only("funder_id", "client_id", "credit_limit").get(pk=instance.pk)
            instance._prev_funder_id = prev.funder_id
        except CreditAccount.DoesNotExist:
            instance._prev_funder_id = None
    else:
        instance._prev_funder_id = None


@receiver(post_save, sender=CreditAccount)
def creditaccount_sync_funder_side(sender, instance: CreditAccount, created, **kwargs):
    """
    If the account's funder changed:
      - remove this client’s allocation from the old funder
      - create/resize allocation on the new funder to match the current credit_limit (best effort)
      - rebuild this ISO week’s summaries for both funders
    """
    old_id = getattr(instance, "_prev_funder_id", None)
    new_id = instance.funder_id

    if old_id == new_id:
        return  # no change

    with transaction.atomic():
        # Remove old allocation (for this client only)
        if old_id:
            FunderAllocation.objects.filter(funder_id=old_id, client=instance.client).delete()

        # Ensure new allocation ~= current credit_limit
        if new_id:
            _ensure_allocation_or_best_effort(
                funder=instance.funder,
                client=instance.client,
                target_amount=_r2(instance.credit_limit or Decimal("0.00")),
            )

    # Rebuild this week’s summaries for both funders (non-fatal if anything goes wrong)
    try:
        today = date.today()
        ws = monday_of(today)
        if old_id:
            try:
                old_funder = Funder.objects.get(pk=old_id)
                old_funder.rebuild_week(ws)
            except Funder.DoesNotExist:
                pass
        if new_id:
            instance.funder.rebuild_week(ws)
    except Exception:
        # Avoid blocking the save if summaries fail; optionally log the exception.
        pass
