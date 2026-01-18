from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import StaffProfile, CustomerProfile, SalesRepProfile, SalesRole, DriverProfile

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
        fields = ("user", "job_title", "phone", "notes", "status", "department", "can_access_sales")

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
        "department",
        "can_access_sales",
        "phone",
        "updated_at",
        "status",
        "online_now",
        "last_seen_at",
        "user_last_login",
    )
    list_filter = ("status", "department", "can_access_sales")
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
                    "department",
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
# SalesRepProfile admin form
# ----------------------------
class SalesRepProfileAdminForm(forms.ModelForm):
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
        # department + supervisor are managed elsewhere / read-only here
        fields = ("user", "staff_profile", "supervisor", "notes", "status")

    def clean(self):
        cleaned = super().clean()
        c1 = cleaned.get("new_auth_code")
        c2 = cleaned.get("confirm_auth_code")
        if c1 or c2:
            if c1 != c2:
                raise forms.ValidationError("Authorisation codes do not match.")
        return cleaned

    def save(self, commit=True):
        obj: SalesRepProfile = super().save(commit=False)
        if self.cleaned_data.get("new_auth_code"):
            obj.set_auth_code(self.cleaned_data["new_auth_code"], save=False)
        if commit:
            obj.save()
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
        "department",
        "supervisor",
        "status",
        "updated_at",
        "online_now",
        "last_seen_at",
        "user_last_login",
    )
    list_filter = ("status", "department")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "department",
        "status",
    )
    autocomplete_fields = ("user", "staff_profile", "supervisor")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "staff_profile",
                    "supervisor",
                    "department",
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
        "department",  # department is fixed as "Sales" in model, so read-only here
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
    fields = ("job_title", "phone", "department", "can_access_sales", "notes", "status", "last_seen_at", "auth_code_hash")
    readonly_fields = ("auth_code_hash", "last_seen_at")


@admin.register(SalesRole)
class SalesRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")
    ordering = ("name",)


class SalesRepProfileInline(admin.StackedInline):
    model = SalesRepProfile
    fk_name = "user"  # IMPORTANT: SalesRepProfile has two FKs to User
    can_delete = False
    extra = 0

    fields = (
        "staff_profile",
        "roles",              # ✅ NEW (multi-select)
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

    filter_horizontal = ("roles",)  # ✅ clean multi-select UI



# Re-register User with the inlines
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = (StaffProfileInline, SalesRepProfileInline)


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
    list_filter = ("profile_type", "status")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "phone",
     
        "status",
    )
    autocomplete_fields = ("client",)

    fieldsets = (
        (None, {"fields": ("user", "profile_type", "status", "client")}),
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
    readonly_fields = ("last_seen_at", "user_last_login_display", "created_at", "updated_at")

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

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Driver", {
            "fields": ("user", "staff_profile", "status"),
        }),
        ("Notes", {
            "fields": ("notes",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )
