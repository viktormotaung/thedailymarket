from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "amount",
        "status",
        "provider",
        "client",
        "invoice",
        "ozow_transaction_id",
        "created_at",
        "paid_at",
    )

    list_filter = (
        "status",
        "provider",
        "created_at",
        "paid_at",
    )

    search_fields = (
        "reference",
        "ozow_transaction_id",
        "client__name",
        "invoice__invoice_number",
    )

    readonly_fields = (
        "reference",
        "ozow_transaction_id",
        "created_at",
        "paid_at",
    )

    ordering = ("-created_at",)

    fieldsets = (
        ("Payment Details", {
            "fields": (
                "reference",
                "amount",
                "status",
                "provider",
            )
        }),
        ("Relations", {
            "fields": (
                "client",
                "invoice",
                "created_by",
            )
        }),
        ("Ozow Details", {
            "fields": (
                "ozow_transaction_id",
            )
        }),
        ("Timestamps", {
            "fields": (
                "created_at",
                "paid_at",
            )
        }),
    )