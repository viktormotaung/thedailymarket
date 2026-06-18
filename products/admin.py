from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect

from .models import (
    Category,
    Product,
    ProductPricing,
    ProductVariant,
)
from .forms import ProductExcelUploadForm
from .services.product_excel_importer import import_products_from_excel


# ------------------------------------------------------------------------------
# CATEGORY ADMIN
# ------------------------------------------------------------------------------

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "parent",
        "abbreviation",
        "is_active",
        "sort_order",
    )
    list_filter = ("is_active", "parent")
    search_fields = ("name", "slug", "abbreviation", "parent__name")
    ordering = ("parent__name", "sort_order", "name")
    autocomplete_fields = ("parent",)
    prepopulated_fields = {"slug": ("name",)}


# ------------------------------------------------------------------------------
# PRODUCT PRICING INLINE
# ------------------------------------------------------------------------------

class ProductPricingInline(admin.TabularInline):
    model = ProductPricing
    extra = 0
    autocomplete_fields = ("supplier",)
    show_change_link = True

    fields = (
        "supplier",
        "supplier_price_input",
        "supplier_price_is_inclusive",
        "supplier_vat_percent",
        "supplier_price_excl",

        "wholesale_margin_percent",
        "wholesale_vat_percent",

        "retail_margin_percent",
        "retail_vat_percent",

        "is_primary",
        "skip_variant_sync",
        "is_active",

        "supplier_vat_amount",
        "supplier_price_incl",
        "wholesale_margin_amount",
        "wholesale_price_excl",
        "wholesale_price_inc",
        "retail_margin_amount",
        "retail_price_excl",
        "retail_price_inc",
    )

    readonly_fields = (
        "supplier_price_excl",
        "supplier_vat_amount",
        "supplier_price_incl",
        "wholesale_margin_amount",
        "wholesale_price_excl",
        "wholesale_price_inc",
        "retail_margin_amount",
        "retail_price_excl",
        "retail_price_inc",
    )


# ------------------------------------------------------------------------------
# PRODUCT ADMIN (WITH EXCEL IMPORT ACTION)
# ------------------------------------------------------------------------------

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "product_no",
        "name",
        "category",
        "uom",
        "wholesale_price",
        "retail_price",
        "created_at",
        "updated_at",
    )

    # ✅ Sort admin by Product Number
    ordering = ("product_no",)

    search_fields = (
        "sku",
        "product_no",
        "name",
        "category__name",
        "category__parent__name",
    )

    list_filter = (
        "category",
        "uom",
        "created_at",
    )

    readonly_fields = (
        "sku",
        "slug",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = ("category",)
    inlines = [ProductPricingInline]

    fieldsets = (
        ("Basic Info", {
            "fields": (
                "product_no",
                "name",
                "category",
                "description",
                "uom",
                "image",
            )
        }),
        ("System Fields", {
            "fields": (
                "sku",
                "slug",
                "created_at",
                "updated_at",
            )
        }),
        ("Base Prices (EXCL VAT)", {
            "fields": (
                "cost_price",
                "wholesale_price",
                "retail_price",
                "retail_margin_pct",
            )
        }),
    )

    # ✅ ADMIN ACTION
    actions = ["import_products_excel_action"]

    def import_products_excel_action(self, request, queryset):
        """
        Redirects to Excel upload screen.
        Selected rows are intentionally ignored.
        """
        return redirect("admin:products_product_import_excel")

    import_products_excel_action.short_description = (
        "📥 Import / Update Products from Excel"
    )

    # ✅ CUSTOM URL FOR UPLOAD SCREEN
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-excel/",
                self.admin_site.admin_view(self.import_excel),
                name="products_product_import_excel",
            ),
        ]
        return custom_urls + urls

    # ✅ UPLOAD VIEW
    def import_excel(self, request):

        # 🔥 FORCE DB BASED ON ADMIN SITE
        if request.path.startswith("/dummy-admin/"):
            request._db = "dummy"
        else:
            request._db = "default"

        if request.method == "POST":
            form = ProductExcelUploadForm(request.POST, request.FILES)

            if form.is_valid():
                try:
                    result = import_products_from_excel(
                        form.cleaned_data["excel_file"],
                        db=request._db
                    )

                    messages.success(
                        request,
                        f"Import successful: "
                        f"{result['created']} created, "
                        f"{result['updated']} updated."
                    )

                    return redirect("..")

                except Exception as e:
                    messages.error(request, f"Import failed: {e}")

        else:
            form = ProductExcelUploadForm()

        return render(
            request,
            "admin/products/import_excel.html",
            {"form": form},
        )
    

    
# ------------------------------------------------------------------------------
# PRODUCT VARIANT ADMIN
# ------------------------------------------------------------------------------

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "pack_size",
        "uom",
        "wholesale_price_display",
        "retail_price_display",
        "scales_with_pack",
        "updated_at",
    )

    list_filter = ("product", "scales_with_pack", "uom")
    search_fields = ("product__name", "name", "sku", "slug")

    readonly_fields = (
        "wholesale_price",
        "retail_price",
    )

    fieldsets = (
        (None, {
            "fields": ("product", "name", "sku", "slug", "image", "uom", "pack_size", "scales_with_pack")
        }),
        ("Pricing (ex VAT overrides)", {
            "fields": ("wholesale_price_override", "retail_price_override")
        }),
        ("Pricing (inclusive VAT, auto-calculated)", {
            "fields": ("wholesale_price", "retail_price")
        }),
    )

    # --- Custom display methods for inclusive prices ---
    def wholesale_price_display(self, obj):
        return obj.wholesale_price or obj.wholesale_derived
    wholesale_price_display.short_description = "Wholesale Price (incl VAT)"

    def retail_price_display(self, obj):
        return obj.retail_price or obj.retail_derived
    retail_price_display.short_description = "Retail Price (incl VAT)"
