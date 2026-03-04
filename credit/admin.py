# credit/admin.py
from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from credit.models import bypass_ledger
from .models import (
    Funder,
    FunderMember,
    FunderAllocation,
    FunderMovement,
    CreditAccount,
    CreditLog,
    CreditEntry,
    FunderWeekSummary,
)

# ============================================================
# INLINES
# ============================================================

class FunderMemberInline(admin.TabularInline):
    model = FunderMember
    extra = 0
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


class FunderAllocationInline(admin.TabularInline):
    model = FunderAllocation
    extra = 0
    autocomplete_fields = ("client",)
    readonly_fields = ("created_at", "updated_at")


class CreditEntryInline(admin.TabularInline):
    model = CreditEntry
    extra = 0
    fields = ("posted_at", "kind", "amount", "balance")
    readonly_fields = fields
    ordering = ("-posted_at",)
    can_delete = False
    show_change_link = True


class CreditLogInline(admin.TabularInline):
    model = CreditLog
    extra = 0
    readonly_fields = (
        "previous_limit",
        "new_limit",
        "amount_changed",
        "authorised_by",
        "created_at",
    )
    can_delete = False


# ============================================================
# FUNDER ADMIN
# ============================================================

@admin.register(Funder)
class FunderAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "balance",
        "total_allocated_display",
        "allocatable_balance",
        "weekly_rate_pct",
    )
    search_fields = ("name",)
    ordering = ("name",)
    readonly_fields = ("balance", "created_at", "updated_at")

    inlines = (
        FunderMemberInline,
        FunderAllocationInline,
    )

    fieldsets = (
        (None, {
            "fields": ("name", "weekly_rate_pct"),
        }),
        ("Financials (System Controlled)", {
            "fields": ("balance",),
        }),
        ("System", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def total_allocated_display(self, obj):
        return obj.total_allocated()
    total_allocated_display.short_description = "Total Allocated"


# ============================================================
# FUNDER MEMBER ADMIN
# ============================================================

@admin.register(FunderMember)
class FunderMemberAdmin(admin.ModelAdmin):
    list_display = ("funder", "user", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("funder__name", "user__username", "user__email")
    autocomplete_fields = ("funder", "user")


# ============================================================
# FUNDER ALLOCATION ADMIN
# ============================================================

@admin.register(FunderAllocation)
class FunderAllocationAdmin(admin.ModelAdmin):
    list_display = ("funder", "client", "amount")
    search_fields = ("funder__name", "client__name")
    autocomplete_fields = ("funder", "client")
    readonly_fields = ("created_at", "updated_at")


# ============================================================
# FUNDER MOVEMENT ADMIN
# ============================================================

@admin.register(FunderMovement)
class FunderMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "funder", "kind", "amount", "reference")
    list_filter = ("kind", "created_at")
    search_fields = ("reference", "note", "funder__name")
    autocomplete_fields = ("funder",)
    readonly_fields = ("created_at",)

    fieldsets = (
        (None, {
            "fields": ("funder", "kind", "amount", "reference", "note"),
        }),
        ("System", {
            "fields": ("created_at",),
        }),
    )


# ============================================================
# CREDIT ACCOUNT ADMIN
# ============================================================

@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "funder",
        "credit_limit",
        "credit_used",
        "credit_available_display",
        "payment_term",
    )
    list_filter = ("payment_term",)
    search_fields = ("client__name",)
    autocomplete_fields = ("client", "funder")

    readonly_fields = (
        "credit_limit",
        "credit_used",
        "created_at",
        "updated_at",
    )

    inlines = (
        CreditLogInline,
        CreditEntryInline,
    )

    fieldsets = (
        (None, {
            "fields": ("client", "funder"),
        }),
        ("Terms", {
            "fields": ("payment_term", "credit_deposit_pct"),
        }),
        ("Balances (Ledger Controlled)", {
            "fields": ("credit_limit", "credit_used"),
        }),
        ("System", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    def credit_available_display(self, obj):
        return obj.credit_available
    credit_available_display.short_description = "Available Credit"


# ============================================================
# CREDIT LOG ADMIN (AUDIT ONLY)
# ============================================================

@admin.register(CreditLog)
class CreditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "credit_account",
        "previous_limit",
        "new_limit",
        "amount_changed",
        "authorised_by",
    )
    list_filter = ("created_at",)
    search_fields = ("credit_account__client__name",)
    readonly_fields = [f.name for f in CreditLog._meta.fields]


# ============================================================
# CREDIT ENTRY ADMIN (LEDGER — READ ONLY)
# ============================================================

@admin.register(CreditEntry)
class CreditEntryAdmin(admin.ModelAdmin):
    list_display = (
        "posted_at",
        "credit_account",
        "kind",
        "amount",
        "balance",
    )
    list_filter = ("kind", "posted_at")
    search_fields = (
        "reference",
        "note",
        "credit_account__client__name",
    )
    autocomplete_fields = ("credit_account", "invoice", "transaction")

    readonly_fields = [f.name for f in CreditEntry._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    
    def delete_model(self, request, obj):
        with bypass_ledger():
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with bypass_ledger():
            super().delete_queryset(request, queryset)




# ============================================================
# FUNDER WEEK SUMMARY ADMIN (REPORTING)
# ============================================================

@admin.register(FunderWeekSummary)
class FunderWeekSummaryAdmin(admin.ModelAdmin):
    list_display = (
        "week_start",
        "funder",
        "visible_utilization_total",
        "weekly_rate_pct_snapshot",
        "weekly_return",
    )
    list_filter = ("funder", "week_start")
    search_fields = ("funder__name",)
    readonly_fields = [f.name for f in FunderWeekSummary._meta.fields]

    ordering = ("-week_start",)
