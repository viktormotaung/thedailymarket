# clients/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import Client, Prospect, ProspectUpdate


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        "client_number",
        "name",
        "organization",
        "client_type",
        "price_type",           # <-- show Retail / Wholesale
        "status",
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
        "price_type",           # <-- allow filtering by price type
        "province",
        "delivery_city",
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
        "email",
        "phone",
        "whatsapp",
        "vat_number",
        "company_reg_number",
        # address fields
        "address_line1",
        "address_line2",
        "suburb",
        "city",
        "province",
        "postal_code",
        "delivery_address_line1",
        "delivery_address_line2",
        "delivery_suburb",
        "delivery_city",
        "delivery_province",
        "delivery_postal_code",
    )

    readonly_fields = (
        "client_number",
        "created_at",
        "updated_at",
        "last_order_at",
        "maps_link",
    )
    filter_horizontal = ("categories",)
    autocomplete_fields = ("account_manager",)
    
    list_select_related = ("account_manager",)
    list_per_page = 50
    save_on_top = True

    fieldsets = (
        ("Account", {
            "fields": (
                ("client_number", "status"),
                ("client_type", "price_type"),      # <-- expose price type in Account section
                ("account_manager",),
                ("account_type", "credit_status"),
            )
        }),
        ("Identity", {
            "fields": (
                "name", "organization", "contact_person",
                ("email", "phone", "whatsapp"),
            )
        }),
        ("Billing / Main Address", {
            "fields": (
                "address_line1", "address_line2",
                ("suburb", "city"),
                ("province", "postal_code"),
                "country",
            )
        }),
        ("Delivery Address", {
            "fields": (
                "delivery_address_line1", "delivery_address_line2",
                ("delivery_suburb", "delivery_city"),
                ("delivery_province", "delivery_postal_code"),
                "delivery_country",
                ("delivery_lat", "delivery_lng"),
                "maps_link",
            )
        }),
        ("Compliance (optional)", {
            "fields": ("vat_number", "company_reg_number"),
            "classes": ("collapse",),
        }),
        ("Categories & Spend", {
            "fields": ("categories", "estimated_weekly_spend"),
        }),
        ("Notes & Meta", {
            "fields": ("notes", ("last_order_at", "created_at", "updated_at")),
        }),
    )

    # --- Helpers shown in admin ---

    def has_geo(self, obj: Client) -> bool:
        return obj.has_delivery_geo
    has_geo.boolean = True
    has_geo.short_description = "Geo?"

    def maps_link(self, obj: Client):
        url = obj.google_maps_link()
        return format_html('<a href="{}" target="_blank" rel="noopener">Open in Google Maps</a>', url)
    maps_link.short_description = "Map"

# ----------------------------
# Prospect / ProspectUpdate
# ----------------------------

class ProspectUpdateInline(admin.TabularInline):
    """
    Inline timeline for a prospect:
    shows calls, WhatsApps, visits, samples, etc.
    """
    model = ProspectUpdate
    extra = 0
    fields = (
        "action_at",
        "action_type",
        "outcome",
        "visit_date",
        "visit_contact_name",
        "user",
        "old_stage",
        "new_stage",
        "notes",
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
    ordering = ("-action_at", "-created_at")
    show_change_link = True


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "stage",
        "status",
        "owner",
        "created_by",
        "city",
        "province",
        "estimated_weekly_spend",
        "last_contact_at",
        "next_follow_up_at",
        "created_at",
    )
    list_filter = (
        "stage",
        "status",
        "owner",
        "created_by",
        "city",
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
        "suburb",
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
            "fields": (
                ("suburb", "city", "province"),
            )
        }),
        ("Potential Client Profile", {
            "fields": (
                ("potential_client_type", "potential_size_tier"),
                "estimated_weekly_spend",
                "lead_source",
            )
        }),
        ("Conversion Link", {
            "fields": ("client",),
        }),
        ("Notes & Meta", {
            "fields": ("notes", ("created_at", "updated_at")),
        }),
    )


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
        "visit_contact_name",
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
        "user__first_name",
        "user__last_name",
    )
    autocomplete_fields = ("prospect", "user")
    date_hierarchy = "action_at"
    list_per_page = 50
    ordering = ("-action_at", "-created_at")
    readonly_fields = ("created_at",)

    fieldsets = (
        ("Core interaction", {
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
        ("Site visit details", {
            "fields": (
                "visit_date",
                ("visit_time_arrived", "visit_time_left"),
                "visit_contact_name",
                "visit_photo",
            ),
            "classes": ("collapse",),
        }),
        ("Negotiation details", {
            "fields": (
                "negotiation_products",
                "negotiation_menu_opportunities",
                "negotiation_competitor_info",
            ),
            "classes": ("collapse",),
        }),
    )

    def short_notes(self, obj):
        if not obj.notes:
            return ""
        return (obj.notes[:50] + "…") if len(obj.notes) > 50 else obj.notes
    short_notes.short_description = "Notes"

    def has_photo(self, obj):
        return bool(obj.visit_photo)
    has_photo.boolean = True
    has_photo.short_description = "Photo?"