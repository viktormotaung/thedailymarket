from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect

from .models import (
    Category,
    Product,
    ProductPricing,
    ProductVariant,
    Procurement,
    ProcurementItem,
    PurchaseOrder,
    PurchaseOrderItem,

    # Product Knowledge
    ProductKnowledge,
    ProductKnowledgeBusinessType,
    ProductKnowledgeBenefit,
    ProductKnowledgeVariant,
    ProductKnowledgeAlternative,
    ProductKnowledgeCompetitor,
    ProductKnowledgeQuestion,
    ProductKnowledgeObjection,
    ProductKnowledgeUnitEconomics,
)

from .forms import ProductExcelUploadForm
from .services.product_excel_importer import import_products_from_excel


# =============================================================================
# CATEGORY ADMIN
# =============================================================================

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

    search_fields = (
        "name",
        "slug",
        "abbreviation",
        "parent__name",
    )

    ordering = (
        "parent__name",
        "sort_order",
        "name",
    )

    autocomplete_fields = ("parent",)

    prepopulated_fields = {
        "slug": ("name",)
    }


# =============================================================================
# PRODUCT PRICING INLINE
# =============================================================================

class ProductPricingInline(admin.TabularInline):
    model = ProductPricing
    extra = 0

    autocomplete_fields = (
        "supplier",
    )

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


