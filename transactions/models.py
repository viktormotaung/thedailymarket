# transactions/models.py
from __future__ import annotations

from decimal import Decimal

from django.apps import apps
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.utils.timezone import now, localdate
from django.utils import timezone



# ---------- helpers ----------
def _r2(x: Decimal | None) -> Decimal:
    return Decimal("0.00") if x is None else x.quantize(Decimal("0.01"))


# Which transaction types count as “money in” on an invoice’s **cash deposit**
# Ledger-first model: credit movements do NOT count toward deposit.
INVOICE_PAYMENT_TYPES = {"payment", "refund"}  # refunds are deducted from receipts


# =========================
# Business-wide balance row
# =========================
class BusinessBalance(models.Model):
    """
    Singleton row tracking Seshibo Daily Market's running totals.
    """
    name = models.CharField(max_length=64, unique=True, default="Seshibo Daily Market")
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_in = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_out = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    updated_at = models.DateTimeField(auto_now=True)

    # Only actual cash receipts increase the business/client running balances.
    # credit_issue is a non-cash funding allocation and must have zero balance impact.
    # Keep legacy credit_usage as a debit for historical compatibility.
    CREDIT_TYPES = {"payment", "credit_repayment"}
    DEBIT_TYPES = {"invoice", "credit_usage", "adjustment", "refund"}

    class Meta:
        verbose_name = "Business balance"
        verbose_name_plural = "Business balances"

    @classmethod
    def get_seshibo(cls, *, using="default", for_update=False):
        qs = cls.objects.using(using)
        if for_update:
            qs = qs.select_for_update()
        obj, _ = qs.get_or_create(name="Seshibo Daily Market")
        return obj

    @staticmethod
    def signed_amount(t_type: str | None, amount: Decimal | None) -> Decimal:
        if not t_type or amount is None:
            return Decimal("0.00")
        if t_type in BusinessBalance.CREDIT_TYPES:
            return _r2(amount)
        if t_type in BusinessBalance.DEBIT_TYPES:
            return _r2(amount) * Decimal("-1")
        return Decimal("0.00")

    def apply_delta(self, delta: Decimal) -> None:
        if delta == 0:
            return
        self.balance = F("balance") + delta
        if delta > 0:
            self.total_in = F("total_in") + delta
        else:
            self.total_out = F("total_out") + (-delta)
        self.save(update_fields=["balance", "total_in", "total_out", "updated_at"])


# ==================
# Per-client ledger
# ==================
class ClientBalance(models.Model):
    """
    One row per client that mirrors the business ledger (but scoped to the client).
    """
    client = models.OneToOneField("clients.Client", on_delete=models.CASCADE, related_name="balance_row")
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_in = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_out = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Client balance"
        verbose_name_plural = "Client balances"


    @classmethod
    def get_for_client(cls, client_id: int, *, using="default", for_update=False):
        qs = cls.objects.using(using)
        if for_update:
            qs = qs.select_for_update()
        obj, _ = qs.get_or_create(client_id=client_id)
        return obj

    def apply_delta(self, delta: Decimal) -> None:
        if delta == 0:
            return
        self.balance = F("balance") + delta
        if delta > 0:
            self.total_in = F("total_in") + delta
        else:
            self.total_out = F("total_out") + (-delta)
        self.save(update_fields=["balance", "total_in", "total_out", "updated_at"])


