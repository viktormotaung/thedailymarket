# clients/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import Client


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
    date_hierarchy = "created_at"
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
