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
    CREDIT_TYPES = {"payment", "credit_issue", "refund"}
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

    def __str__(self) -> str:
        return f"{self.client} · {self.transaction_type} · R{self.amount:.2f}"

    # ----- convenience flags -----
    @property
    def is_credit(self) -> bool:
        return self.transaction_type in {"payment", "credit_issue", "credit_repayment", "refund"}

    @property
    def is_debit(self) -> bool:
        return self.transaction_type in {"invoice", "credit_usage", "adjustment"}

    # ------------------------------------------------------------------
    # CreditEntry mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _creditentry_kind(t_type):
        if t_type == "credit_repayment":
            return "repayment"
        if t_type == "credit_usage":  # legacy
            return "usage"
        return None

    def _sync_credit_entry_after_save(self, *, old_type):
        CreditEntry = apps.get_model("credit", "CreditEntry")
        CreditAccount = apps.get_model("credit", "CreditAccount")

        kind = self._creditentry_kind(self.transaction_type)
        if not kind:
            return

        ca, _ = CreditAccount.objects.get_or_create(client_id=self.client_id)

        ce = CreditEntry.objects.create(
            credit_account=ca,
            kind=kind,
            amount=_r2(self.amount),
            posted_at=self.created_at,
            invoice_id=self.invoice_id or None,
            transaction=self,  # TEMPORARY link
            note=self.note or f"Auto from transaction {self.id}",
        )

        # 🔑 If this is a credit repayment, detach and remove the transaction
        if self.transaction_type == "credit_repayment":
            ce.transaction = None
            ce.save(update_fields=["transaction"])

            

    # ------------------------------------------------------------------
    # INTERNAL delete used only for credit repayments
    # ------------------------------------------------------------------
    def _delete_self_silently(self):
        """
        Delete the transaction WITHOUT:
          - reversing balances
          - deleting CreditEntry
        Used ONLY for credit_repayment.
        """
        super(Transaction, self).delete()

    def _delete_credit_entry(self) -> None:
        CreditEntry = apps.get_model("credit", "CreditEntry")
        CreditEntry.objects.filter(transaction=self).delete()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _current_db_values(self):
        if not self.pk:
            return None, None, None
        try:
            row = Transaction.objects.only("transaction_type", "amount", "client_id").get(pk=self.pk)
            return row.transaction_type, row.amount, row.client_id
        except Transaction.DoesNotExist:
            return None, None, None

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    @transaction.atomic
    def save(self, *args, **kwargs):
        old_type, old_amount, old_client_id = self._current_db_values()

        # 🔒 Credit repayments do NOT affect balances
        if self.transaction_type == "credit_repayment":
            super().save(*args, **kwargs)
            self._sync_credit_entry_after_save(old_type=old_type)
            return

        # ---------------- Normal flow unchanged ----------------
        new_signed = BusinessBalance.signed_amount(self.transaction_type, self.amount)
        old_signed = BusinessBalance.signed_amount(old_type, old_amount)
        business_delta = new_signed - old_signed

        bb = BusinessBalance.get_seshibo(for_update=True)
        cb = ClientBalance.get_for_client(self.client_id, for_update=True)

        self.balance = bb.balance + business_delta
        self.client_balance = cb.balance + new_signed

        super().save(*args, **kwargs)

        if business_delta:
            bb.apply_delta(business_delta)
            cb.apply_delta(new_signed)

        if self.invoice_id:
            self._sync_invoice_totals_and_status()

        self._sync_credit_entry_after_save(old_type=old_type)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    @transaction.atomic
    def delete(self, *args, **kwargs):
        # Credit repayment transactions should never reach here
        if self.transaction_type == "credit_repayment":
            return

        cur_signed = BusinessBalance.signed_amount(self.transaction_type, self.amount)

        bb = BusinessBalance.get_seshibo(for_update=True)
        cb = ClientBalance.get_for_client(self.client_id, for_update=True)

        super().delete(*args, **kwargs)

        if cur_signed:
            bb.apply_delta(-cur_signed)
            cb.apply_delta(-cur_signed)

        if self.invoice_id:
            self._sync_invoice_totals_and_status()

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