# ============
# Transaction
# ============
class Transaction(models.Model):
    """
    Transactions are the audit trail for financial and non-cash events.
    Saving or deleting a row updates:
      - BusinessBalance (global) and ClientBalance for cash/debit movements
      - Linked Invoice deposit+status (cash deposit dimension only)
      - Credit ledger via CreditEntry (repayments only; usage is managed by Invoice)

    credit_issue is informational/non-cash: it is retained in this table but
    deliberately has zero impact on either running balance.
    """
    TRANSACTION_TYPES = [
        ("payment", "Payment In"),
        ("invoice", "Invoice Out"),
        ("credit_issue", "Credit Issued"),
        ("credit_usage", "Credit Used"),          # legacy; new flows should not create these
        ("credit_repayment", "Credit Repaid"),
        ("refund", "Refund"),
        ("adjustment", "Manual Adjustment"),
    ]

    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="transactions")
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )

    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # snapshots immediately AFTER this row is applied
    balance = models.DecimalField(           # business-wide snapshot
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Business balance immediately after this transaction."
    )
    client_balance = models.DecimalField(    # per-client snapshot
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Client balance immediately after this transaction."
    )

    reference = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["client", "transaction_type", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "transaction_type"],
                condition=Q(invoice__isnull=False) & Q(transaction_type__in=["invoice", "credit_issue"]),
                name="uniq_inv_txn_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.client} · {self.transaction_type} · R{self.amount:.2f}"

    # ----- convenience flags -----
    @property
    def is_credit(self) -> bool:
        """True only for transaction rows representing money received."""
        return self.transaction_type in {"payment", "credit_repayment"}

    @property
    def is_debit(self) -> bool:
        """True only for transaction rows that reduce the running balance."""
        return self.transaction_type in {"invoice", "credit_usage", "adjustment", "refund"}

    @property
    def is_neutral(self) -> bool:
        """Non-cash informational transaction; shown without +/- and no balance impact."""
        return self.transaction_type == "credit_issue"

    # ------------------------------------------------------------------
    # CreditEntry mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _rebuild_credit_account_ledger(account_id, *, using):
        """Recalculate running CreditEntry balances after an edit or reversal."""
        CreditEntry = apps.get_model("credit", "CreditEntry")
        CreditAccount = apps.get_model("credit", "CreditAccount")
        running = Decimal("0.00")
        entries = CreditEntry.objects.using(using).filter(
            credit_account_id=account_id
        ).order_by("id")
        for entry in entries:
            amount = _r2(entry.amount)
            if entry.kind in {CreditEntry.ISSUE, CreditEntry.REPAYMENT, CreditEntry.WRITEOFF, CreditEntry.ADJUSTMENT}:
                running += amount
            elif entry.kind in {CreditEntry.USAGE, CreditEntry.LIMIT_DECREASE}:
                running -= amount
            CreditEntry.objects.using(using).filter(pk=entry.pk).update(balance=_r2(running))
        account = CreditAccount.objects.using(using).filter(pk=account_id).first()
        if account:
            account.save(using=using)

    @staticmethod
    def _creditentry_kind(t_type):
        if t_type == "credit_repayment":
            return "repayment"
        if t_type == "credit_usage":  # legacy compatibility only
            return "usage"
        return None

    def _sync_credit_entry_after_save(self, *, old_type=None, old_client_id=None):
        """Keep at most one CreditEntry linked to this transaction.

        Repayments and legacy usage remain in the CreditEntry ledger. The
        transaction remains the cash/audit record; the linked CreditEntry is
        the TradeAssist exposure record. Both are created in the same DB.
        """
        db = self._state.db or "default"
        CreditEntry = apps.get_model("credit", "CreditEntry")
        CreditAccount = apps.get_model("credit", "CreditAccount")

        kind = self._creditentry_kind(self.transaction_type)
        linked = list(
            CreditEntry.objects.using(db)
            .filter(transaction_id=self.pk)
            .select_related("credit_account")
            .order_by("id")
        )

        if not kind:
            if linked:
                accounts = {entry.credit_account_id: entry.credit_account for entry in linked}
                CreditEntry.objects.using(db).filter(transaction_id=self.pk).delete()
                for account in accounts.values():
                    self._rebuild_credit_account_ledger(account.pk, using=db)
            return None

        account, _ = CreditAccount.objects.using(db).get_or_create(client_id=self.client_id)
        expected_kind = kind
        existing = linked[0] if linked else None

        # If the transaction changed from usage to repayment (or vice versa),
        # or its client changed, reverse the old linked ledger row before
        # recording the new kind/account.
        if existing and (
            existing.kind != expected_kind
            or existing.credit_account_id != account.pk
        ):
            old_accounts = {entry.credit_account_id: entry.credit_account for entry in linked}
            CreditEntry.objects.using(db).filter(transaction_id=self.pk).delete()
            for old_account in old_accounts.values():
                self._rebuild_credit_account_ledger(old_account.pk, using=db)
            linked = []
            existing = None

        if existing:
            existing.amount = _r2(self.amount)
            existing.invoice_id = self.invoice_id or None
            existing.posted_at = self.created_at
            existing.reference = self.reference or existing.reference
            existing.note = self.note or existing.note
            existing.save(using=db)
            self._rebuild_credit_account_ledger(existing.credit_account_id, using=db)
            return existing

        if kind == "repayment":
            entry = CreditEntry.record_repayment(
                client=self.client,
                amount=_r2(self.amount),
                invoice=(
                    apps.get_model("invoices", "Invoice").objects.using(db)
                    .filter(pk=self.invoice_id).first()
                    if self.invoice_id else None
                ),
                transaction=self,
                reference=self.reference or f"TX-{self.pk}",
                note=self.note or f"Credit repayment from transaction {self.pk}",
                using=db,
            )
            if self.created_at and self.created_at != entry.posted_at:
                entry.posted_at = self.created_at
                entry.save(using=db, update_fields=["posted_at"])
            return entry

        # Legacy credit_usage only. New TradeAssist allocations are created
        # through Invoice.ensure_credit_usage_entry(), not this transaction map.
        return CreditEntry.objects.using(db).create(
            credit_account=account,
            kind=kind,
            amount=_r2(self.amount),
            posted_at=self.created_at,
            invoice_id=self.invoice_id or None,
            transaction=self,
            reference=self.reference,
            note=self.note or f"Legacy credit usage from transaction {self.pk}",
        )

    def _delete_credit_entry(self) -> None:
        """Remove linked credit ledger rows and recalculate affected accounts."""
        CreditEntry = apps.get_model("credit", "CreditEntry")
        db = self._state.db or "default"
        entries = list(
            CreditEntry.objects.using(db)
            .filter(transaction_id=self.pk)
            .select_related("credit_account")
        )
        if not entries:
            return
        accounts = {entry.credit_account_id: entry.credit_account for entry in entries}
        CreditEntry.objects.using(db).filter(transaction_id=self.pk).delete()
        for account in accounts.values():
            self._rebuild_credit_account_ledger(account.pk, using=db)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _current_db_values(self):
        """Fetch existing transaction values from its own database."""
        if not self.pk:
            return None, None, None, None

        db = self._state.db or "default"
        try:
            row = (
                Transaction.objects.using(db)
                .only("transaction_type", "amount", "client_id", "invoice_id")
                .get(pk=self.pk)
            )
            return row.transaction_type, row.amount, row.client_id, row.invoice_id
        except Transaction.DoesNotExist:
            return None, None, None, None

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    @transaction.atomic
    def save(self, *args, **kwargs):
        old_type, old_amount, old_client_id, old_invoice_id = self._current_db_values()
        db = kwargs.get("using") or self._state.db or "default"

        # When callers use update_fields, only apply ledger deltas for fields
        # that Django will actually persist.
        if kwargs.get("update_fields") and old_type is not None:
            requested = set(kwargs["update_fields"])
            if "transaction_type" not in requested:
                self.transaction_type = old_type
            if "amount" not in requested:
                self.amount = old_amount
            if not ({"client", "client_id"} & requested):
                self.client_id = old_client_id
            if not ({"invoice", "invoice_id"} & requested):
                self.invoice_id = old_invoice_id

        new_signed = BusinessBalance.signed_amount(self.transaction_type, self.amount)
        old_signed = BusinessBalance.signed_amount(old_type, old_amount)
        business_delta = new_signed - old_signed

        bb = BusinessBalance.get_seshibo(using=db, for_update=True)
        new_cb = ClientBalance.get_for_client(self.client_id, using=db, for_update=True)
        old_cb = None
        if old_client_id and old_client_id != self.client_id:
            old_cb = ClientBalance.get_for_client(old_client_id, using=db, for_update=True)

        self.balance = bb.balance + business_delta
        # Snapshot for the client attached to this transaction after its own
        # signed movement is applied.
        client_delta = new_signed if old_client_id != self.client_id else business_delta
        self.client_balance = new_cb.balance + client_delta

        if kwargs.get("update_fields"):
            update_fields = set(kwargs["update_fields"])
            update_fields.update({"balance", "client_balance"})
            kwargs["update_fields"] = list(update_fields)

        super().save(*args, **kwargs)

        if business_delta:
            bb.apply_delta(business_delta)

        if old_client_id and old_client_id != self.client_id and old_cb:
            if old_signed:
                old_cb.apply_delta(-old_signed)
            if new_signed:
                new_cb.apply_delta(new_signed)
        elif client_delta:
            new_cb.apply_delta(client_delta)

        # Keep any existing CreditEntry mapping idempotent across edits.
        self._sync_credit_entry_after_save(
            old_type=old_type,
            old_client_id=old_client_id,
        )

        # If the invoice relation changed, refresh the previous invoice too.
        if old_invoice_id and old_invoice_id != self.invoice_id:
            old_invoice = apps.get_model("invoices", "Invoice").objects.using(db).filter(pk=old_invoice_id).first()
            if old_invoice:
                self._sync_invoice_totals_and_status(inv_override=old_invoice)

        if self.invoice_id:
            self._sync_invoice_totals_and_status()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    @transaction.atomic
    def delete(self, *args, **kwargs):
        db = kwargs.get("using") or self._state.db or "default"
        invoice_id = self.invoice_id
        client_id = self.client_id
        cur_signed = BusinessBalance.signed_amount(self.transaction_type, self.amount)

        bb = BusinessBalance.get_seshibo(using=db, for_update=True)
        cb = ClientBalance.get_for_client(client_id, using=db, for_update=True)

        # Delete the linked TA ledger row before the transaction disappears.
        self._delete_credit_entry()
        super().delete(*args, **kwargs)

        if cur_signed:
            bb.apply_delta(-cur_signed)
            cb.apply_delta(-cur_signed)

        if invoice_id:
            invoice = apps.get_model("invoices", "Invoice").objects.using(db).filter(pk=invoice_id).first()
            if invoice:
                self._sync_invoice_totals_and_status(inv_override=invoice)

    # ----- invoice sync helper -----
    def _sync_invoice_totals_and_status(self, *, inv_override=None) -> None:
        Invoice = apps.get_model("invoices", "Invoice")
        db = self._state.db or "default"
        inv = inv_override or Invoice.objects.using(db).filter(pk=self.invoice_id).first()
        if not inv:
            return

        totals = Transaction.objects.using(db).filter(invoice_id=inv.id).aggregate(
            payments=Sum("amount", filter=Q(transaction_type="payment")),
            refunds=Sum("amount", filter=Q(transaction_type="refund")),
        )
        net_receipts = (totals["payments"] or Decimal("0.00")) - (totals["refunds"] or Decimal("0.00"))
        inv.deposit_paid = max(_r2(net_receipts), Decimal("0.00"))

        today = localdate()
        if inv.deposit_paid >= inv.amount_due:
            new_status = "paid"
        elif inv.due_date and today > inv.due_date:
            new_status = "overdue"
        elif inv.deposit_paid > 0:
            new_status = "partial"
        else:
            new_status = "unpaid"

        transition_to_paid = new_status == "paid" and inv.status != "paid"
        inv.status = new_status
        update_fields = ["deposit_paid", "status", "updated_at"]
        if new_status == "paid":
            paid_at = (
                Transaction.objects.using(db)
                .filter(invoice_id=inv.id, transaction_type="payment")
                .order_by("-created_at", "-id")
                .values_list("created_at", flat=True)
                .first()
            )
            inv.paid_date = timezone.localtime(paid_at).date() if paid_at else today
            update_fields.append("paid_date")
        elif inv.paid_date is not None:
            inv.paid_date = None
            update_fields.append("paid_date")
        inv.save(using=db, update_fields=update_fields)

        # Picking date/wave must follow the payment that completed the
        # customer's contribution, not the earlier order creation timestamp.
        PickingBatch = apps.get_model("deliveries", "PickingBatch")
        if transition_to_paid and inv.order_id:
            event_dt = (
                Transaction.objects.using(db)
                .filter(invoice_id=inv.id, transaction_type="payment")
                .order_by("-created_at", "-id")
                .values_list("created_at", flat=True)
                .first()
            ) or now()
            local_dt = timezone.localtime(event_dt)
            wave = "AM" if local_dt.hour < 12 else "PM"
            batch, _ = PickingBatch.get_or_create_wave(
                service_date=local_dt.date(),
                wave=wave,
                db=db,
            )
            batch.add_order(inv.order)

        try:
            inv.ensure_credit_after_deposit()
        except Exception as e:
            print("❌ CREDIT SYNC ERROR:", e, "DB:", db, "TX:", self.id)
            raise
