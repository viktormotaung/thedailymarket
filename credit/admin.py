from decimal import Decimal
from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Sum, Case, When, F, DecimalField
from django.urls import reverse
from django.utils.html import format_html
from django.utils.timezone import now

from .models import (
    CreditAccount,
    CreditLog,
    Funder,
    FunderMovement,
    FunderClientWeek,
    FunderWeekSummary,
    FunderAllocation,
    FunderMember,            # NEW: bring memberships into admin
)

# CreditEntry may or may not exist / may have different field names
try:
    from .models import CreditEntry  # type: ignore
    HAS_CREDIT_ENTRY = True
except Exception:
    CreditEntry = None  # type: ignore
    HAS_CREDIT_ENTRY = False


# -----------------------------
# Helper: model-introspection
# -----------------------------
def model_has_field(model, field_name: str) -> bool:
    try:
        return any(f.name == field_name for f in model._meta.get_fields())
    except Exception:
        return False


# -----------------------------
# Inlines
# -----------------------------

if HAS_CREDIT_ENTRY:

    class CreditEntryInline(admin.TabularInline):
        """
        Read-only inline to show the credit ledger rows under a CreditAccount.
        Compatible with slightly different field names.
        """
        model = CreditEntry
        extra = 0
        can_delete = False
        ordering = ("-posted_at", "-id")

        fields = (
            "posted_at",
            "entry_type_display",
            "amount",
            "invoice_link",
            "reference_display",
            "note",
        )
        readonly_fields = fields

        # ---- Display helpers (must live on the Inline class) ----
        def entry_type_display(self, obj):
            # prefer obj.kind (new schema); fall back to entry_type/type
            val = getattr(obj, "kind", None)
            if val is None:
                val = getattr(obj, "entry_type", None)
            if val is None:
                val = getattr(obj, "type", None)
            # Try Django's get_FOO_display if present
            disp = None
            for attr in ("get_kind_display", "get_entry_type_display"):
                try:
                    disp = getattr(obj, attr)()
                    break
                except Exception:
                    pass
            return disp or val or "—"
        entry_type_display.short_description = "Entry type"

        def reference_display(self, obj):
            val = getattr(obj, "reference", None) or getattr(obj, "ref", None)
            return val or "—"
        reference_display.short_description = "Reference"

        def invoice_link(self, obj):
            inv_id = getattr(obj, "invoice_id", None)
            if inv_id:
                try:
                    url = reverse("admin:invoices_invoice_change", args=[inv_id])
                    return format_html('<a href="{}">Invoice #{}</a>', url, inv_id)
                except Exception:
                    return f"Invoice #{inv_id}"
            return "—"
        invoice_link.short_description = "Invoice"


class CreditLogInline(admin.TabularInline):
    model = CreditLog
    extra = 0
    can_delete = False
    ordering = ("-created_at",)
    fields = (
        "created_at",
        "authorised_by",
        "previous_limit",
        "new_limit",
        "amount_changed",
        "note",
    )
    readonly_fields = fields


# -----------------------------
# CreditAccount
# -----------------------------

