from django.contrib import admin
from django.utils.html import format_html
from .models import SupplierLead, HeroSlide

@admin.register(SupplierLead)
class SupplierLeadAdmin(admin.ModelAdmin):
    list_display = ("business_name", "full_name", "product_type", "weekly_capacity", "location", "created_at", "status")
    search_fields = ("business_name", "full_name", "email", "phone", "location")
    list_filter = ("product_type", "status", "created_at")

@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ("title", "label", "image_preview", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")

    readonly_fields = ("image_preview",)

    def image_preview(self, obj):
        if obj.slide_image:
            return format_html(
                '<img src="{}" width="80" style="border-radius:6px;">',
                obj.slide_image.url
            )
        return "-"
    
    image_preview.short_description = "Preview"