# =============================================================================
# PRODUCT ADMIN
# =============================================================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "sku",
        "product_no",
        "name",
        "category",
        "visible",
        "is_special",
        "wholesale_price",
        "special_saving_display",
        "knowledge_status_display",
        "created_at",
        "updated_at",
    )

    ordering = (
        "product_no",
    )

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
        "visible",
        "is_special",
        "created_at",
    )

    readonly_fields = (
        "sku",
        "slug",
        "wholesale_price_inc",
        "special_saving",
        "special_percentage",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = (
        "category",
    )

    inlines = [
        ProductPricingInline,
    ]

    fieldsets = (
        (
            "Basic Info",
            {
                "fields": (
                    "product_no",
                    "name",
                    "category",
                    "visible",
                    "description",
                    "uom",
                    "image",
                )
            },
        ),

        (
            "System Fields",
            {
                "fields": (
                    "sku",
                    "slug",
                    "created_at",
                    "updated_at",
                )
            },
        ),

        (
            "Base Prices (EXCL VAT)",
            {
                "fields": (
                    "cost_price",
                    "wholesale_price",
                    "retail_price",
                    "retail_margin_pct",
                )
            },
        ),

        (
            "Specials",
            {
                "fields": (
                    "is_special",
                    "special_label",
                    "old_wholesale_price_inc",
                    "special_wholesale_price_inc",
                    "wholesale_price_inc",
                    "special_saving",
                    "special_percentage",
                )
            },
        ),
    )

    # =========================================================================
    # PRODUCT KNOWLEDGE STATUS
    # =========================================================================

    @admin.display(
        description="Product Knowledge",
        ordering="knowledge__updated_at",
    )
    def knowledge_status_display(self, obj):

        knowledge = getattr(obj, "knowledge", None)

        if not knowledge:
            return "NOT CREATED"

        return f"{knowledge.completion_percentage}%"

    # =========================================================================
    # SPECIAL SAVING
    # =========================================================================

    @admin.display(description="Save")
    def special_saving_display(self, obj):

        if obj.special_saving > 0:
            return f"R{obj.special_saving:.2f}"

        return "-"

    # =========================================================================
    # EXCEL IMPORT ACTION
    # =========================================================================

    actions = [
        "import_products_excel_action"
    ]

    def import_products_excel_action(self, request, queryset):
        """
        Redirects to Excel upload screen.

        Selected rows are intentionally ignored.
        """

        return redirect(
            "admin:products_product_import_excel"
        )

    import_products_excel_action.short_description = (
        "📥 Import / Update Products from Excel"
    )

    # =========================================================================
    # CUSTOM URL FOR EXCEL UPLOAD
    # =========================================================================

    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [
            path(
                "import-excel/",
                self.admin_site.admin_view(
                    self.import_excel
                ),
                name="products_product_import_excel",
            ),
        ]

        return custom_urls + urls

    # =========================================================================
    # EXCEL UPLOAD VIEW
    # =========================================================================

    def import_excel(self, request):

        # Force DB based on admin site
        if request.path.startswith("/dummy-admin/"):
            request._db = "dummy"
        else:
            request._db = "default"

        if request.method == "POST":

            form = ProductExcelUploadForm(
                request.POST,
                request.FILES,
            )

            if form.is_valid():

                try:

                    result = import_products_from_excel(
                        form.cleaned_data["excel_file"],
                        db=request._db,
                    )

                    messages.success(
                        request,
                        f"Import successful: "
                        f"{result['created']} created, "
                        f"{result['updated']} updated.",
                    )

                    return redirect("..")

                except Exception as e:

                    messages.error(
                        request,
                        f"Import failed: {e}",
                    )

        else:

            form = ProductExcelUploadForm()

        return render(
            request,
            "admin/products/import_excel.html",
            {
                "form": form,
            },
        )


# =============================================================================
# PRODUCT KNOWLEDGE INLINE BASE
# =============================================================================

class ProductKnowledgeBusinessTypeInline(
    admin.TabularInline
):
    model = ProductKnowledgeBusinessType
    extra = 1
    fields = (
        "business_type",
        "notes",
        "sort_order",
    )


class ProductKnowledgeBenefitInline(
    admin.TabularInline
):
    model = ProductKnowledgeBenefit
    extra = 1
    fields = (
        "benefit",
        "explanation",
        "sort_order",
    )


class ProductKnowledgeVariantInline(
    admin.TabularInline
):
    model = ProductKnowledgeVariant
    extra = 1
    fields = (
        "variant_name",
        "description",
        "best_suited_for",
        "customer_benefit",
        "sort_order",
    )


class ProductKnowledgeAlternativeInline(
    admin.TabularInline
):
    model = ProductKnowledgeAlternative
    extra = 1
    fields = (
        "brand",
        "product_name",
        "notes",
        "sort_order",
    )


class ProductKnowledgeCompetitorInline(
    admin.TabularInline
):
    model = ProductKnowledgeCompetitor
    extra = 1
    fields = (
        "competitor_brand",
        "competitor_product",
        "why_customer_uses_it",
        "tdm_positioning",
        "sort_order",
    )


class ProductKnowledgeQuestionInline(
    admin.TabularInline
):
    model = ProductKnowledgeQuestion
    extra = 1
    fields = (
        "question",
        "purpose",
        "sort_order",
    )


class ProductKnowledgeUnitEconomicsInline(admin.StackedInline):
    model = ProductKnowledgeUnitEconomics
    extra = 0
    max_num = 1
    fields = (
        "is_applicable",
        "base_quantity",
        "base_uom",
        "unit_name",
        "minimum_units",
        "maximum_units",
        "current_wholesale_price_display",
        "cost_per_unit_low_display",
        "cost_per_unit_high_display",
        "cost_per_unit_display",
        "cost_display",
        "created_at",
        "updated_at",
    )
    readonly_fields = (
        "current_wholesale_price_display",
        "cost_per_unit_low_display",
        "cost_per_unit_high_display",
        "cost_per_unit_display",
        "cost_display",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Current Wholesale Price (incl VAT)")
    def current_wholesale_price_display(self, obj):
        return f"R{obj.current_wholesale_price:,.2f}"

    @admin.display(description="Lowest Cost per Unit")
    def cost_per_unit_low_display(self, obj):
        return f"R{obj.cost_per_unit_low:,.2f}"

    @admin.display(description="Highest Cost per Unit")
    def cost_per_unit_high_display(self, obj):
        return f"R{obj.cost_per_unit_high:,.2f}"

    @admin.display(description="Exact Cost per Unit")
    def cost_per_unit_display(self, obj):
        if not obj.is_exact:
            return "— (range)"
        return f"R{obj.cost_per_unit:,.2f}"

    @admin.display(description="Sales Display")
    def cost_display(self, obj):
        return obj.cost_display


class ProductKnowledgeObjectionInline(
    admin.TabularInline
):
    model = ProductKnowledgeObjection
    extra = 1
    fields = (
        "objection",
        "response",
        "notes",
        "sort_order",
    )


# =============================================================================
# PRODUCT KNOWLEDGE ADMIN
# =============================================================================

@admin.register(ProductKnowledge)
class ProductKnowledgeAdmin(admin.ModelAdmin):

    list_display = (
        "product",
        "completion_display",
        "status_display",
        "is_approved",
        "updated_at",
    )

    search_fields = (
        "product__product_no",
        "product__name",
        "product__sku",
    )

    list_filter = (
        "is_approved",
        "variants_not_applicable",
        "updated_at",
    )

    ordering = (
        "product__name",
    )

    autocomplete_fields = (
        "product",
    )

    readonly_fields = (
        "completion_display",
        "status_display",
        "created_at",
        "updated_at",
    )

    fieldsets = (

        (
            "Product",
            {
                "fields": (
                    "product",
                )
            },
        ),

        (
            "Product Knowledge Completion",
            {
                "fields": (
                    "completion_display",
                    "status_display",
                )
            },
        ),

        (
            "1. Product Description / Definition",
            {
                "fields": (
                    "product_description",
                )
            },
        ),

        (
            "3. Usage / Application",
            {
                "fields": (
                    "usage_application",
                )
            },
        ),

        (
            "5. Yield / Portion Information",
            {
                "fields": (
                    "yield_portion_information",
                )
            },
        ),

        (
            "6. Variants",
            {
                "fields": (
                    "variants_not_applicable",
                )
            },
        ),

        (
            "9. Why Choose The Daily Market",
            {
                "fields": (
                    "why_choose_tdm",
                )
            },
        ),

        (
            "12. Key Takeaways",
            {
                "fields": (
                    "key_takeaways",
                )
            },
        ),

        (
            "Approval",
            {
                "fields": (
                    "is_approved",
                    "approved_at",
                )
            },
        ),

        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            }
        ),
    )

    inlines = [
        ProductKnowledgeUnitEconomicsInline,
        ProductKnowledgeBusinessTypeInline,
        ProductKnowledgeBenefitInline,
        ProductKnowledgeVariantInline,
        ProductKnowledgeAlternativeInline,
        ProductKnowledgeCompetitorInline,
        ProductKnowledgeQuestionInline,
        ProductKnowledgeObjectionInline,
    ]

    # =========================================================================
    # COMPLETION DISPLAY
    # =========================================================================

    @admin.display(
        description="Completion",
        ordering="updated_at",
    )
    def completion_display(self, obj):

        return f"{obj.completion_percentage}%"

    # =========================================================================
    # STATUS DISPLAY
    # =========================================================================

    @admin.display(
        description="Status",
    )
    def status_display(self, obj):

        return obj.knowledge_status