@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    # Base list_display
    base_list_display = [
        "client",
        "client_number",
        "payment_term_label",          # NEW
        "credit_deposit_pct_display",  # NEW
        "credit_limit",
        "credit_used",
        "credit_available_display",
        "last_activity",
        "updated_at",
    ]
    # If a 'funder' FK exists on CreditAccount, show it
    if model_has_field(CreditAccount, "funder"):
        base_list_display.insert(1, "funder")
    list_display = tuple(base_list_display)

    list_select_related = ("client",)
    search_fields = (
        "client__name",
        "client__organization",
        "client__client_number",
    )
    ordering = ("client__name",)

    # Some nice filters for your new fields
    list_filter = (
        *(("funder",) if model_has_field(CreditAccount, "funder") else ()),
        "payment_term",
        "credit_deposit_pct",
    )

    # Respect optional funder FK
    raw_id_fields = ("client",) + (("funder",) if model_has_field(CreditAccount, "funder") else ())

    # Attach inlines that actually exist
    inlines = [CreditLogInline]
    if HAS_CREDIT_ENTRY:
        inlines = [CreditEntryInline, CreditLogInline]

    readonly_fields = (
        "credit_used",
        "credit_available_display",
        "created_at",
        "updated_at",
    )

    # Fields shown on the form (inject 'funder' if present)
    base_fields = [
        "client",
        "payment_term",          # NEW
        "credit_deposit_pct",    # NEW
        "credit_limit",
        "credit_used",
        "credit_available_display",
        "created_at",
        "updated_at",
    ]
    if model_has_field(CreditAccount, "funder"):
        base_fields.insert(1, "funder")
    fields = tuple(base_fields)

    actions = ["recompute_credit_used_from_ledger"]

    # ---- display helpers ----

    def client_number(self, obj):
        return getattr(obj.client, "client_number", "")
    client_number.short_description = "Client #"
    client_number.admin_order_field = "client__client_number"

    def payment_term_label(self, obj):
        # uses get_FOO_display from the choices on the model
        try:
            return obj.get_payment_term_display()
        except Exception:
            return getattr(obj, "payment_term", "—")
    payment_term_label.short_description = "Payment term"

    def credit_deposit_pct_display(self, obj):
        try:
            return f"{obj.credit_deposit_pct:.0f}%"
        except Exception:
            return "—"
    credit_deposit_pct_display.short_description = "Deposit %"

    def credit_available_display(self, obj):
        return obj.credit_available
    credit_available_display.short_description = "Credit available (R)"

    def last_activity(self, obj):
        if HAS_CREDIT_ENTRY:
            last = obj.entries.order_by("-posted_at", "-id").first()
            return getattr(last, "posted_at", None) if last else None
        return obj.updated_at
    last_activity.short_description = "Last activity"
    last_activity.admin_order_field = "updated_at"

    def save_model(self, request, obj, form, change):
        previous_limit = None

        if change:
            try:
                old = CreditAccount.objects.get(pk=obj.pk)
                previous_limit = old.credit_limit
            except CreditAccount.DoesNotExist:
                old = None
        else:
            old = None

        # If limit changed, do not set directly; go via ledger
        if change and old and previous_limit != form.cleaned_data.get("credit_limit"):
            new_limit = form.cleaned_data["credit_limit"]

            # save other fields, keep stored credit_limit as-is (previous)
            obj.credit_limit = previous_limit
            super().save_model(request, obj, form, change)

            obj.set_limit(
                new_limit,
                authorised_by=request.user if request.user.is_authenticated else None,
                note=f"Limit changed in admin by {request.user}.",
            )
            return

        super().save_model(request, obj, form, change)

    @admin.action(description="Recompute credit used from ledger")
    def recompute_credit_used_from_ledger(self, request, queryset):
        """
        Safely recompute credit_used as:
            sum(USAGE) - sum(REPAYMENT) + sum(ADJUSTMENT) - sum(WRITEOFF)
        based on CreditEntry rows (if present).
        """
        if not HAS_CREDIT_ENTRY:
            self.message_user(request, "No ledger model found; nothing to recompute.")
            return

        for acc in queryset:
            agg = acc.entries.aggregate(total=Sum(
                Case(
                    When(kind=getattr(CreditEntry, "USAGE", "usage"), then=F("amount")),
                    When(kind=getattr(CreditEntry, "REPAYMENT", "repayment"), then=-F("amount")),
                    When(kind=getattr(CreditEntry, "ADJUSTMENT", "adjustment"), then=F("amount")),
                    When(kind=getattr(CreditEntry, "WRITEOFF", "writeoff"), then=-F("amount")),
                    default=Decimal("0.00"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            ))
            new_used = agg["total"] or Decimal("0.00")
            if new_used != (acc.credit_used or Decimal("0.00")):
                acc.credit_used = new_used
                acc.save(update_fields=["credit_used", "updated_at"])


# -----------------------------
# CreditEntry (standalone admin)
# -----------------------------

if HAS_CREDIT_ENTRY:

    class CreditEntryAdmin(admin.ModelAdmin):
        list_display = (
            "posted_at",
            "client",
            "entry_type_display",
            "amount",
            "invoice_link",
            "reference_display",
        )
        list_select_related = ("credit_account__client", "invoice")

        # list_filter must reference real fields; add 'kind' if present
        if model_has_field(CreditEntry, "kind"):
            list_filter = ("kind", "posted_at")
        else:
            # fallback to whatever exists
            list_filter = tuple(f for f in ("entry_type", "posted_at") if model_has_field(CreditEntry, f))

        date_hierarchy = "posted_at" if model_has_field(CreditEntry, "posted_at") else None
        search_fields = (
            "credit_account__client__name",
            "credit_account__client__organization",
            "credit_account__client__client_number",
            "reference",
            "note",
            "invoice__id",
        )
        ordering = ("-posted_at", "-id") if model_has_field(CreditEntry, "posted_at") else ("-id",)
        raw_id_fields = ("credit_account", "invoice")

        fields = (
            "credit_account",
            *(("kind",) if model_has_field(CreditEntry, "kind") else ()),
            "entry_type_display",
            "amount",
            "invoice",
            "reference_display",
            "note",
            *(("posted_at",) if model_has_field(CreditEntry, "posted_at") else ()),
        )
        readonly_fields = ("entry_type_display", "reference_display") + (
            ("posted_at",) if "posted_at" in fields else ()
        )

        # ---- Display helpers (must live on the Admin class) ----
        def client(self, obj):
            return obj.credit_account.client
        client.short_description = "Client"
        client.admin_order_field = "credit_account__client__name"

        def entry_type_display(self, obj):
            val = getattr(obj, "kind", None)
            if val is None:
                val = getattr(obj, "entry_type", None)
            if val is None:
                val = getattr(obj, "type", None)
            disp = None
            for attr in ("get_kind_display", "get_entry_type_display"):
                try:
                    disp = getattr(obj, attr)()
                    break
                except Exception:
                    pass
            return disp or val or "—"
        entry_type_display.short_description = "Entry type"

        def reference_display(self, obj):
            val = getattr(obj, "reference", None) or getattr(obj, "ref", None)
            return val or "—"
        reference_display.short_description = "Reference"

        def invoice_link(self, obj):
            inv_id = getattr(obj, "invoice_id", None)
            if inv_id:
                try:
                    url = reverse("admin:invoices_invoice_change", args=[inv_id])
                    return format_html('<a href="{}">Invoice #{}</a>', url, inv_id)
                except Exception:
                    return f"Invoice #{inv_id}"
            return "—"
        invoice_link.short_description = "Invoice"

    admin.site.register(CreditEntry, CreditEntryAdmin)


# -----------------------------
# CreditLog
# -----------------------------

@admin.register(CreditLog)
class CreditLogAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "amount_changed",
        "previous_limit",
        "new_limit",
        "authorised_by",
        "created_at",
    )
    list_select_related = ("credit_account__client", "authorised_by")
    search_fields = (
        "credit_account__client__name",
        "credit_account__client__organization",
        "authorised_by__username",
        "authorised_by__first_name",
        "authorised_by__last_name",
    )
    ordering = ("-created_at",)

    readonly_fields = (
        "credit_account",
        "previous_limit",
        "new_limit",
        "amount_changed",
        "authorised_by",
        "created_at",
    )
    fields = (
        "credit_account",
        "previous_limit",
        "new_limit",
        "amount_changed",
        "note",
        "authorised_by",
        "created_at",
    )

    def client(self, obj):
        return obj.credit_account.client
    client.short_description = "Client"
    client.admin_order_field = "credit_account__client__name"


# -----------------------------
# Funder Allocation
# -----------------------------

class FunderAllocationInline(admin.TabularInline):
    model = FunderAllocation
    extra = 0
    ordering = ("client__name",)
    autocomplete_fields = ("client",)
    fields = ("client", "amount", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FunderAllocation)
class FunderAllocationAdmin(admin.ModelAdmin):
    list_display = ("funder", "client", "amount",
                    "funder_balance", "funder_total_allocated",
                    "funder_allocatable_balance", "updated_at")
    list_filter = ("funder",)
    search_fields = ("funder__name", "client__name", "client__organization")
    ordering = ("funder__name", "client__name")
    autocomplete_fields = ("funder", "client")
    readonly_fields = ("created_at", "updated_at")
    fields = ("funder", "client", "amount", "created_at", "updated_at")

    def funder_balance(self, obj):
        return getattr(obj.funder, "balance", Decimal("0.00"))
    funder_balance.short_description = "Funder balance (R)"

    def funder_total_allocated(self, obj):
        try:
            return obj.funder.total_allocated()
        except Exception:
            total = (
                FunderAllocation.objects
                .filter(funder=obj.funder)
                .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
            )
            return total
    funder_total_allocated.short_description = "Allocated total (R)"

    def funder_allocatable_balance(self, obj):
        try:
            return obj.funder.allocatable_balance
        except Exception:
            bal = getattr(obj.funder, "balance", Decimal("0.00"))
            alloc = (
                FunderAllocation.objects
                .filter(funder=obj.funder)
                .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
            )
            return (bal or Decimal("0.00")) - (alloc or Decimal("0.00"))
    funder_allocatable_balance.short_description = "Allocatable (R)"

    def save_model(self, request, obj, form, change):
        # ensure model-level clean() runs so we block over-allocation
        obj.full_clean()
        return super().save_model(request, obj, form, change)


# -----------------------------
# FunderMember (NEW)
# -----------------------------

class FunderMemberInline(admin.TabularInline):
    model = FunderMember
    extra = 0
    ordering = ("-is_active", "user__username")
    autocomplete_fields = ("user",)
    fields = ("user", "role", "is_active", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FunderMember)
class FunderMemberAdmin(admin.ModelAdmin):
    list_display = ("funder", "user", "role_badge", "is_active", "updated_at")
    list_filter = ("role", "is_active", "funder")
    search_fields = (
        "funder__name",
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
    )
    ordering = ("funder__name", "user__username")
    autocomplete_fields = ("funder", "user")
    fields = ("funder", "user", "role", "is_active", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")

    def role_badge(self, obj):
        color = {
            "OWNER": "#0b5c39",
            "MANAGER": "#0d6efd",
            "VIEWER": "#6c757d",
        }.get(obj.role, "#6c757d")
        return format_html(
            '<span style="padding:2px 8px;border-radius:12px;background:{};color:#fff;font-size:12px;">{}</span>',
            color, obj.get_role_display()
        )
    role_badge.short_description = "Role"


# -----------------------------
# Funder Admin
# -----------------------------

class FunderMovementInline(admin.TabularInline):
    """
    Lightweight inline to show money moving in/out of the funder balance.
    """
    model = FunderMovement
    extra = 0
    ordering = ("-created_at", "-id")
    fields = ("created_at", "kind", "amount", "reference", "note")
    readonly_fields = ("created_at",)


class FunderClientWeekInline(admin.TabularInline):
    """
    Read-only weekly per-client utilization (capped at 100% of client's limit).
    """
    model = FunderClientWeek
    extra = 0
    can_delete = False
    ordering = ("-week_start", "client__name")
    fields = (
        "week_start",
        "client",
        "credit_limit_at_start",
        "usage_sum",
        "visible_utilization",
        "updated_at",
    )
    readonly_fields = fields


class FunderWeekSummaryInline(admin.TabularInline):
    """
    Read-only weekly roll-up for the funder.
    """
    model = FunderWeekSummary
    extra = 0
    can_delete = False
    ordering = ("-week_start",)
    fields = (
        "week_start",
        "visible_utilization_total",
        "weekly_rate_pct_snapshot",
        "weekly_return",
        "updated_at",
    )
    readonly_fields = fields


@admin.register(Funder)
class FunderAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "weekly_rate_pct",
        "balance",
        "total_allocated_display",
        "allocatable_balance_display",
        "updated_at",
    )
    search_fields = ("name",)
    ordering = ("name",)
    inlines = [
        FunderMemberInline,          # NEW: manage memberships on Funder page
        FunderAllocationInline,
        FunderMovementInline,
        FunderWeekSummaryInline,
        FunderClientWeekInline,
    ]

    actions = ["rebuild_current_week", "rebuild_last_week"]

    def total_allocated_display(self, obj):
        try:
            return obj.total_allocated()
        except Exception:
            total = (
                FunderAllocation.objects
                .filter(funder=obj)
                .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
            )
            return total
    total_allocated_display.short_description = "Allocated total (R)"

    def allocatable_balance_display(self, obj):
        try:
            return obj.allocatable_balance
        except Exception:
            bal = getattr(obj, "balance", Decimal("0.00"))
            alloc = (
                FunderAllocation.objects
                .filter(funder=obj)
                .aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
            )
            return (bal or Decimal("0.00")) - (alloc or Decimal("0.00"))
    allocatable_balance_display.short_description = "Allocatable (R)"

    @admin.action(description="Rebuild current ISO week summaries (Mon..Sun)")
    def rebuild_current_week(self, request, queryset):
        today = now().date()
        monday = today - timedelta(days=today.weekday())
        self._rebuild_week(request, queryset, monday)

    @admin.action(description="Rebuild last ISO week summaries (previous Mon..Sun)")
    def rebuild_last_week(self, request, queryset):
        today = now().date()
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        self._rebuild_week(request, queryset, last_monday)

    def _rebuild_week(self, request, queryset, monday):
        count = 0
        for funder in queryset:
            funder.rebuild_week(monday)
            count += 1
        self.message_user(
            request,
            f"Rebuilt week starting {monday.isoformat()} for {count} funder(s).",
            level=messages.SUCCESS,
        )


# -----------------------------
# FunderMovement Admin
# -----------------------------

@admin.register(FunderMovement)
class FunderMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "funder", "kind", "amount", "reference")
    list_filter = ("kind", "created_at", "funder")
    date_hierarchy = "created_at"
    search_fields = ("reference", "note", "funder__name")
    ordering = ("-created_at", "-id")
    raw_id_fields = ("funder",)
    fields = ("funder", "kind", "amount", "reference", "note", "created_at")
    readonly_fields = ("created_at",)


