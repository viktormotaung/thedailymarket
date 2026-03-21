# credit/admin.py
from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from django.contrib.auth import get_user_model
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
from django import forms
from django.contrib.auth import get_user_model

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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from clients.models import Client

        if db_field.name == "client":
            print("\n===== CLIENT FK DEBUG =====")

            qs = Client.objects.using("dummy").all()

            print("Queryset DB:", qs.db)
            print("Clients:", list(qs.values_list("id", "name"))[:5])

            kwargs["queryset"] = qs

        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
        "is_dummy",
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

    list_filter = (
        "is_dummy",  # 👈 ADD THIS
    )

    fieldsets = (
        (None, {
            "fields": ("name", "is_dummy", "weekly_rate_pct"),
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
class FunderMemberAdminForm(forms.ModelForm):
    class Meta:
        model = FunderMember
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        User = get_user_model()

        # 🔥 FORCE USER FIELD TO USE DEFAULT DB
        self.fields["user"].queryset = User.objects.using("default").all()

    def clean_user(self):
        user = self.cleaned_data.get("user")

        # 🔥 RE-FETCH USER FROM DEFAULT DB (CRITICAL FIX)
        if user:
            User = get_user_model()
            return User.objects.using("default").get(pk=user.pk)

        return user
    
@admin.register(FunderMember)
class FunderMemberAdmin(admin.ModelAdmin):

    form = FunderMemberAdminForm  # 🔥 ADD THIS LINE

    list_display = ("funder", "user", "role", "is_active")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if db_field.name == "user":
            print("\n===== FK FIELD DEBUG =====")
            print("Setting queryset to DEFAULT DB")

            qs = User.objects.using("default").all()

            print("Queryset DB:", qs.db)
            print("Users in queryset:", list(qs.values_list("id", "username"))[:5])

            kwargs["queryset"] = qs
            kwargs["to_field_name"] = "id"

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)

        if db_field.name == "user":
            print("\n===== DBFIELD DEBUG =====")
            print("Original queryset DB:", field.queryset.db)

            field.queryset = field.queryset.using("default")

            print("UPDATED queryset DB:", field.queryset.db)

        return field

    def save_model(self, request, obj, form, change):
        print("\n===== SAVE DEBUG =====")
        print("Selected user:", obj.user)
        print("User ID:", obj.user.id)

        super().save_model(request, obj, form, change)

# ============================================================
# FUNDER ALLOCATION ADMIN
# ============================================================

@admin.register(FunderAllocation)
class FunderAllocationAdmin(admin.ModelAdmin):
    list_display = ("funder", "client", "amount")
    search_fields = ("funder__name", "client__name")
    autocomplete_fields = ("funder", "client")
    readonly_fields = ("created_at", "updated_at")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from clients.models import Client

        if db_field.name == "client":
            kwargs["queryset"] = Client.objects.using("dummy").all()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
        if request.path.startswith("/dummy-admin/"):
            return False
        return super().has_add_permission(request)

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
        "raw_weekly_usage",
        "visible_utilization_total",
        "weekly_rate_pct_snapshot",
        "weekly_return",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "funder",
        "week_start",
    )

    search_fields = (
        "funder__name",
    )

    readonly_fields = (
        "funder",
        "week_start",
        "raw_weekly_usage",
        "visible_utilization_total",
        "weekly_rate_pct_snapshot",
        "weekly_return",
        "created_at",
        "updated_at",
    )

    ordering = ("-week_start", "-created_at")

    date_hierarchy = "week_start"