# =============================================================================
# PRODUCT VARIANT ADMIN
# =============================================================================

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

    list_filter = (
        "product",
        "scales_with_pack",
        "uom",
    )

    search_fields = (
        "product__name",
        "name",
        "sku",
        "slug",
    )

    readonly_fields = (
        "wholesale_price",
        "retail_price",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "product",
                    "name",
                    "sku",
                    "slug",
                    "image",
                    "uom",
                    "pack_size",
                    "scales_with_pack",
                )
            },
        ),

        (
            "Pricing (ex VAT overrides)",
            {
                "fields": (
                    "wholesale_price_override",
                    "retail_price_override",
                )
            },
        ),

        (
            "Pricing (inclusive VAT, auto-calculated)",
            {
                "fields": (
                    "wholesale_price",
                    "retail_price",
                )
            },
        ),
    )

    # =========================================================================
    # CUSTOM DISPLAY METHODS
    # =========================================================================

    @admin.display(
        description="Wholesale Price (incl VAT)"
    )
    def wholesale_price_display(self, obj):

        return (
            obj.wholesale_price
            or obj.wholesale_derived
        )

    @admin.display(
        description="Retail Price (incl VAT)"
    )
    def retail_price_display(self, obj):

        return (
            obj.retail_price
            or obj.retail_derived
        )