# -----------------------------
# FunderClientWeek Admin
# -----------------------------

@admin.register(FunderClientWeek)
class FunderClientWeekAdmin(admin.ModelAdmin):
    list_display = (
        "week_start",
        "funder",
        "client",
        "credit_limit_at_start",
        "usage_sum",
        "visible_utilization",
        "updated_at",
    )
    list_filter = ("funder", "week_start")
    date_hierarchy = "week_start"
    search_fields = ("funder__name", "client__name", "client__organization")
    ordering = ("-week_start", "funder__name", "client__name")
    raw_id_fields = ("funder", "client")
    readonly_fields = ("created_at", "updated_at")
    fields = (
        "funder",
        "client",
        "week_start",
        "credit_limit_at_start",
        "usage_sum",
        "visible_utilization",
        "created_at",
        "updated_at",
    )


# -----------------------------
# FunderWeekSummary Admin
# -----------------------------

@admin.register(FunderWeekSummary)
class FunderWeekSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "week_start",
        "funder",
        "visible_utilization_total",
        "weekly_rate_pct_snapshot",
        "weekly_return",
        "updated_at",
    )
    list_filter = ("funder", "week_start")
    date_hierarchy = "week_start"
    search_fields = ("funder__name",)
    ordering = ("-week_start", "funder__name")
    raw_id_fields = ("funder",)
    readonly_fields = ("created_at", "updated_at")
    fields = (
        "funder",
        "week_start",
        "visible_utilization_total",
        "weekly_rate_pct_snapshot",
        "weekly_return",
        "created_at",
        "updated_at",
    )

    actions = ["refresh_totals_from_client_rows"]

    @admin.action(description="Refresh selected summaries from client rows")
    def refresh_totals_from_client_rows(self, request, queryset):
        for summary in queryset:
            summary.refresh_from_client_weeks()
        self.message_user(request, f"Refreshed {queryset.count()} summary(ies).", level=messages.SUCCESS)
