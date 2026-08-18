from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .forms import SalesRepProfileForm
from .models import (
    StaffProfile,
    CustomerProfile,
    SalesRepProfile,
    SalesRole,
    DriverProfile,
    SalesOperator,
    Department,
)

User = get_user_model()


# ----------------------------
# StaffProfile admin form
# ----------------------------
class StaffProfileAdminForm(forms.ModelForm):
    new_auth_code = forms.CharField(
        label="New authorisation code",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the current code.",
    )
    confirm_auth_code = forms.CharField(
        label="Confirm code",
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta:
        model = StaffProfile
        fields = (
            "user",
            "job_title",
            "phone",
            "notes",
            "status",
            "primary_department",
            "departments",
            "can_access_sales",
        )

    def clean(self):
        cleaned = super().clean()
        c1 = cleaned.get("new_auth_code")
        c2 = cleaned.get("confirm_auth_code")

        if c1 or c2:
            if c1 != c2:
                raise forms.ValidationError("Authorisation codes do not match.")

        return cleaned

    def save(self, commit=True):
        obj: StaffProfile = super().save(commit=False)

        if self.cleaned_data.get("new_auth_code"):
            obj.set_auth_code(self.cleaned_data["new_auth_code"], save=False)

        if commit:
            obj.save()

        return obj


# ----------------------------
# StaffProfile admin
# ----------------------------
@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    form = StaffProfileAdminForm

    list_display = (
        "user_full_name",
        "user_username",
        "job_title",
        "primary_department",
        "can_access_sales",
        "phone",
        "updated_at",
        "status",
        "online_now",
        "last_seen_at",
        "user_last_login",
    )

    list_filter = (
        "status",
        "primary_department",
        "departments",
        "can_access_sales",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "job_title",
        "phone",
        "status",
    )

    autocomplete_fields = ("user",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "job_title",
                    "phone",
                    "primary_department",
                    "departments",
                    "can_access_sales",
                    "notes",
                    "status",
                )
            },
        ),
        (
            "Authorisation code",
            {
                "fields": (
                    "new_auth_code",
                    "confirm_auth_code",
                    "auth_code_hash",
                )
            },
        ),
        ("Presence", {"fields": ("last_seen_at", "user_last_login_display")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    readonly_fields = (
        "auth_code_hash",
        "last_seen_at",
        "user_last_login_display",
        "created_at",
        "updated_at",
    )

    def user_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.get_username()

    user_full_name.short_description = "Name"

    def user_username(self, obj):
        return obj.user.get_username()

    user_username.short_description = "Username"

    @admin.display(boolean=True, description="Online", ordering="last_seen_at")
    def online_now(self, obj: StaffProfile):
        return obj.is_online

    @admin.display(description="Last login", ordering="user__last_login")
    def user_last_login(self, obj: StaffProfile):
        return getattr(obj.user, "last_login", None)

    def user_last_login_display(self, obj: StaffProfile):
        return getattr(obj.user, "last_login", None)

    user_last_login_display.short_description = "Last login"
    user_last_login_display.admin_order_field = "user__last_login"


# ----------------------------
# SalesOperator admin
# ----------------------------
@admin.register(SalesOperator)
class SalesOperatorAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "territory",
        "owner_1",
        "owner_2",
        "responsible_user_1",
        "responsible_user_2",
        "base_commission_pct",
        "bonus_commission_pct",
        "is_active",
        "created_at",
    )

    list_filter = (
        "territory",
        "is_active",
        "account_type",
    )

    search_fields = (
        "name",
        "owner_1__username",
        "owner_1__first_name",
        "owner_1__last_name",
        "owner_2__username",
        "owner_2__first_name",
        "owner_2__last_name",
        "responsible_user_1__username",
        "responsible_user_1__first_name",
        "responsible_user_1__last_name",
        "responsible_user_2__username",
        "responsible_user_2__first_name",
        "responsible_user_2__last_name",
        "suburb",
        "city",
        "province",
        "bank_name",
        "account_holder",
    )

    autocomplete_fields = (
        "owner_1",
        "owner_2",
        "responsible_user_1",
        "responsible_user_2",
    )

    readonly_fields = (
        "full_address_display",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Operator Details",
            {
                "fields": (
                    "name",
                    "territory",
                    "is_active",
                    "notes",
                )
            },
        ),
        (
            "Ownership",
            {
                "fields": (
                    "owner_1",
                    "owner_2",
                )
            },
        ),
        (
            "Responsible Internal Users",
            {
                "fields": (
                    "responsible_user_1",
                    "responsible_user_2",
                )
            },
        ),
        (
            "Commission",
            {
                "fields": (
                    "base_commission_pct",
                    "bonus_commission_pct",
                )
            },
        ),
        (
            "Address",
            {
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "suburb",
                    "city",
                    "province",
                    "postal_code",
                    "full_address_display",
                )
            },
        ),
        (
            "Banking Details",
            {
                "fields": (
                    "bank_name",
                    "account_holder",
                    "account_number",
                    "branch_code",
                    "account_type",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Full address")
    def full_address_display(self, obj):
        return obj.full_address


# ----------------------------
# SalesRepProfile admin form
# ----------------------------
class SalesRepProfileAdminForm(SalesRepProfileForm):
    new_auth_code = forms.CharField(
        label="New authorisation code",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the current code.",
    )

    confirm_auth_code = forms.CharField(
        label="Confirm code",
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta:
        model = SalesRepProfile
        fields = (
            "user",
            "staff_profile",
            "sales_operator",
            "region",
            "territory",
            "supervisor",
            "department",
            "roles",
            "notes",
            "status",
            "base_commission_pct",
            "bonus_commission_pct",
        )

    def clean(self):
        cleaned = super().clean()

        code1 = cleaned.get("new_auth_code")
        code2 = cleaned.get("confirm_auth_code")

        if code1 or code2:
            if code1 != code2:
                raise forms.ValidationError(
                    "Authorisation codes do not match."
                )

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)

        if self.cleaned_data.get("new_auth_code"):
            obj.set_auth_code(
                self.cleaned_data["new_auth_code"],
                save=False,
            )

        if commit:
            obj.save()
            self.save_m2m()

        return obj
    
# ----------------------------
# SalesRepProfile admin
# ----------------------------
@admin.register(SalesRepProfile)
class SalesRepProfileAdmin(admin.ModelAdmin):
    form = SalesRepProfileAdminForm

    list_display = (
        "user_full_name",
        "user_username",
        "region",
        "territory",
        "sales_operator",
        "department",
        "supervisor",
        "base_commission_pct",
        "bonus_commission_pct",
        "status",
        "updated_at",
        "online_now",
        "last_seen_at",
        "user_last_login",
    )

    list_filter = (
        "status",
        "department",
        "region",
        "territory",
        "sales_operator",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "region__name",
        "territory__name",
        "sales_operator__name",
        "department__name",
        "department__code",
        "status",
    )

    autocomplete_fields = (
        "user",
        "staff_profile",
        "sales_operator",
    )

    filter_horizontal = ("roles",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "staff_profile",
                    "sales_operator",
                    "region",
                    "territory",
                    "supervisor",
                    "department",
                    "roles",
                    "notes",
                    "status",
                )
            },
        ),
        (
            "Commission",
            {
                "fields": (
                    "base_commission_pct",
                    "bonus_commission_pct",
                )
            },
        ),
        (
            "Authorisation code",
            {
                "fields": (
                    "new_auth_code",
                    "confirm_auth_code",
                    "auth_code_hash",
                )
            },
        ),
        ("Presence", {"fields": ("last_seen_at", "user_last_login_display")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    readonly_fields = (
        "department",
        "auth_code_hash",
        "last_seen_at",
        "user_last_login_display",
        "created_at",
        "updated_at",
    )

    def user_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.get_username()

    user_full_name.short_description = "Name"

    def user_username(self, obj):
        return obj.user.get_username()

    user_username.short_description = "Username"

    @admin.display(boolean=True, description="Online", ordering="last_seen_at")
    def online_now(self, obj: SalesRepProfile):
        return obj.is_online

    @admin.display(description="Last login", ordering="user__last_login")
    def user_last_login(self, obj: SalesRepProfile):
        return getattr(obj.user, "last_login", None)

    def user_last_login_display(self, obj: SalesRepProfile):
        return getattr(obj.user, "last_login", None)

    user_last_login_display.short_description = "Last login"
    user_last_login_display.admin_order_field = "user__last_login"


# ----------------------------
# Inlines on the User admin
# ----------------------------
class StaffProfileInline(admin.StackedInline):
    model = StaffProfile
    can_delete = False
    extra = 0

    fields = (
        "job_title",
        "phone",
        "primary_department",
        "departments",
        "can_access_sales",
        "notes",
        "status",
        "last_seen_at",
        "auth_code_hash",
    )

    readonly_fields = (
        "auth_code_hash",
        "last_seen_at",
    )


@admin.register(SalesRole)
class SalesRoleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
    )

    search_fields = (
        "name",
        "code",
    )

    ordering = (
        "name",
    )


class SalesRepProfileInline(admin.StackedInline):
    model = SalesRepProfile
    fk_name = "user"
    can_delete = False
    extra = 0

    fields = (
        "staff_profile",
        "sales_operator",
        "region",
        "territory",
        "base_commission_pct",
        "bonus_commission_pct",
        "roles",
        "supervisor",
        "department",
        "status",
        "notes",
        "last_seen_at",
        "auth_code_hash",
    )

    readonly_fields = (
        "department",
        "auth_code_hash",
        "last_seen_at",
    )

    autocomplete_fields = (
        "staff_profile",
        "sales_operator",
    )

    filter_horizontal = ("roles",)


# Re-register User with the inlines
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = (
        StaffProfileInline,
        SalesRepProfileInline,
    )


# ----------------------------
# CustomerProfile admin
# ----------------------------
@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "profile_type",
        "client",
        "phone",
        "updated_at",
        "status",
        "online_now",
        "last_seen_at",
        "user_last_login",
    )

    list_filter = (
        "profile_type",
        "status",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "phone",
        "status",
    )

    autocomplete_fields = (
        "user",
        "client",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "profile_type",
                    "status",
                    "client",
                    "consumer",
                )
            },
        ),
        (
            "Contact",
            {
                "fields": (
                    "display_name",
                    "phone",
                )
            },
        ),
        ("Presence", {"fields": ("last_seen_at", "user_last_login_display")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    readonly_fields = (
        "last_seen_at",
        "user_last_login_display",
        "created_at",
        "updated_at",
    )

    @admin.display(boolean=True, description="Online", ordering="last_seen_at")
    def online_now(self, obj: CustomerProfile):
        return obj.is_online

    @admin.display(description="Last login", ordering="user__last_login")
    def user_last_login(self, obj: CustomerProfile):
        return getattr(obj.user, "last_login", None)

    def user_last_login_display(self, obj: CustomerProfile):
        return getattr(obj.user, "last_login", None)

    user_last_login_display.short_description = "Last login"
    user_last_login_display.admin_order_field = "user__last_login"


# ----------------------------
# DriverProfile admin
# ----------------------------
@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "staff_profile",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
    )

    autocomplete_fields = (
        "user",
        "staff_profile",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Driver",
            {
                "fields": (
                    "user",
                    "staff_profile",
                    "status",
                )
            },
        ),
        (
            "Notes",
            {
                "fields": (
                    "notes",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )





@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "code",
        "manager",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
    )

    filter_horizontal = (
        "members",
    )