# credit/admin.py
from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html
from django.contrib.auth import get_user_model
from credit.models import bypass_ledger
from clients.models import Client
from .models import (
    Funder,
    FunderMember,
    FunderAllocation,
    FunderMovement,
    CreditAccount,
    CreditLog,
    CreditEntry,
    FunderWeekSummary,
    FunderProfit,
)
from django import forms
from django.db import transaction
from django.core.exceptions import ValidationError
from django.urls import path
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.contrib import messages

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


class FunderProfitInline(admin.TabularInline):
    model = FunderProfit
    extra = 0
    fields = (
        "period_start",
        "period_end",
        "source_type",
        "amount",
        "status",
        "processed_at",
    )
    readonly_fields = ("created_at", "updated_at")
    show_change_link = True

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
        "profit_mode",
        "profit_frequency",
    )
    search_fields = ("name",)
    ordering = ("name",)
    readonly_fields = ("balance", "created_at", "updated_at")

    inlines = (
        FunderMemberInline,
        FunderAllocationInline,
        FunderProfitInline,
    )

    list_filter = (
        "is_dummy",
        "profit_mode",
        "profit_frequency",
    )

    fieldsets = (
        (None, {
            "fields": (
                "name",
                "is_dummy",
                "weekly_rate_pct",
                "profit_mode",
                "profit_frequency",
            ),
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

    # --------------------------------------------------
    # 🔥 DETECT DB
    # --------------------------------------------------
    def _db(self, request):
        return "dummy" if request.path.startswith("/dummy-admin") else "default"

    # --------------------------------------------------
    # 🔥 FIX FK QUERYSETS
    # --------------------------------------------------
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        db = self._db(request)

        if db_field.name == "client":
            from clients.models import Client
            kwargs["queryset"] = Client.objects.using(db).all()

        if db_field.name == "funder":
            from credit.models import Funder
            kwargs["queryset"] = Funder.objects.using(db).all()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # --------------------------------------------------
    # 🔥 CRITICAL FIX: SAVE USING CORRECT DB
    # --------------------------------------------------
    def save_model(self, request, obj, form, change):
        db = self._db(request)
        obj.save(using=db)

    # --------------------------------------------------
    # 🔥 CRITICAL FIX: FORM VALIDATION DB
    # --------------------------------------------------
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        db = self._db(request)

        # Force queryset again at form level
        if "client" in form.base_fields:
            from clients.models import Client
            form.base_fields["client"].queryset = Client.objects.using(db).all()

        if "funder" in form.base_fields:
            from credit.models import Funder
            form.base_fields["funder"].queryset = Funder.objects.using(db).all()

        return form


# ============================================================
# FUNDER MOVEMENT ADMIN
# ============================================================

@admin.register(FunderMovement)
class FunderMovementAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "funder",
        "kind",
        "amount",
        "reference",
        "linked_profits_count",
    )

    list_filter = ("kind", "created_at", "funder")

    search_fields = ("reference", "note", "funder__name")

    autocomplete_fields = (
        "funder",
        "profit_links",
    )

    readonly_fields = ("created_at",)

    fieldsets = (
        (None, {
            "fields": (
                "funder",
                "kind",
                "amount",
                "reference",
                "note",
                "profit_links",
            ),
        }),
        ("System", {
            "fields": ("created_at",),
        }),
    )

    # 🔒 Lock profit_links after creation
    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)

        if obj:
            ro.append("profit_links")

        return ro

    # Display helper
    def linked_profits_count(self, obj):
        return obj.profit_links.count()

    linked_profits_count.short_description = "Linked Profits"


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

    # --------------------------------------------------
    # 🔒 LOCK CLIENT AFTER CREATION (CRITICAL FIX)
    # --------------------------------------------------
    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)

        # If editing existing record → lock client
        if obj:
            ro.append("client")

        return ro

    # --------------------------------------------------
    # 🔥 MULTI-DB SAFE FK HANDLING
    # --------------------------------------------------
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)

        # Detect admin DB
        if request.path.startswith("/dummy-admin/"):
            db = "dummy"
        else:
            db = "default"

        # Apply correct DB queryset
        if db_field.name == "client":
            from clients.models import Client
            field.queryset = Client.objects.using(db).all()

        if db_field.name == "funder":
            from credit.models import Funder
            field.queryset = Funder.objects.using(db).all()

        return field

    # --------------------------------------------------
    # DISPLAY HELPERS
    # --------------------------------------------------
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

    # 🔥 ONLY lock critical ledger fields (allow posted_at to be edited)
    readonly_fields = (
        "balance",
        "created_at",
        "created_by",
    )

    # --------------------------------------------------
    # PERMISSIONS
    # --------------------------------------------------
    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    # --------------------------------------------------
    # 🔥 CORRECT SAVE (FIXED)
    # --------------------------------------------------
    def save_model(self, request, obj, form, change):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        if not obj.pk:
            obj.created_by = request.user

        # ✅ Let Django handle normal save flow
        super().save_model(request, obj, form, change)

        # ✅ Ensure object is saved in correct DB
        if obj._state.db != db:
            obj.save(using=db)

    # --------------------------------------------------
    # SAFE DELETE (BYPASS LEDGER)
    # --------------------------------------------------
    def delete_model(self, request, obj):
        with bypass_ledger():
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with bypass_ledger():
            super().delete_queryset(request, queryset)

    # --------------------------------------------------
    # OPTIONAL: RESTRICT EDITING TO SUPERUSERS ONLY
    # --------------------------------------------------
    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return super().has_change_permission(request, obj)

    # --------------------------------------------------
    # OPTIONAL: WARNING MESSAGE WHEN EDITING posted_at
    # --------------------------------------------------
    def change_view(self, request, object_id, form_url="", extra_context=None):
        from django.contrib import messages

        messages.warning(
            request,
            "⚠ Changing 'posted_at' will affect historical weekly summaries."
        )

        return super().change_view(request, object_id, form_url, extra_context)
    

    
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


