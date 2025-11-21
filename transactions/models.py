# transactions/models.py
from __future__ import annotations

from decimal import Decimal

from django.apps import apps
from django.db import models, transaction
from django.db.models import F, Sum
from django.utils.timezone import now, localdate
from django.utils import timezone


# ---------- helpers ----------
def _r2(x: Decimal | None) -> Decimal:
    return Decimal("0.00") if x is None else x.quantize(Decimal("0.01"))


# Which transaction types count as “money in” on an invoice’s **cash deposit**
# Ledger-first model: credit movements do NOT count toward deposit.
INVOICE_PAYMENT_TYPES = {"payment", "refund"}  # excluded: credit_issue, credit_repayment


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

    # NOTE: keep legacy types for historical data; new flows shouldn't emit "credit_usage".
    CREDIT_TYPES = {"payment", "credit_issue", "credit_repayment", "refund"}
    DEBIT_TYPES = {"invoice", "credit_usage", "adjustment"}

    class Meta:
        verbose_name = "Business balance"
        verbose_name_plural = "Business balances"

    @classmethod
    def get_seshibo(cls, *, for_update: bool = False) -> "BusinessBalance":
        qs = cls.objects
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
    def get_for_client(cls, client_id: int, *, for_update: bool = False) -> "ClientBalance":
        qs = cls.objects
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
    Every row moves money in/out. Saving or deleting a row updates:
      - BusinessBalance (global)
      - ClientBalance (for the row’s client)
      - Linked Invoice deposit+status (if any)  [cash deposit dimension only]
      - Credit ledger via CreditEntry (repayments only; usage is managed by Invoice]
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
        "invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions"
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

    def __str__(self) -> str:
        return f"{self.client} · {self.transaction_type} · R{self.amount:.2f}"

    # ----- convenience flags -----
    @property
    def is_credit(self) -> bool:
        return self.transaction_type in {"payment", "credit_issue", "credit_repayment", "refund"}

    @property
    def is_debit(self) -> bool:
        return self.transaction_type in {"invoice", "credit_usage", "adjustment"}

    # ----- CreditEntry mapping -----
    @staticmethod
    def _creditentry_kind(t_type: str | None) -> str | None:
        """
        Map Transaction types to CreditEntry kinds.
        New design: only credit_repayment maps forward.
        Keep legacy support for credit_usage for historical rows.
        """
        if t_type == "credit_repayment":
            return "repayment"
        if t_type == "credit_usage":  # legacy support
            return "usage"
        return None

    def _sync_credit_entry_after_save(self, *, old_type: str | None) -> None:
        """
        Ensure there's a CreditEntry row mirroring this Transaction when applicable.
        If the type changed from a credit-mapped type to a non-mapped type, remove the entry.
        """
        CreditEntry = apps.get_model("credit", "CreditEntry")
        CreditAccount = apps.get_model("credit", "CreditAccount")

        new_kind = self._creditentry_kind(self.transaction_type)
        old_kind = self._creditentry_kind(old_type)

        existing = CreditEntry.objects.filter(transaction=self).first()

        if new_kind:
            ca, _ = CreditAccount.objects.get_or_create(client_id=self.client_id)
            if existing:
                fields = []
                if existing.kind != new_kind:
                    existing.kind = new_kind
                    fields.append("kind")
                new_amt = _r2(self.amount)
                if existing.amount != new_amt:
                    existing.amount = new_amt
                    fields.append("amount")
                if existing.credit_account_id != ca.id:
                    existing.credit_account = ca
                    fields.append("credit_account")
                if existing.invoice_id != (self.invoice_id or None):
                    existing.invoice_id = self.invoice_id or None
                    fields.append("invoice")
                if existing.posted_at != self.created_at:
                    existing.posted_at = self.created_at
                    fields.append("posted_at")
                if fields:
                    existing.save(update_fields=list(set(fields)))
            else:
                CreditEntry.objects.create(
                    credit_account=ca,
                    kind=new_kind,
                    amount=_r2(self.amount),
                    posted_at=self.created_at,
                    invoice_id=self.invoice_id or None,
                    transaction=self,
                    note=(self.note or f"Auto from transaction {self.id}"),
                )
        else:
            # No longer a credit-mapped transaction -> remove any existing entry
            if existing:
                existing.delete()

    def _delete_credit_entry(self) -> None:
        CreditEntry = apps.get_model("credit", "CreditEntry")
        CreditEntry.objects.filter(transaction=self).delete()

    # ----- internals -----
    def _current_db_values(self) -> tuple[str | None, Decimal | None, int | None]:
        """
        Returns (old_type, old_amount, old_client_id) for delta computations.
        (None, None, None) if the row doesn't exist yet.
        """
        if not self.pk:
            return None, None, None
        try:
            db_self = (
                Transaction.objects
                .only("transaction_type", "amount", "client_id")
                .get(pk=self.pk)
            )
            return db_self.transaction_type, db_self.amount, db_self.client_id
        except Transaction.DoesNotExist:
            return None, None, None

    # ----- persistence with dual ledgers + credit ledger via CreditEntry -----
    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        old_type, old_amount, old_client_id = self._current_db_values()

        # Signed movements for business/client ledgers
        new_signed = BusinessBalance.signed_amount(self.transaction_type, self.amount)
        old_signed = BusinessBalance.signed_amount(old_type, old_amount)
        business_delta = new_signed - old_signed

        # Lock the global ledger
        bb = BusinessBalance.get_seshibo(for_update=True)
        current_business = (
            BusinessBalance.objects
            .filter(pk=bb.pk)
            .values_list("balance", flat=True)
            .get()
        )

        # Determine which client rows to lock and how their deltas change
        target_client_id = self.client_id
        client_changed = (old_client_id is not None and old_client_id != target_client_id)

        # Lock client ledgers in a stable order to avoid deadlocks
        lock_ids: list[int] = []
        if old_client_id and client_changed:
            lock_ids = sorted({old_client_id, target_client_id})
        elif target_client_id:
            lock_ids = [target_client_id]

        client_rows: dict[int, ClientBalance] = {}
        for cid in lock_ids:
            client_rows[cid] = ClientBalance.get_for_client(cid, for_update=True)

        # Read current balances
        new_cb = client_rows.get(target_client_id) or ClientBalance.get_for_client(target_client_id, for_update=True)
        current_client_new = (
            ClientBalance.objects
            .filter(pk=new_cb.pk)
            .values_list("balance", flat=True)
            .get()
        )

        # Compute per-client post snapshot for THIS row
        if old_client_id is None:
            # fresh create
            post_client = current_client_new + new_signed
        elif client_changed:
            # moved between clients
            post_client = current_client_new + new_signed
        else:
            # same client, update type/amount
            post_client = current_client_new + (new_signed - old_signed)

        # Set snapshots for this row
        self.balance = current_business + business_delta
        self.client_balance = post_client

        # Persist the row
        super().save(*args, **kwargs)

        # Apply deltas to ledgers
        if business_delta != 0:
            bb.apply_delta(business_delta)

        if old_client_id is None:
            # create -> add to new client
            new_cb.apply_delta(new_signed)
        elif client_changed:
            # move -> remove from old client, add to new client
            old_cb = client_rows[old_client_id]
            if old_signed != 0:
                old_cb.apply_delta(-old_signed)
            if new_signed != 0:
                new_cb.apply_delta(new_signed)
        else:
            # same client -> apply the diff
            client_delta = new_signed - old_signed
            if client_delta != 0:
                new_cb.apply_delta(client_delta)

        # Keep linked invoice’s **deposit** in sync (cash-only)
        if self.invoice_id:
            self._sync_invoice_totals_and_status()

        # ---- Credit ledger via CreditEntry (append-only) ----
        # New flow: only credit_repayment maps forward.
        # Legacy: credit_usage still mirrored for historical rows.
        self._sync_credit_entry_after_save(old_type=old_type)

    @transaction.atomic
    def delete(self, *args, **kwargs) -> None:
        # compute reverse deltas BEFORE delete
        cur_signed = BusinessBalance.signed_amount(self.transaction_type, self.amount)

        # Lock ledgers
        bb = BusinessBalance.get_seshibo(for_update=True)
        cb = ClientBalance.get_for_client(self.client_id, for_update=True)

        inv_id, client_id = self.invoice_id, self.client_id

        # Also remove the linked CreditEntry (signals will reverse credit_used for legacy)
        self._delete_credit_entry()

        # delete row
        super().delete(*args, **kwargs)

        # reverse business/client ledgers
        if cur_signed != 0:
            bb.apply_delta(-cur_signed)
            cb.apply_delta(-cur_signed)

        # resync invoice if needed
        if inv_id:
            inv = apps.get_model("invoices", "Invoice").objects.filter(pk=inv_id).first()
            if inv:
                self._sync_invoice_totals_and_status(inv_override=inv)

    # ----- invoice sync helper -----
    def _sync_invoice_totals_and_status(self, *, inv_override=None) -> None:
        Invoice = apps.get_model("invoices", "Invoice")
        inv = inv_override or Invoice.objects.filter(pk=self.invoice_id).first()
        if not inv:
            return

        total_in = (
            inv.transactions
            .filter(transaction_type__in=INVOICE_PAYMENT_TYPES)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
        )
        inv.deposit_paid = _r2(total_in)

        today = localdate()
        if inv.deposit_paid >= inv.amount_due:
            new_status = "paid"
        elif inv.due_date and today > inv.due_date and inv.deposit_paid < inv.amount_due:
            new_status = "overdue"
        elif inv.deposit_paid > 0:
            new_status = "partial"
        else:
            new_status = "unpaid"

        transition_to_paid = (new_status == "paid" and inv.status != "paid")
        transition_from_paid = (new_status != "paid" and inv.status == "paid")

        if new_status != inv.status:
            inv.status = new_status

        inv.save(update_fields=["deposit_paid", "status", "updated_at"])

        # === If invoice just became PAID, enqueue the order into AM/PM picking ===
        PickingBatch = apps.get_model("deliveries", "PickingBatch")
        if transition_to_paid and inv.order_id:
            event_dt = getattr(inv.order, "created_at", None) or now()
            local_dt = timezone.localtime(event_dt)
            wave = "AM" if local_dt.hour < 12 else "PM"
            service_date = local_dt.date()

            batch, _ = PickingBatch.get_or_create_wave(service_date=service_date, wave=wave)
            batch.add_order(inv.order)  # idempotent per (batch, order_item)

        # === Option A: realize or remove credit artefacts here ===
        # Always sync the credit side to match current deposit state
        # (ensure_credit_after_deposit will create/update/remove credit_issue txn + usage entry).
        try:
            inv.ensure_credit_after_deposit()
        except Exception:
            # fail-open: do not block transactions on credit realization hiccups
            pass
