from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "provider",
        "status",
        "amount",
        "client",
        "invoice",
        "created_at",
        "paid_at",
    )
    list_filter = (
        "provider",
        "status",
        "created_at",
        "paid_at",
    )
    search_fields = (
        "reference",
        "client__organization",
        "client__name",
        "client__contact_person",
        "invoice__id",
        "ozow_transaction_id",
    )
    readonly_fields = (
        "reference",
        "provider",
        "amount",
        "client",
        "invoice",
        "created_by",
        "created_at",
        "paid_at",
        "ozow_transaction_id",
        "idempotency_key",
    )
    ordering = ("-created_at",)

    fieldsets = (
        (
            "Payment Info",
            {
                "fields": (
                    "reference",
                    "provider",
                    "status",
                    "amount",
                )
            },
        ),
        (
            "Related Records",
            {
                "fields": (
                    "client",
                    "invoice",
                    "created_by",
                )
            },
        ),
        (
            "Gateway Details",
            {
                "fields": (
                    "ozow_transaction_id",
                    "idempotency_key",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "paid_at",
                )
            },
        ),
    )