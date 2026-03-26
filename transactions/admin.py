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
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.path.startswith("/dummy-admin"):
            return qs.using("dummy")

        return qs.using("default")
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

    def save_model(self, request, obj, form, change):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"
        obj.save(using=db)

    def delete_model(self, request, obj):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"
        obj.delete(using=db)

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
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"
        return not BusinessBalance.objects.using(db).exists()

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
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        credit_types = getattr(BusinessBalance, "CREDIT_TYPES",
                            {"payment", "credit_issue", "credit_repayment", "refund"})
        debit_types = getattr(BusinessBalance, "DEBIT_TYPES",
                            {"invoice", "credit_usage", "adjustment"})

        with db_transaction.atomic(using=db):

            credit_total = (
                Transaction.objects.using(db)
                .filter(transaction_type__in=credit_types)
                .aggregate(s=Sum("amount"))["s"]
                or Decimal("0.00")
            )

            debit_total = (
                Transaction.objects.using(db)
                .filter(transaction_type__in=debit_types)
                .aggregate(s=Sum("amount"))["s"]
                or Decimal("0.00")
            )

            bb = BusinessBalance.objects.using(db).select_for_update().first()

            bb.total_in = credit_total
            bb.total_out = debit_total
            bb.balance = credit_total - debit_total
            bb.save(using=db)

        self.message_user(
            request,
            f"Rebuilt Business Balance: IN={credit_total} OUT={debit_total} BAL={credit_total - debit_total}",
            level=messages.SUCCESS,
        )

    @admin.action(description="Recompute Transaction Snapshots")
    def recompute_transaction_snapshots(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

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

        with db_transaction.atomic(using=db):

            bb = BusinessBalance.objects.using(db).select_for_update().first()

            running = Decimal("0.00")

            txns = (
                Transaction.objects.using(db)
                .all()
                .order_by("created_at", "id")
                .only("id", "transaction_type", "amount")
            )

            buffer = []

            for t in txns:
                running += signed_amount(t.transaction_type, t.amount)
                buffer.append(Transaction(id=t.id, balance=running))
                updated += 1

            BATCH = 1000
            for i in range(0, len(buffer), BATCH):
                Transaction.objects.using(db).bulk_update(
                    buffer[i:i+BATCH], ["balance"]
                )

            # refresh BusinessBalance
            bb.total_in = sum(
                t.amount for t in txns if t.transaction_type in credit_types
            )
            bb.total_out = sum(
                t.amount for t in txns if t.transaction_type in debit_types
            )
            bb.balance = bb.total_in - bb.total_out
            bb.save(using=db)

        self.message_user(
            request,
            f"Recomputed {updated} transaction snapshots.",
            level=messages.SUCCESS,
        )

   