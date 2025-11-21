# products/admin.py
from django.contrib import admin
from .models import Category, Product, ProductPricing, ProductVariant

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "abbreviation", "is_active", "sort_order")
    search_fields = ("name", "slug", "abbreviation")
    ordering = ("sort_order", "name")
    prepopulated_fields = {"slug": ("name",)}

class ProductPricingInline(admin.TabularInline):
    model = ProductPricing
    extra = 0
    autocomplete_fields = ("supplier",)
    fields = (
        "supplier",
        "supplier_price_excl", "supplier_vat_percent",
        "wholesale_margin_percent", "wholesale_vat_percent",
        "retail_margin_percent", "retail_vat_percent",
        "is_active",
        # computed (readonly) – optional to show in the inline:
        "supplier_vat_amount", "supplier_price_incl",
        "wholesale_margin_amount", "wholesale_price_excl", "wholesale_price_inc",
        "retail_margin_amount", "retail_price_excl", "retail_price_inc",
    )
    readonly_fields = (
        "supplier_vat_amount", "supplier_price_incl",
        "wholesale_margin_amount", "wholesale_price_excl", "wholesale_price_inc",
        "retail_margin_amount", "retail_price_excl", "retail_price_inc",
    )

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "uom", "created_at", "updated_at")
    search_fields = ("sku", "name", "category__name")
    list_filter = ("category", "uom")
    readonly_fields = ("sku", "slug", "created_at", "updated_at")
    autocomplete_fields = ("category",)  # optional
    inlines = [ProductPricingInline]

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "pack_size", "uom", "sku", "retail_price_override", "wholesale_price_override", "updated_at")
    list_filter = ("uom", "product__category")
    search_fields = ("product__name", "sku", "name")