# =============================================================================
# PROCUREMENT / PURCHASE ORDER ADMIN
# =============================================================================

@admin.register(ProcurementItem)
class ProcurementItemAdmin(admin.ModelAdmin):
    list_display = (
        "procurement",
        "product",
        "required_quantity",
        "created_at",
    )

    list_filter = (
        "procurement__procurement_date",
        "procurement__wave",
    )

    search_fields = (
        "product__product_no",
        "product__name",
        "product__sku",
        "procurement__procurement_number",
    )

    ordering = (
        "-procurement__procurement_date",
        "product__name",
    )

    autocomplete_fields = (
        "procurement",
        "product",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


class ProcurementItemInline(admin.TabularInline):
    model = ProcurementItem
    extra = 0
    autocomplete_fields = ("product",)
    fields = (
        "product",
        "required_quantity",
        "notes",
    )
    show_change_link = True


@admin.register(Procurement)
class ProcurementAdmin(admin.ModelAdmin):

    list_display = (
        "procurement_number",
        "procurement_date",
        "wave",
        "status",
        "created_by",
        "approved_by",
        "approved_at",
        "created_at",
    )

    list_filter = (
        "procurement_date",
        "wave",
        "status",
        "created_at",
    )

    search_fields = (
        "procurement_number",
        "notes",
        "created_by__username",
        "approved_by__username",
    )

    ordering = (
        "-procurement_date",
        "-wave",
        "-id",
    )

    autocomplete_fields = (
        "created_by",
        "approved_by",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "approved_at",
    )

    fieldsets = (
        (
            "Procurement",
            {
                "fields": (
                    "procurement_number",
                    "procurement_date",
                    "wave",
                    "status",
                )
            },
        ),
        (
            "Approval",
            {
                "fields": (
                    "created_by",
                    "approved_by",
                    "approved_at",
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
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    inlines = [
        ProcurementItemInline,
    ]


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    autocomplete_fields = (
        "procurement_item",
        "product",
    )
    fields = (
        "procurement_item",
        "product",
        "ordered_quantity",
        "expected_unit_cost_excl",
        "expected_total_excl_display",
        "notes",
    )
    readonly_fields = (
        "expected_total_excl_display",
    )
    show_change_link = True

    @admin.display(description="Expected Total EXCL VAT")
    def expected_total_excl_display(self, obj):
        return obj.expected_total_excl


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):

    list_display = (
        "po_number",
        "procurement",
        "supplier",
        "order_date",
        "expected_delivery_date",
        "status",
        "created_by",
        "approved_by",
        "sent_at",
    )

    list_filter = (
        "status",
        "order_date",
        "expected_delivery_date",
        "supplier",
        "created_at",
    )

    search_fields = (
        "po_number",
        "supplier__name",
        "supplier_reference",
        "procurement__procurement_number",
        "created_by__username",
        "approved_by__username",
        "notes",
    )

    ordering = (
        "-order_date",
        "-id",
    )

    autocomplete_fields = (
        "procurement",
        "supplier",
        "created_by",
        "approved_by",
    )

    readonly_fields = (
        "approved_at",
        "sent_at",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Purchase Order",
            {
                "fields": (
                    "po_number",
                    "procurement",
                    "supplier",
                    "order_date",
                    "expected_delivery_date",
                    "status",
                    "supplier_reference",
                )
            },
        ),
        (
            "Approval & Sending",
            {
                "fields": (
                    "created_by",
                    "approved_by",
                    "approved_at",
                    "sent_at",
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
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    inlines = [
        PurchaseOrderItemInline,
    ]