@admin.register(FunderProfit)
class FunderProfitAdmin(admin.ModelAdmin):
    list_display = (
        "funder",
        "period_start",
        "period_end",
        "source_type",
        "amount",
        "status",
        "processed_at",
        "created_at",
    )

    list_filter = (
        "status",
        "source_type",
        "funder",
        "period_start",
    )

    search_fields = (
        "funder__name",
        "reference",
        "note",
    )

    autocomplete_fields = (
        "funder",
        "week_summary",
    )

    readonly_fields = (
        "funder",
        "week_summary",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (None, {
            "fields": (
                "funder",
                "week_summary",
                "source_type",
                "period_start",
                "period_end",
                "amount",
                "status",
            ),
        }),
        ("Processing", {
            "fields": (
                "processed_at",
                "reference",
                "note",
            ),
        }),
        ("System", {
            "fields": (
                "created_at",
                "updated_at",
            ),
        }),
    )

    ordering = ("-period_start", "-created_at")

    change_list_template = "admin/credit/funderprofit/change_list.html"

    actions = [
        "reinvest_selected_profits",
        "payout_selected_profits",
    ]

    # -------------------------------------------------
    # DB DETECTION
    # -------------------------------------------------
    def _db(self, request):
        return "dummy" if request.path.startswith("/dummy-admin") else "default"

    # -------------------------------------------------
    # CUSTOM URLS
    # -------------------------------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "process-monthly/",
                self.admin_site.admin_view(self.process_monthly_view),
                name="credit_funderprofit_process_monthly",
            ),
            path(
                "process-weekly/",
                self.admin_site.admin_view(self.process_weekly_view),
                name="credit_funderprofit_process_weekly",
            ),
        ]
        return custom_urls + urls

    # -------------------------------------------------
    # CHANGE LIST EXTRA CONTEXT
    # -------------------------------------------------
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_profit_buttons"] = True
        return super().changelist_view(request, extra_context=extra_context)

    # -------------------------------------------------
    # TOP BUTTON HANDLERS
    # -------------------------------------------------
    def process_monthly_view(self, request):
        db = self._db(request)

        result = FunderProfit.process_monthly_reinvestment(using=db)

        self.message_user(
            request,
            (
                f"Monthly reinvestment complete | "
                f"DB: {db} | "
                f"Funders processed: {result['funders_processed']} | "
                f"Profits processed: {result['profits_processed']} | "
                f"Total reinvested: R{result['total_reinvested']}"
            ),
            level=messages.SUCCESS,
        )

        return HttpResponseRedirect("../")

    def process_weekly_view(self, request):
        db = self._db(request)

        # 🔥 Replace this once your weekly function is added
        self.message_user(
            request,
            f"Weekly processing function not yet connected. DB detected: {db}",
            level=messages.WARNING,
        )

        return HttpResponseRedirect("../")

    # -------------------------------------------------
    # ACTIONS
    # -------------------------------------------------
    @admin.action(description="Reinvest selected profits")
    def reinvest_selected_profits(self, request, queryset):
        success = 0

        for profit in queryset:
            if profit.status != "PENDING":
                continue

            db = profit._state.db or "default"

            with transaction.atomic(using=db):
                profit.funder.apply_delta(profit.amount)

                profit.status = "REINVESTED"
                profit.processed_at = now()
                profit.save(
                    using=db,
                    update_fields=["status", "processed_at", "updated_at"]
                )

                success += 1

        self.message_user(
            request,
            f"{success} profit(s) reinvested successfully."
        )

    @admin.action(description="Mark selected profits as paid out")
    def payout_selected_profits(self, request, queryset):
        success = 0

        for profit in queryset:
            if profit.status != "PENDING":
                continue

            db = profit._state.db or "default"

            with transaction.atomic(using=db):
                profit.status = "PAID_OUT"
                profit.processed_at = now()
                profit.save(
                    using=db,
                    update_fields=["status", "processed_at", "updated_at"]
                )

                success += 1

        self.message_user(
            request,
            f"{success} profit(s) marked as paid out."
        )

