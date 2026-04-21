from django.contrib import admin
from .models import Payment


from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):

    # ===============================
    # LIST VIEW (TABLE)
    # ===============================
    list_display = (
        "reference",
        "amount",
        "status",
        "payment_method",
        "institution_name",
        "client",
        "invoice",
        "created_at",
        "paid_at",
    )

    list_filter = (
        "status",
        "payment_method",
        "provider",
        "created_at",
    )

    search_fields = (
        "reference",
        "oneapi_payment_id",
        "oneapi_transaction_id",
        "client__client_number",
        "client__name",
        "institution_name",
    )

    ordering = ("-created_at",)

    list_per_page = 25

    # ===============================
    # DETAIL VIEW (FORM)
    # ===============================
    readonly_fields = (
        "reference",
        "amount",
        "provider",
        "oneapi_payment_id",
        "oneapi_transaction_id",
        "idempotency_key",
        "created_at",
        "paid_at",
    )

    fieldsets = (
        ("Payment Info", {
            "fields": (
                "reference",
                "amount",
                "status",
                "provider",
                "payment_method",
            )
        }),

        ("Institution", {
            "fields": (
                "institution_name",
                "institution_id",
            )
        }),

        ("Relations", {
            "fields": (
                "client",
                "invoice",
                "created_by",
            )
        }),

        ("OneAPI Details", {
            "fields": (
                "oneapi_payment_id",
                "oneapi_transaction_id",
                "idempotency_key",
            )
        }),

        ("Timestamps", {
            "fields": (
                "created_at",
                "paid_at",
            )
        }),
    )

    # ===============================
    # ACTIONS (VERY USEFUL FOR TESTING)
    # ===============================
    actions = ["mark_as_success", "mark_as_failed"]

    def mark_as_success(self, request, queryset):
        for payment in queryset:
            if payment.status != "success":
                payment.status = "success"
                payment.save()
        self.message_user(request, "Selected payments marked as SUCCESS.")

    mark_as_success.short_description = "Mark selected payments as SUCCESS"

    def mark_as_failed(self, request, queryset):
        queryset.update(status="failed")
        self.message_user(request, "Selected payments marked as FAILED.")

    mark_as_failed.short_description = "Mark selected payments as FAILED"