# invoices/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import Invoice


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "id", "client_name", "order_id", "invoice_date", "due_date",
        "order_total_display", "deposit_required", "deposit_paid",
        "credit_used", "status_colored", "is_fully_paid"
    ]
    list_filter = ["status", "invoice_date", "due_date", "client__account_type"]
    search_fields = ["client__name", "order__id", "client__organization"]
    readonly_fields = [
        "created_at", "updated_at", "order_total_inc", "deposit_required",
        "credit_used", "amount_due"
    ]
    fieldsets = (
        (None, {
            "fields": (
                "client", "order", "status", "invoice_date", "due_date"
            )
        }),
        ("Financial Summary", {
            "fields": (
                "order_total_inc", "deposit_required", "deposit_paid",
                "credit_used", "amount_due"
            )
        }),
        ("Metadata", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        })
    )
    ordering = ["-invoice_date", "-id"]
    date_hierarchy = "invoice_date"

    def client_name(self, obj):
        return obj.client.name
    client_name.short_description = "Client"

    def order_id(self, obj):
        return f"#{obj.order.id}" if obj.order else "—"
    order_id.short_description = "Order"

    def status_colored(self, obj):
        color = {
            "paid": "green",
            "partial": "orange",
            "unpaid": "red",
            "overdue": "darkred",
        }.get(obj.status, "black")
        return format_html(
            '<b style="color: {};">{}</b>', color, obj.get_status_display()
        )
    status_colored.short_description = "Status"

    def order_total_display(self, obj):
        return f"R{obj.order_total_inc:.2f}"
    order_total_display.short_description = "Order Total"
