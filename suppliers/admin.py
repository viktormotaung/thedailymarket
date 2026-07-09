from django import forms
from django.contrib import admin
from django.utils.html import format_html
from image_cropping import ImageCroppingMixin
from easy_thumbnails.files import get_thumbnailer

from .models import Supplier

class SupplierAdminForm(forms.ModelForm):
    # Force a Yes/No select for the boolean
    visible = forms.TypedChoiceField(
        label="Visible",
        coerce=lambda x: x == "True",
        choices=((False, "No"), (True, "Yes")),
        widget=forms.Select
    )

    class Meta:
        model = Supplier
        fields = "__all__"

@admin.register(Supplier)
class SupplierAdmin(ImageCroppingMixin, admin.ModelAdmin):
    form = SupplierAdminForm
    list_display = (
        "logo_thumb",
        "code",
        "name",
        "has_route_location",
        "account_manager",
        "payment_terms",
        "visible",
        "is_active",
    )

    list_display_links = (
        "code",
        "name",
    )
        

    list_filter  = ("is_active", "visible", "payment_terms", "country", "province", "categories")
    search_fields = ("code", "name", "contact_person", "email", "phone", "whatsapp", "website", "city")
    filter_horizontal = ("categories",)
    readonly_fields = ("logo_preview", "created_at", "updated_at")
    autocomplete_fields = ("account_manager",)
    save_on_top = True

    fieldsets = (
        ("Identity", {"fields": ("name", "code", "categories", "is_active", "visible")}),
        ("Branding", {"fields": ("logo", "logo_cropping", "logo_preview")}),
        ("Account Owner", {"fields": ("account_manager",)}),
        ("Contact", {"fields": ("contact_person", "email", "phone", "whatsapp", "website")}),
        ("Address", {
            "fields": (
                "address_line1",
                "address_line2",
                "city",
                "province",
                "postal_code",
                "country",
                (
                    "delivery_lat",
                    "delivery_lng",
                ),
            )
        }),
        ("Compliance / IDs", {"fields": ("vat_number", "company_reg_number")}),
        ("Files", {"fields": ("contract_file",)}),
        ("Notes", {"fields": ("notes",)}),
        ("Meta", {"fields": ("created_at", "updated_at")}),
    )


    def has_route_location(self, obj):
        if obj.delivery_lat is not None and obj.delivery_lng is not None:
            return format_html(
                '<span style="color:green;font-weight:600;">✔ GPS</span>'
            )

        return format_html(
            '<span style="color:#dc3545;font-weight:600;">✖ Missing</span>'
        )

    has_route_location.short_description = "Route Location"

    # Thumbnail helpers (same as before)
    def _thumb_url(self, obj, size=(120, 60)):
        if not obj.logo:
            return None
        try:
            return get_thumbnailer(obj.logo).get_thumbnail({"size": size, "crop": True}).url
        except Exception:
            return getattr(obj.logo, "url", None)

    def logo_thumb(self, obj):
        url = self._thumb_url(obj, size=(120, 60))
        if not url:
            return "—"
        return format_html('<img src="{}" style="height:24px;max-width:90px;object-fit:contain;" alt="logo"/>', url)
    logo_thumb.short_description = "Logo"

    def logo_preview(self, obj):
        if not obj.logo:
            return "No logo uploaded"
        url = self._thumb_url(obj, size=(400, 200)) or obj.logo.url
        return format_html(
            '<img src="{}" style="max-width:100%;height:auto;max-height:160px;object-fit:contain;'
            'border:1px solid #eee;padding:6px;border-radius:6px;background:#fff"/>', url
        )
    logo_preview.short_description = "Logo preview"
