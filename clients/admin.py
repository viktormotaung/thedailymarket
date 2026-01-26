# clients/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Client,
    ClientCompliance,
    ClientComplianceDocument,
    Prospect,
    ProspectUpdate,
)

# ============================================================
# CLIENT
# ============================================================

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    # ---------------------------
    # List view
    # ---------------------------
    list_display = (
        "client_number",
        "display_name",
        "client_type",
        "price_type",
        "status",
        "account_type",
        "credit_status",
        "city",
        "delivery_city",
        "has_geo",
        "account_manager",
        "last_order_at",
        "created_at",
    )

    list_filter = (
        "status",
        "client_type",
        "price_type",
        "account_type",
        "credit_status",
        "province",
        "delivery_province",
        "account_manager",
        ("categories", admin.RelatedOnlyFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
        ("last_order_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "client_number",
        "name",
        "organization",
        "contact_person",
        "email",
        "phone",
        "whatsapp",
        "vat_number",
        "company_reg_number",
        "address_line1",
        "suburb",
        "city",
        "delivery_address_line1",
        "delivery_suburb",
        "delivery_city",
    )

    ordering = ("name",)
    list_select_related = ("account_manager",)
    list_per_page = 50
    save_on_top = True

    # ---------------------------
    # Forms
    # ---------------------------
    readonly_fields = (
        "client_number",
        "created_at",
        "updated_at",
        "last_order_at",
        "maps_link",
    )

    autocomplete_fields = ("account_manager", "funder")
    filter_horizontal = ("categories",)

    fieldsets = (
        ("Account", {
            "fields": (
                ("client_number", "status"),
                ("client_type", "client_size_tier"),
                ("price_type",),
                ("account_type", "credit_status"),
                ("account_manager", "funder"),
            )
        }),
        ("Identity", {
            "fields": (
                "name",
                "organization",
                "contact_person",
                ("email", "phone", "whatsapp"),
            )
        }),
        ("Billing Address", {
            "fields": (
                "address_line1",
                "address_line2",
                ("suburb", "city"),
                ("province", "postal_code"),
                "country",
            )
        }),
        ("Delivery Address", {
            "fields": (
                "delivery_address_line1",
                "delivery_address_line2",
                ("delivery_suburb", "delivery_city"),
                ("delivery_province", "delivery_postal_code"),
                "delivery_country",
                ("delivery_lat", "delivery_lng"),
                "maps_link",
            )
        }),
        ("Compliance", {
            "fields": ("vat_number", "company_reg_number"),
            "classes": ("collapse",),
        }),
        ("Categories & Spend", {
            "fields": ("categories", "estimated_weekly_spend"),
        }),
        ("Notes & Meta", {
            "fields": ("notes", "last_order_at", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    # ---------------------------
    # Helpers
    # ---------------------------
    @admin.display(description="Name / Org")
    def display_name(self, obj: Client):
        return obj.organization or obj.name

    @admin.display(boolean=True, description="Geo?")
    def has_geo(self, obj: Client):
        return obj.has_delivery_geo

    @admin.display(description="Map")
    def maps_link(self, obj: Client):
        url = obj.google_maps_link()
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Open map</a>',
            url
        )


# ============================================================
# CLIENT COMPLIANCE
# ============================================================

class ClientComplianceDocumentInline(admin.TabularInline):
    model = ClientComplianceDocument
    extra = 0
    fields = (
        "document_type",
        "file",
        "is_verified",
        "uploaded_by",
        "uploaded_at",
        "notes",
    )
    readonly_fields = ("uploaded_at",)
    autocomplete_fields = ("uploaded_by",)
    show_change_link = True


@admin.register(ClientCompliance)
class ClientComplianceAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "vetting_status",
        "vetted_by",
        "vetted_at",
        "created_at",
    )
    list_filter = (
        "vetting_status",
        "vetted_by",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "client__name",
        "client__organization",
        "vat_number",
        "company_reg_number",
        "notes",
    )
    autocomplete_fields = ("client", "vetted_by")
    readonly_fields = ("created_at", "updated_at")
    inlines = [ClientComplianceDocumentInline]

    fieldsets = (
        ("Client", {
            "fields": ("client",),
        }),
        ("Registration", {
            "fields": ("company_reg_number", "vat_number"),
        }),
        ("Vetting", {
            "fields": (
                "vetting_status",
                ("vetted_by", "vetted_at"),
                "notes",
            )
        }),
        ("Meta", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


# ============================================================
# PROSPECTS
# ============================================================

class ProspectUpdateInline(admin.TabularInline):
    model = ProspectUpdate
    extra = 0
    ordering = ("-action_at",)
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "stage",
        "status",
        "owner",
        "city",
        "province",
        "estimated_weekly_spend",
        "last_contact_at",
        "created_at",
    )
    list_filter = (
        "stage",
        "status",
        "owner",
        "province",
        ("created_at", admin.DateFieldListFilter),
        ("last_contact_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "name",
        "organization",
        "contact_name",
        "email",
        "phone",
        "whatsapp",
        "city",
        "lead_source",
        "notes",
    )
    autocomplete_fields = ("owner", "created_by", "client")
    readonly_fields = ("created_at", "updated_at", "last_contact_at")
    date_hierarchy = "created_at"
    list_per_page = 50
    save_on_top = True
    inlines = [ProspectUpdateInline]

    fieldsets = (
        ("Ownership & Pipeline", {
            "fields": (
                ("owner", "created_by"),
                ("stage", "status"),
                ("last_contact_at", "next_follow_up_at"),
            )
        }),
        ("Identity", {
            "fields": (
                "name",
                "organization",
                "contact_name",
                ("email", "phone", "whatsapp"),
            )
        }),
        ("Location", {
            "fields": (("suburb", "city", "province"),),
        }),
        ("Potential Value", {
            "fields": (
                ("potential_client_type", "potential_size_tier"),
                "estimated_weekly_spend",
                "lead_source",
            )
        }),
        ("Conversion", {
            "fields": ("client",),
        }),
        ("Notes & Meta", {
            "fields": ("notes", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


# ============================================================
# PROSPECT UPDATE
# ============================================================

@admin.register(ProspectUpdate)
class ProspectUpdateAdmin(admin.ModelAdmin):
    list_display = (
        "prospect",
        "action_at",
        "action_type",
        "outcome",
        "user",
        "old_stage",
        "new_stage",
        "visit_date",
        "has_photo",
        "short_notes",
    )
    list_filter = (
        "action_type",
        "outcome",
        "old_stage",
        "new_stage",
        "user",
        ("action_at", admin.DateFieldListFilter),
        ("visit_date", admin.DateFieldListFilter),
    )
    search_fields = (
        "prospect__name",
        "prospect__organization",
        "notes",
        "negotiation_products",
        "negotiation_menu_opportunities",
        "negotiation_competitor_info",
        "visit_contact_name",
        "user__username",
    )
    autocomplete_fields = ("prospect", "user")
    date_hierarchy = "action_at"
    ordering = ("-action_at", "-created_at")
    readonly_fields = ("created_at",)

    fieldsets = (
        ("Interaction", {
            "fields": (
                "prospect",
                "user",
                "action_type",
                "outcome",
                "action_at",
                ("old_stage", "new_stage"),
                "notes",
                "created_at",
            )
        }),
        ("Site Visit", {
            "fields": (
                "visit_date",
                ("visit_time_arrived", "visit_time_left"),
                "visit_contact_name",
                "visit_photo",
            ),
            "classes": ("collapse",),
        }),
        ("Negotiation", {
            "fields": (
                "negotiation_products",
                "negotiation_menu_opportunities",
                "negotiation_competitor_info",
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(boolean=True, description="Photo?")
    def has_photo(self, obj):
        return bool(obj.visit_photo)

    @admin.display(description="Notes")
    def short_notes(self, obj):
        if not obj.notes:
            return ""
        return obj.notes[:50] + ("…" if len(obj.notes) > 50 else "")