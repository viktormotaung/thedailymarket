# transactions/admin.py
from decimal import Decimal
from django.contrib import admin, messages
from django.db import transaction as db_transaction
from django.db.models import Sum

from .models import Transaction, BusinessBalance


# -------------------
# Transaction Admin
# -------------------
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "client",
        "transaction_type",
        "amount",
        "balance",
        "invoice",
        "reference",
    )
    list_filter = ("transaction_type", "created_at")
    # date_hierarchy = "created_at"  ❌ removed
    ordering = ("-created_at",)

    search_fields = (
        "reference",
        "note",
        "client__name",
        "invoice__number",
    )
    autocomplete_fields = ("client", "invoice")

    readonly_fields = ("balance", "created_at")

    fieldsets = (
        (None, {
            "fields": (
                "client",
                "invoice",
                "transaction_type",
                "amount",
                "reference",
                "note",
            )
        }),
        ("System", {
            "fields": ("balance", "created_at"),
        }),
    )

# ------------------------
# Business Balance Admin
# ------------------------
@admin.register(BusinessBalance)
class BusinessBalanceAdmin(admin.ModelAdmin):
    list_display = ("name", "balance", "total_in", "total_out", "updated_at")
    readonly_fields = ("name", "balance", "total_in", "total_out", "updated_at")

    actions = ["rebuild_from_transactions", "recompute_transaction_snapshots"]

    # Enforce singleton and protect from deletion
    def has_add_permission(self, request):
        return not BusinessBalance.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Remove the bulk delete action just in case
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    @admin.action(description="Rebuild from Transactions (totals & balance)")
    def rebuild_from_transactions(self, request, queryset):
        """
        Recomputes total_in, total_out, and balance from ALL transactions.
        Safe even if multiple rows are selected; only the singleton row is updated.
        """
        # Allow selecting 0 or 1 row; we’ll use the singleton inside the transaction.
        credit_types = getattr(BusinessBalance, "CREDIT_TYPES",
                               {"payment", "credit_issue", "credit_repayment", "refund"})
        debit_types = getattr(BusinessBalance, "DEBIT_TYPES",
                              {"invoice", "credit_usage", "adjustment"})

        with db_transaction.atomic():
            # Sum credits
            credit_total = (
                Transaction.objects.filter(transaction_type__in=credit_types)
                .aggregate(s=Sum("amount"))["s"]
                or Decimal("0.00")
            )

            # Sum debits
            debit_total = (
                Transaction.objects.filter(transaction_type__in=debit_types)
                .aggregate(s=Sum("amount"))["s"]
                or Decimal("0.00")
            )

            bb = BusinessBalance.get_seshibo(for_update=True)
            bb.total_in = credit_total
            bb.total_out = debit_total
            bb.balance = credit_total - debit_total
            bb.save()

        self.message_user(
            request,
            f"Rebuilt Business Balance: IN={credit_total} OUT={debit_total} BAL={credit_total - debit_total}",
            level=messages.SUCCESS,
        )

    @admin.action(description="Recompute Transaction Snapshots (writes each Transaction.balance)")
    def recompute_transaction_snapshots(self, request, queryset):
        """
        Walks all transactions in chronological order and recomputes each row's
        post-transaction 'balance' snapshot from scratch, starting at 0.00.
        This is helpful after historical edits/imports.

        If your business starts with a non-zero opening balance, you can adjust
        'running' below to that opening value.
        """
        credit_types = getattr(BusinessBalance, "CREDIT_TYPES",
                               {"payment", "credit_issue", "credit_repayment", "refund"})
        debit_types = getattr(BusinessBalance, "DEBIT_TYPES",
                              {"invoice", "credit_usage", "adjustment"})

        def signed_amount(t_type, amount):
            if t_type in credit_types:
                return amount
            if t_type in debit_types:
                return -amount
            return Decimal("0.00")

        updated = 0
        with db_transaction.atomic():
            # Lock the singleton to avoid concurrent writes while we rebuild snapshots
            bb = BusinessBalance.get_seshibo(for_update=True)

            running = Decimal("0.00")  # adjust if you have an opening balance
            txns = Transaction.objects.all().order_by("created_at", "id").only(
                "id", "transaction_type", "amount"
            )

            # Update each transaction's snapshot in a single pass
            buffer = []
            for t in txns:
                running += signed_amount(t.transaction_type, t.amount)
                buffer.append(Transaction(id=t.id, balance=running))
                updated += 1

            # Bulk update in chunks for efficiency
            BATCH = 1000
            for i in range(0, len(buffer), BATCH):
                Transaction.objects.bulk_update(buffer[i:i+BATCH], ["balance"])

            # After snapshots, also refresh the BusinessBalance totals & balance
