# invoices/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Invoice,
    DailyOverdueSummary,
    CommissionEntry,
    MonthlyCommission,
    CommissionAdjustment,
)


# ==============================
# Invoice admin
# ==============================
@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "client_name",
        "order_id",
        "invoice_date",
        "due_date",
        "order_total_display",
        "deposit_required",
        "deposit_paid",
        "credit_used",
        "status_colored",
        "is_fully_paid",
    ]
    list_filter = [
        "status",
        "invoice_date",
        "due_date",
        "client__account_type",
    ]
    search_fields = [
        "client__name",          # from Client model
        "client__client_number", # your auto-generated CL####
        "order__id",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "order_total_inc",
        "deposit_required",
        "credit_used",
        "amount_due",
    ]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "client",
                    "order",
                    "status",
                    "invoice_date",
                    "due_date",
                    "paid_date",
                )
            },
        ),
        (
            "Financial Summary",
            {
                "fields": (
                    "order_total_inc",
                    "deposit_required",
                    "deposit_paid",
                    "credit_used",
                    "amount_due",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
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


# ==============================
# DailyOverdueSummary admin
# ==============================
@admin.register(DailyOverdueSummary)
class DailyOverdueSummaryAdmin(admin.ModelAdmin):
    list_display = ("run_date", "new_overdue", "total_overdue", "created_at")
    date_hierarchy = "run_date"
    ordering = ["-run_date"]


# ==============================
# CommissionEntry admin
# ==============================
@admin.register(CommissionEntry)
class CommissionEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "invoice_id",
        "rep",
        "supervisor",
        "cost_total",
        "rep_rate",
        "rep_amount",
        "supervisor_rate",
        "supervisor_amount",
        "is_new_business",
        "created_at",
    )
    list_filter = ("is_new_business", "rep", "supervisor")
    search_fields = (
        "invoice__id",
        "rep__username",
        "rep__first_name",
        "rep__last_name",
        "supervisor__username",
        "supervisor__first_name",
        "supervisor__last_name",
    )
    readonly_fields = ("created_at",)


# ==============================
# MonthlyCommission admin
# ==============================
@admin.register(MonthlyCommission)
class MonthlyCommissionAdmin(admin.ModelAdmin):
    list_display = (
        "rep",
        "year",
        "month",
        "recurring_sales_total",
        "recurring_commission_total",
        "new_business_total",
        "new_business_commission",
        "weekly_average",
        "commission_rate_pct",
        "monthly_cash_bonus",
        "total_payout",
        "paid",
        "paid_on",
    )
    list_filter = ("year", "month", "paid")
    search_fields = (
        "rep__username",
        "rep__first_name",
        "rep__last_name",
    )
    date_hierarchy = "paid_on"
    readonly_fields = ("created_at", "updated_at")


# ==============================
# CommissionAdjustment admin
# ==============================
@admin.register(CommissionAdjustment)
class CommissionAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("id", "monthly_commission", "amount", "created_at")
    search_fields = (
        "monthly_commission__rep__username",
        "monthly_commission__rep__first_name",
        "monthly_commission__rep__last_name",
    )
    readonly_fields = ("created_at",)
