# invoices/admin.py
from django.urls import path
from django.contrib import admin, messages
from django.utils.html import format_html
from django.db import transaction
from django.shortcuts import render, redirect

from .models import (
    Invoice,
    DailyOverdueSummary,
    CommissionEntry,
    MonthlyCommission,
    CommissionAdjustment,
    UtilizationSegment,
    MonthlyTarget,
    MonthlyTargetAllocation,
)
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

# =========================================================
# EMAIL FUNCTION
# =========================================================
def send_invoice_email(invoice, recipient_email, recipient_name):
    subject = f"Invoice INV-{invoice.id} · The Daily Market"

    html_content = render_to_string(
        "emails/invoice_email.html",
        {
            "invoice": invoice,
            "client": invoice.client,
            "recipient_name": recipient_name,
            "support_email": getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        },
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body="Please view your invoice.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
    )

    email.attach_alternative(html_content, "text/html")
    email.send()


# =========================================================
# Invoice admin
# =========================================================
@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):

    # --------------------------------------------------
    # MULTI DB
    # --------------------------------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.using("dummy") if request.path.startswith("/dummy-admin") else qs.using("default")

    def _db(self, request):
        return "dummy" if request.path.startswith("/dummy-admin") else "default"

    # --------------------------------------------------
    # DISPLAY
    # --------------------------------------------------
    list_display = [
        "id",
        "client_name",
        "order_id",
        "segment",
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
        "segment",
        "invoice_date",
        "due_date",
        "client__account_type",
    ]

    search_fields = [
        "client__name",
        "client__client_number",
        "order__id",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "order_total_inc",
        "deposit_required",
        "credit_used",
        "amount_due",
        "client",
        "order",
    ]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "client",
                    "order",
                    "segment",
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

    # --------------------------------------------------
    # SAVE
    # --------------------------------------------------
    def save_model(self, request, obj, form, change):
        with transaction.atomic(using=self._db(request)):
            obj.save(using=self._db(request))

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------
    def client_name(self, obj):
        return obj.client.name

    def order_id(self, obj):
        return f"#{obj.order.id}" if obj.order else "—"

    def status_colored(self, obj):
        color = {
            "paid": "green",
            "partial": "orange",
            "unpaid": "red",
            "overdue": "darkred",
        }.get(obj.status, "black")

        return format_html(
            '<b style="color: {};">{}</b>',
            color,
            obj.get_status_display()
        )

    def order_total_display(self, obj):
        return f"R{obj.order_total_inc:.2f}"

    # --------------------------------------------------
    # DELETE
    # --------------------------------------------------
    def delete_model(self, request, obj):
        obj.delete(using=self._db(request))

    # ==================================================
    # 🔥 CUSTOM SEND EMAIL VIEW (WITH INPUT FORM)
    # ==================================================
    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<int:invoice_id>/send-email/",
                self.admin_site.admin_view(self.send_invoice_view),
                name="invoice-send-email",
            ),
        ]

        return custom_urls + urls

    def send_invoice_view(self, request, invoice_id):
        db = self._db(request)

        invoice = Invoice.objects.using(db).select_related("client", "order").get(pk=invoice_id)

        if request.method == "POST":
            email = request.POST.get("email")
            name = request.POST.get("name")

            if not email or not name:
                messages.error(request, "Both name and email are required.")
                return redirect(request.path)

            try:
                send_invoice_email(invoice, email, name)

                self.message_user(
                    request,
                    f"Invoice sent to {email}",
                    level=messages.SUCCESS
                )

                return redirect(f"../../{invoice.id}/change/")

            except Exception as e:
                self.message_user(
                    request,
                    f"Failed to send: {str(e)}",
                    level=messages.ERROR
                )

                return redirect(request.path)

        return render(
            request,
            "admin/invoices/send_invoice.html",
            {
                "invoice": invoice,
            },
        )
    
# =========================================================
# Utilization Segment Admin
# =========================================================
@admin.register(UtilizationSegment)
class UtilizationSegmentAdmin(admin.ModelAdmin):
    list_display = ("name", "cycle_days", "is_active")
    list_filter = ("is_active",)
    ordering = ("cycle_days",)


# =========================================================
# Monthly Target Allocation Inline
# =========================================================
class MonthlyTargetAllocationInline(admin.TabularInline):
    model = MonthlyTargetAllocation
    extra = 1


# =========================================================
# Monthly Target Admin
# =========================================================
@admin.register(MonthlyTarget)
class MonthlyTargetAdmin(admin.ModelAdmin):
    list_display = (
        "area",
        "month",
        "year",
        "quarter",
        "monthly_target",
        "created_at",
    )

    list_filter = ("year", "quarter", "area")
    search_fields = ("area",)
    ordering = ("-year", "month")

    inlines = [MonthlyTargetAllocationInline]


# =========================================================
# DailyOverdueSummary admin
# =========================================================
@admin.register(DailyOverdueSummary)
class DailyOverdueSummaryAdmin(admin.ModelAdmin):
    list_display = ("run_date", "new_overdue", "total_overdue", "created_at")
    date_hierarchy = "run_date"
    ordering = ["-run_date"]


# =========================================================
# CommissionEntry admin
# =========================================================
@admin.register(CommissionEntry)
class CommissionEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "invoice_id",
        "segment",
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

    list_filter = (
        "is_new_business",
        "rep",
        "supervisor",
        "invoice__segment",
    )

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

    def invoice_id(self, obj):
        return obj.invoice.id
    invoice_id.short_description = "Invoice"

    def segment(self, obj):
        return obj.invoice.segment
    segment.short_description = "Segment"


# =========================================================
# MonthlyCommission admin
# =========================================================
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


# =========================================================
# CommissionAdjustment admin
# =========================================================
@admin.register(CommissionAdjustment)
class CommissionAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("id", "monthly_commission", "amount", "created_at")

    search_fields = (
        "monthly_commission__rep__username",
        "monthly_commission__rep__first_name",
        "monthly_commission__rep__last_name",
    )

    readonly_fields = ("created_at",)