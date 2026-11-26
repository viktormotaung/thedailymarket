# products/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db.models import Q, Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from suppliers.models import Supplier
from .models import Product, Category, ProductPricing
from .models import Procurement, ProcurementItem, PurchaseOrder, PurchaseOrderItem
from .forms import ProductForm, ProductVariantFormSet, ProductPricingForm, ProductKnowledgeForm
from django.db import transaction
from .forms import ProductForm, ProductVariantForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.shortcuts import redirect, render, get_object_or_404
from decimal import Decimal
from django.db.models import Count, Q, Min, Max, Avg, Sum, F, DecimalField, ExpressionWrapper
from django.apps import apps

from django.utils import timezone
from products.models import Product, Category, ProductPricing, ProductVariant
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import inlineformset_factory
from django.forms import modelform_factory
from django.forms.models import BaseInlineFormSet
from django.shortcuts import get_object_or_404, redirect, render
from .forms import ProductExcelUploadForm
import traceback
from django.http import JsonResponse
from products.services.excel_errors import ExcelImportError
from django.views.decorators.http import require_POST
from .services.product_excel_importer import import_products_from_excel
from products.models import Product, ProductVariant
from products.forms import (
    ProductForm,
    ProductVariantForm,
)
from .forms import ProductForm, ProductVariantForm
from .models import Product, ProductVariant, ProductKnowledge
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Image
from django.conf import settings
import os
from datetime import timedelta
from io import BytesIO

from reportlab.lib.utils import ImageReader

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
)

# -----------------------------------------------------
# Auth helpers
# -----------------------------------------------------
def staff_check(user):
    return user.is_authenticated and user.is_staff


staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")


# -----------------------------------------------------
# Product list
# -----------------------------------------------------
@login_required
@staff_required
def product_list(request):
    """
    List products with filters (search, category, supplier).
    Shows ONE aggregated price per product:
    - cheapest wholesale (incl VAT)
    - cheapest retail (incl VAT)
    """

    qs = (
        Product.objects
        .select_related("category")
        .prefetch_related("pricing_rows__supplier")
        .order_by("product_no")   # ← changed from name
    )

    # Filters
    filter_categories = Category.objects.order_by("name")
    filter_suppliers = Supplier.objects.order_by("name")

    search = (request.GET.get("search") or "").strip()
    category_id = (request.GET.get("category") or "").strip()
    supplier_id = (request.GET.get("supplier") or "").strip()

    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(sku__icontains=search)
        )

    if category_id:
        qs = qs.filter(category_id=category_id)

    if supplier_id:
        active_for_supplier = ProductPricing.objects.filter(
            product=OuterRef("pk"),
            supplier_id=supplier_id,
            is_active=True,
        )
        qs = qs.annotate(
            _has_supplier=Exists(active_for_supplier)
        ).filter(_has_supplier=True)

    products = list(qs)

    rows = []
    for p in products:
        active_rows = [r for r in p.pricing_rows.all() if r.is_active]

        min_wholesale_inc = None
        min_retail_inc = None

        if active_rows:

            # -------------------------------------------------
            # WHOLESALE PRICE
            # -------------------------------------------------
            # If the product is on special, use the special
            # wholesale price instead of the normal price.
            if (
                p.is_special
                and p.special_wholesale_price_inc is not None
            ):
                min_wholesale_inc = p.special_wholesale_price_inc

            else:
                w_vals = [
                    r.wholesale_price_inc
                    for r in active_rows
                    if r.wholesale_price_inc is not None
                ]

                if w_vals:
                    min_wholesale_inc = min(w_vals)

            # -------------------------------------------------
            # RETAIL PRICE
            # -------------------------------------------------
            r_vals = [
                r.retail_price_inc
                for r in active_rows
                if r.retail_price_inc is not None
            ]

            if r_vals:
                min_retail_inc = min(r_vals)

        rows.append({
            "product": p,
            "active_supplier_count": len(active_rows),
            "min_wholesale_inc": min_wholesale_inc,
            "min_retail_inc": min_retail_inc,
        })

    price_list_subcategories = list(
        Category.objects.filter(
            is_active=True,
            parent__isnull=False,
        )
        .select_related("parent")
        .order_by("name")
    )

    price_list_subcategories.sort(
        key=lambda category: (
            category.parent.name if category.parent else "",
            category.name or "",
        )
    )

    return render(
        request,
        "products/product_list.html",
        {
            "rows": rows,
            "filter_categories": filter_categories,
            "filter_suppliers": filter_suppliers,
            "search": search,
            "price_list_subcategories": price_list_subcategories,
        },
    )


# -----------------------------------------------------
# Product Knowledge
# -----------------------------------------------------

@login_required
@staff_required
def product_knowledge_list(request):
    """
    List all Product Knowledge records.

    Product Knowledge is automatically created for Products,
    so this page provides the staff-facing overview of the
    knowledge profiles and their completion status.
    """

    qs = (
        ProductKnowledge.objects
        .select_related(
            "product",
            "product__category",
        )
        .order_by("id")
    )

    # -----------------------------------------------------
    # Search
    # -----------------------------------------------------

    search = request.GET.get("search", "").strip()

    if search:
        qs = qs.filter(
            Q(product__product_no__icontains=search)
            | Q(product__name__icontains=search)
            | Q(product__sku__icontains=search)
            | Q(product__category__name__icontains=search)
        )

    # -----------------------------------------------------
    # Category filter
    # -----------------------------------------------------

    category_id = request.GET.get("category")

    if category_id:
        qs = qs.filter(
            product__category_id=category_id
        )

    # -----------------------------------------------------
    # Knowledge status filter
    # -----------------------------------------------------

    status = request.GET.get("status")

    if status == "complete":
        qs = [
            knowledge
            for knowledge in qs
            if knowledge.completion_percentage == 100
        ]

    elif status == "incomplete":
        qs = [
            knowledge
            for knowledge in qs
            if knowledge.completion_percentage < 100
        ]

    elif status == "approved":
        qs = qs.filter(
            is_approved=True
        )

    elif status == "not-approved":
        qs = qs.filter(
            is_approved=False
        )

    # Keep the existing display order without asking MariaDB to
    # sort ProductKnowledge by fields on the related Product table.
    qs = list(qs)

    qs.sort(
        key=lambda knowledge: (
            knowledge.product.product_no
            if knowledge.product and knowledge.product.product_no
            else "",
            knowledge.product.name
            if knowledge.product and knowledge.product.name
            else "",
        )
    )

    # -----------------------------------------------------
    # Categories
    # -----------------------------------------------------

    categories_with_products = Product.objects.filter(
        category_id=OuterRef("pk")
    )

    categories = (
        Category.objects
        .filter(
            Exists(categories_with_products)
        )
        .order_by("name")
    )

    # -----------------------------------------------------
    # Render
    # -----------------------------------------------------

    return render(
        request,
        "products/product_knowledge_list.html",
        {
            "product_knowledge_list": qs,
            "categories": categories,
            "search": search,
            "selected_category": category_id,
            "selected_status": status,
            "current": "product-knowledge-list",
        },
    )


# -----------------------------------------------------
# Product Knowledge View
# -----------------------------------------------------

@login_required
@staff_required
def product_knowledge_view(request, pk):
    """
    Display the complete Product Knowledge profile for one product.
    """

    knowledge = get_object_or_404(
        ProductKnowledge.objects
        .select_related(
            "product",
            "product__category",
        )
        .prefetch_related(
            "customer_business_types",
            "product_benefits",
            "knowledge_variants",
            "customer_alternatives",
            "product_competitors",
            "customer_questions",
            "product_objections",
        ),
        pk=pk,
    )

    return render(
        request,
        "products/product_knowledge_view.html",
        {
            "knowledge": knowledge,
            "product": knowledge.product,
            "current": "product-knowledge-view",
        },
    )



# -----------------------------------------------------
# Product Knowledge Manual PDF
# -----------------------------------------------------

@login_required
@staff_required
def product_knowledge_manual(request):
    """
    Generate a PDF Product Knowledge Manual containing
    all Product Knowledge records currently stored.

    Each product includes:
        - Product number
        - Product name
        - Product image
        - Category
        - UOM
        - Completion percentage
        - Knowledge status
        - All Product Knowledge sections
    """

    from xml.sax.saxutils import escape

    knowledge_records = list(
        ProductKnowledge.objects
        .select_related(
            "product",
            "product__category",
        )
        .prefetch_related(
            "customer_business_types",
            "product_benefits",
            "knowledge_variants",
            "customer_alternatives",
            "product_competitors",
            "customer_questions",
            "product_objections",
        )
        .order_by("id")
    )

    knowledge_records.sort(
        key=lambda knowledge: (
            knowledge.product.product_no
            if knowledge.product and knowledge.product.product_no
            else "",
            knowledge.product.name
            if knowledge.product and knowledge.product.name
            else "",
        )
    )

    response = HttpResponse(
        content_type="application/pdf"
    )

    response[
        "Content-Disposition"
    ] = (
        'attachment; '
        'filename="The_Daily_Market_Product_Knowledge_Manual.pdf"'
    )

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()

    # =====================================================
    # STYLES
    # =====================================================

    title_style = ParagraphStyle(
        "ManualTitle",
        parent=styles["Title"],
        fontSize=20,
        leading=24,
        spaceAfter=10,
    )

    product_style = ParagraphStyle(
        "ProductTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        spaceBefore=10,
        spaceAfter=8,
    )

    section_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=4,
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        spaceAfter=4,
    )

    small_style = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10,
    )

    elements = []

    # =====================================================
    # MANUAL COVER
    # =====================================================

    elements.append(
        Paragraph(
            "THE DAILY MARKET",
            title_style,
        )
    )

    elements.append(
        Paragraph(
            "PRODUCT KNOWLEDGE MANUAL",
            product_style,
        )
    )

    elements.append(
        Paragraph(
            "Sales Product Knowledge",
            body_style,
        )
    )

    elements.append(
        Spacer(1, 0.5 * cm)
    )

    elements.append(
        Paragraph(
            f"Products included: {len(knowledge_records)}",
            body_style,
        )
    )

    elements.append(
        Spacer(1, 0.5 * cm)
    )

    # =====================================================
    # PRODUCT RECORDS
    # =====================================================

    for index, knowledge in enumerate(
        knowledge_records
    ):

        product = knowledge.product

        if index > 0:
            elements.append(
                Spacer(1, 0.8 * cm)
            )

        # -------------------------------------------------
        # Product Header
        # -------------------------------------------------

        elements.append(
            Paragraph(
                escape(
                    f"{product.product_no} · {product.name}"
                ),
                product_style,
            )
        )

        # -------------------------------------------------
        # Product Image
        # -------------------------------------------------

        if product.image:

            try:
                image_buffer = BytesIO()

                image_file = product.image.open("rb")

                try:
                    image_buffer.write(
                        image_file.read()
                    )
                finally:
                    image_file.close()

                image_buffer.seek(0)

                image_reader = ImageReader(
                    image_buffer
                )

                image_width, image_height = (
                    image_reader.getSize()
                )

                # Maximum image size
                max_width = 5 * cm
                max_height = 5 * cm

                # Prevent division by zero
                if image_width > 0 and image_height > 0:

                    # Preserve original aspect ratio
                    scale = min(
                        max_width / image_width,
                        max_height / image_height,
                    )

                    display_width = (
                        image_width * scale
                    )

                    display_height = (
                        image_height * scale
                    )

                    elements.append(
                        Image(
                            image_buffer,
                            width=display_width,
                            height=display_height,
                        )
                    )

                    elements.append(
                        Spacer(
                            1,
                            0.3 * cm,
                        )
                    )

            except Exception:
                # If the image cannot be loaded,
                # continue generating the manual.
                pass

        # -------------------------------------------------
        # Product Information
        # -------------------------------------------------

        category_name = (
            product.category.name
            if product.category
            else "N/A"
        )

        elements.append(
            Paragraph(
                escape(
                    f"Category: {category_name} | "
                    f"UOM: {product.get_uom_display()} | "
                    f"Completion: "
                    f"{knowledge.completion_percentage}% | "
                    f"Status: "
                    f"{knowledge.knowledge_status}"
                ),
                small_style,
            )
        )

        # -------------------------------------------------
        # 1. Description
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "1. Product Description / Definition",
                section_style,
            )
        )

        elements.append(
            Paragraph(
                escape(
                    knowledge.product_description
                    or "N/A"
                ),
                body_style,
            )
        )

        # -------------------------------------------------
        # 2. Customer / Business Types
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "2. Customer / Business Types",
                section_style,
            )
        )

        business_types = (
            knowledge.customer_business_types.all()
        )

        if business_types:

            for item in business_types:

                text = escape(
                    item.business_type
                )

                if item.notes:
                    text += (
                        f" — "
                        f"{escape(item.notes)}"
                    )

                elements.append(
                    Paragraph(
                        f"• {text}",
                        body_style,
                    )
                )

        else:

            elements.append(
                Paragraph(
                    "N/A",
                    body_style,
                )
            )

        # -------------------------------------------------
        # 3. Usage
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "3. Where / What It Is Used For",
                section_style,
            )
        )

        elements.append(
            Paragraph(
                escape(
                    knowledge.usage_application
                    or "N/A"
                ),
                body_style,
            )
        )

        # -------------------------------------------------
        # 4. Benefits
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "4. Product Benefits",
                section_style,
            )
        )

        benefits = (
            knowledge.product_benefits.all()
        )

        if benefits:

            for item in benefits:

                text = (
                    f"<b>"
                    f"{escape(item.benefit)}"
                    f"</b>"
                )

                if item.explanation:
                    text += (
                        f" — "
                        f"{escape(item.explanation)}"
                    )

                elements.append(
                    Paragraph(
                        f"• {text}",
                        body_style,
                    )
                )

        else:

            elements.append(
                Paragraph(
                    "N/A",
                    body_style,
                )
            )

        # -------------------------------------------------
        # 5. Yield / Portion
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "5. Yield / Portion Information",
                section_style,
            )
        )

        elements.append(
            Paragraph(
                escape(
                    knowledge.yield_portion_information
                    or "N/A"
                ),
                body_style,
            )
        )

        # -------------------------------------------------
        # 6. Knowledge Variants
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "6. Product Knowledge Variants",
                section_style,
            )
        )

        variants = (
            knowledge.knowledge_variants.all()
        )

        if knowledge.variants_not_applicable:

            elements.append(
                Paragraph(
                    "N/A — No relevant knowledge variants.",
                    body_style,
                )
            )

        elif variants:

            for item in variants:

                elements.append(
                    Paragraph(
                        f"<b>"
                        f"{escape(item.variant_name)}"
                        f"</b>",
                        body_style,
                    )
                )

                elements.append(
                    Paragraph(
                        escape(
                            item.description
                        ),
                        small_style,
                    )
                )

                elements.append(
                    Paragraph(
                        f"<b>Best suited for:</b> "
                        f"{escape(item.best_suited_for)}",
                        small_style,
                    )
                )

                elements.append(
                    Paragraph(
                        f"<b>Customer benefit:</b> "
                        f"{escape(item.customer_benefit)}",
                        small_style,
                    )
                )

        else:

            elements.append(
                Paragraph(
                    "N/A",
                    body_style,
                )
            )

        # -------------------------------------------------
        # 7. Alternatives
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "7. Customer Alternatives",
                section_style,
            )
        )

        alternatives = (
            knowledge.customer_alternatives.all()
        )

        if alternatives:

            for item in alternatives:

                name = escape(
                    item.brand
                )

                if item.product_name:
                    name += (
                        f" · "
                        f"{escape(item.product_name)}"
                    )

                if item.notes:
                    name += (
                        f" — "
                        f"{escape(item.notes)}"
                    )

                elements.append(
                    Paragraph(
                        f"• {name}",
                        body_style,
                    )
                )

        else:

            elements.append(
                Paragraph(
                    "N/A",
                    body_style,
                )
            )

        # -------------------------------------------------
        # 8. Competitors
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "8. Competitor Comparison",
                section_style,
            )
        )

        competitors = (
            knowledge.product_competitors.all()
        )

        if competitors:

            for item in competitors:

                competitor = escape(
                    item.competitor_brand
                )

                if item.competitor_product:
                    competitor += (
                        f" · "
                        f"{escape(item.competitor_product)}"
                    )

                elements.append(
                    Paragraph(
                        f"<b>{competitor}</b>",
                        body_style,
                    )
                )

                elements.append(
                    Paragraph(
                        f"<b>Why customers use it:</b> "
                        f"{escape(item.why_customer_uses_it)}",
                        small_style,
                    )
                )

                elements.append(
                    Paragraph(
                        f"<b>TDM positioning:</b> "
                        f"{escape(item.tdm_positioning)}",
                        small_style,
                    )
                )

        else:

            elements.append(
                Paragraph(
                    "N/A",
                    body_style,
                )
            )

        # -------------------------------------------------
        # 9. Why Choose TDM
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "9. Why Choose The Daily Market",
                section_style,
            )
        )

        elements.append(
            Paragraph(
                escape(
                    knowledge.why_choose_tdm
                    or "N/A"
                ),
                body_style,
            )
        )

        # -------------------------------------------------
        # 10. Customer Questions
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "10. Customer Questions",
                section_style,
            )
        )

        questions = (
            knowledge.customer_questions.all()
        )

        if questions:

            for item in questions:

                elements.append(
                    Paragraph(
                        f"<b>Question:</b> "
                        f"{escape(item.question)}",
                        body_style,
                    )
                )

                if item.purpose:

                    elements.append(
                        Paragraph(
                            f"<b>Purpose:</b> "
                            f"{escape(item.purpose)}",
                            small_style,
                        )
                    )

        else:

            elements.append(
                Paragraph(
                    "N/A",
                    body_style,
                )
            )

        # -------------------------------------------------
        # 11. Objections
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "11. Common Objections & Responses",
                section_style,
            )
        )

        objections = (
            knowledge.product_objections.all()
        )

        if objections:

            for item in objections:

                elements.append(
                    Paragraph(
                        f"<b>Objection:</b> "
                        f"{escape(item.objection)}",
                        body_style,
                    )
                )

                elements.append(
                    Paragraph(
                        f"<b>Recommended response:</b> "
                        f"{escape(item.response)}",
                        small_style,
                    )
                )

                if item.notes:

                    elements.append(
                        Paragraph(
                            f"<b>Notes:</b> "
                            f"{escape(item.notes)}",
                            small_style,
                        )
                    )

        else:

            elements.append(
                Paragraph(
                    "N/A",
                    body_style,
                )
            )

        # -------------------------------------------------
        # 12. Key Takeaways
        # -------------------------------------------------

        elements.append(
            Paragraph(
                "12. Key Takeaways",
                section_style,
            )
        )

        elements.append(
            Paragraph(
                escape(
                    knowledge.key_takeaways
                    or "N/A"
                ),
                body_style,
            )
        )

        # -------------------------------------------------
        # Approval
        # -------------------------------------------------

        elements.append(
            Spacer(
                1,
                0.2 * cm,
            )
        )

        elements.append(
            Paragraph(
                escape(
                    "Approved"
                    if knowledge.is_approved
                    else "Not Approved"
                ),
                small_style,
            )
        )

    # =====================================================
    # BUILD PDF
    # =====================================================

    doc.build(elements)

    return response


@login_required
def product_knowledge_edit(request, pk):
    knowledge = get_object_or_404(
        ProductKnowledge.objects.select_related("product"),
        pk=pk,
    )

    if request.method == "POST":
        form = ProductKnowledgeForm(
            request.POST,
            instance=knowledge,
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "Product Knowledge updated successfully.",
            )

            return redirect(
                "product-knowledge-view",
                pk=knowledge.pk,
            )

    else:
        form = ProductKnowledgeForm(
            instance=knowledge,
        )

    return render(
        request,
        "products/product_knowledge_edit.html",
        {
            "knowledge": knowledge,
            "form": form,
            "current": "product-knowledge-edit",
        },
    )



@login_required
def download_price_list(request):
    subcategory_ids = request.GET.getlist("subcategories")

    # =====================================================
    # PRODUCTS
    # =====================================================
    qs = (
        Product.objects
        .select_related("category", "category__parent")
        .prefetch_related("pricing_rows")
        .filter(
            category__parent__isnull=False,
            visible="YES",
        )
        .order_by("product_no")
    )

    if subcategory_ids:
        qs = qs.filter(category_id__in=subcategory_ids)

    # Sort the small price-list result in Python rather than asking
    # MariaDB to sort by fields on the related Category tables.
    qs = list(qs)
    qs.sort(
        key=lambda product: (
            product.category.parent.name
            if product.category and product.category.parent
            else "",
            product.product_no or "",
        )
    )

    # =====================================================
    # WEEKLY PRICE LIST PERIOD
    # =====================================================
    today = timezone.localdate()

    week_number = today.isocalendar().week

    week_start = today
    week_end = today + timedelta(days=7)

    week_label = (
        f"WEEK {week_number} • "
        f"{week_start.strftime('%d')} - "
        f"{week_end.strftime('%d / %m / %Y')}"
    )

    filename_dates = (
        f"{week_start.strftime('%d')}-"
        f"{week_end.strftime('%d_%m_%Y')}"
    )

    # =====================================================
    # RESPONSE
    # =====================================================
    response = HttpResponse(content_type="application/pdf")

    response["Content-Type"] = "application/pdf"
    response["Content-Disposition"] = (
        f'attachment; filename="The_Daily_Market_Wholesale_Price_List_{filename_dates}.pdf"'
    )

    # =====================================================
    # DOCUMENT
    # =====================================================
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1 * cm,
    )

    styles = getSampleStyleSheet()
    elements = []

    # =====================================================
    # BRAND COLOURS
    # =====================================================
    TDM_GREEN = colors.HexColor("#0b5c39")
    TDM_LIGHT_GREEN = colors.HexColor("#eaf3ee")
    DARK_TEXT = colors.HexColor("#222222")
    LIGHT_GREY = colors.HexColor("#f3f3f3")
    BORDER_GREY = colors.HexColor("#cfcfcf")

    # =====================================================
    # CUSTOM STYLES
    # =====================================================
    company_name_style = ParagraphStyle(
        "CompanyName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=19,
        textColor=TDM_GREEN,
        spaceAfter=2,
    )

    company_subtitle_style = ParagraphStyle(
        "CompanySubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=DARK_TEXT,
    )

    tagline_style = ParagraphStyle(
        "Tagline",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
        textColor=TDM_GREEN,
        alignment=1,
    )

    contact_style = ParagraphStyle(
        "Contact",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=DARK_TEXT,
    )

    contact_heading_style = ParagraphStyle(
        "ContactHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10,
        textColor=TDM_GREEN,
    )

    title_style = ParagraphStyle(
        "PriceListTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=21,
        textColor=colors.white,
        alignment=1,
        spaceAfter=0,
    )

    subtitle_style = ParagraphStyle(
        "PriceListSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )

    updated_style = ParagraphStyle(
        "Updated",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=colors.white,
        alignment=1,
    )

    # =====================================================
    # SPECIAL PRODUCT STYLE
    # =====================================================
    special_product_style = ParagraphStyle(
        "SpecialProduct",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=DARK_TEXT,
    )

    special_price_style = ParagraphStyle(
        "SpecialPrice",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=TDM_GREEN,
        alignment=2,
    )

    normal_price_style = ParagraphStyle(
        "NormalPrice",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=DARK_TEXT,
        alignment=2,
    )

    # =====================================================
    # FOOTER
    # =====================================================
    generated_at = timezone.localtime().strftime("%d %B %Y %H:%M")

    def add_footer(canvas, doc):
        canvas.saveState()

        # =================================================
        # BUSINESS ADDRESS
        # =================================================
        address_text = (
            "47A Russel Road, Steynsvlei, Muldersdrift"
        )

        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(TDM_GREEN)

        canvas.drawCentredString(
            A4[0] / 2,
            1.05 * cm,
            address_text
        )

        # =================================================
        # FOOTER INFORMATION
        # =================================================
        footer_text = (
            f"The Daily Market | Wholesale Price List | "
            f"Generated {generated_at} | Page {canvas.getPageNumber()}"
        )

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)

        canvas.drawCentredString(
            A4[0] / 2,
            0.55 * cm,
            footer_text
        )

        canvas.restoreState()

    # =====================================================
    # LOGO
    # =====================================================
    logo_path = os.path.join(
        settings.BASE_DIR,
        "static",
        "images",
        "seshibo-logo.png"
    )

    logo = None

    if os.path.exists(logo_path):
        logo = Image(
            logo_path,
            width=3.2 * cm,
            height=3.2 * cm,
        )

    # =====================================================
    # COMPANY INFORMATION
    # =====================================================
    company_info = [
        Paragraph(
            "THE DAILY MARKET",
            company_name_style
        ),
        Paragraph(
            "Wholesale Food Supply",
            company_subtitle_style
        ),
        Spacer(1, 4),
        Paragraph(
            "Quality you can count on.",
            contact_style
        ),
        Spacer(1, 4),
        Paragraph(
            "Reg: 2024/232233/07",
            contact_style
        ),
    ]

    contact_info = [
        Paragraph(
            "CONTACT & ORDERS",
            contact_heading_style
        ),
        Spacer(1, 2),
        Paragraph(
            "<b>Tel:</b> 087 265 5488",
            contact_style
        ),
        Paragraph(
            "<b>WhatsApp Orders:</b> 062 231 1902",
            contact_style
        ),
        Paragraph(
            "<b>Email:</b> sales@thedailymarket.co.za",
            contact_style
        ),
        Paragraph(
            "<b>Web:</b> www.thedailymarket.co.za",
            contact_style
        ),
    ]

    # =====================================================
    # TOP HEADER
    # =====================================================
    header_data = [
        [
            logo if logo else "",
            company_info,
            contact_info,
        ]
    ]

    header_table = Table(
        header_data,
        colWidths=[
            4 * cm,
            8 * cm,
            7 * cm,
        ],
    )

    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),

            ("ALIGN", (0, 0), (0, 0), "CENTER"),
            ("ALIGN", (1, 0), (1, 0), "LEFT"),
            ("ALIGN", (2, 0), (2, 0), "LEFT"),
        ])
    )

    elements.append(header_table)

    elements.append(Spacer(1, 5))

    # =====================================================
    # BRAND STATEMENT
    # =====================================================
    statement_table = Table(
        [
            [
                Paragraph(
                    "SUPPLYING THE PRODUCTS FOOD BUSINESSES NEED TO KEEP TRADING",
                    tagline_style
                )
            ]
        ],
        colWidths=[19 * cm],
    )

    statement_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TDM_LIGHT_GREEN),

            ("BOX", (0, 0), (-1, -1), 0.6, TDM_GREEN),

            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),

            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )

    elements.append(statement_table)

    elements.append(Spacer(1, 8))

    # =====================================================
    # PRICE LIST TITLE
    # =====================================================
    title_table = Table(
        [
            [
                Paragraph(
                    "WHOLESALE PRODUCT PRICE LIST",
                    title_style
                )
            ],
            [
                Paragraph(
                    "Quality products for the businesses that keep Gauteng fed.",
                    subtitle_style
                )
            ],
            [
                Paragraph(
                    week_label,
                    updated_style
                )
            ],
        ],
        colWidths=[19 * cm],
    )

    title_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TDM_GREEN),

            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),

            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),

            ("TOPPADDING", (0, 1), (-1, 1), 1),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 3),

            ("TOPPADDING", (0, 2), (-1, 2), 2),
            ("BOTTOMPADDING", (0, 2), (-1, 2), 7),

            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )

    elements.append(title_table)

    elements.append(Spacer(1, 10))

    # =====================================================
    # PRODUCT TABLES BY CATEGORY
    # =====================================================

    # Group products by their top-level category
    category_groups = {}

    for product in qs:
        category_name = (
            product.category.parent.name
            if product.category
            and product.category.parent
            else "Other"
        )

        if category_name not in category_groups:
            category_groups[category_name] = []

        category_groups[category_name].append(product)

    # =====================================================
    # CATEGORY SECTION STYLES
    # =====================================================

    category_title_style = ParagraphStyle(
        "CategoryTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        textColor=colors.white,
        alignment=1,
    )

    # =====================================================
    # BUILD EACH CATEGORY SECTION
    # =====================================================

    for category_name, products in category_groups.items():

        # -------------------------------------------------
        # CATEGORY SECTION HEADER
        # -------------------------------------------------
        category_header = Table(
            [
                [
                    Paragraph(
                        category_name.upper(),
                        category_title_style
                    )
                ]
            ],
            colWidths=[19 * cm],
        )

        category_header.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), TDM_GREEN),

                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),

                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ])
        )

        elements.append(category_header)

        elements.append(Spacer(1, 3))

        # -------------------------------------------------
        # TABLE DATA
        # -------------------------------------------------
        data = [
            [
                "Product No.",
                "Subcategory",
                "Product",
                "Price (Incl VAT)",
            ]
        ]

        for product in products:

            # =============================================
            # DETERMINE PRICE
            # =============================================
            #
            # If the product is on special and has a
            # special price, use that price.
            #
            # Otherwise use the cheapest active
            # wholesale supplier price.
            # =============================================

            if (
                product.is_special
                and product.special_wholesale_price_inc is not None
            ):
                price = product.special_wholesale_price_inc
                is_special_price = True

            else:
                prices = [
                    row.wholesale_price_inc
                    for row in product.pricing_rows.all()
                    if row.is_active
                    and row.wholesale_price_inc is not None
                ]

                price = min(prices) if prices else None
                is_special_price = False

            # =============================================
            # PRODUCT NAME
            # =============================================

            if is_special_price:

                special_label = (
                    product.special_label
                    or "SPECIAL"
                )

                product_display = Paragraph(
                    (
                        f'<b><font color="#0b5c39">'
                        f'★ {special_label.upper()}'
                        f'</font></b><br/>'
                        f'{product.name}'
                    ),
                    special_product_style
                )

                price_display = (
                    Paragraph(
                        f"<b>R{price:.2f}</b>",
                        special_price_style
                    )
                    if price is not None
                    else "—"
                )

            else:

                product_display = Paragraph(
                    product.name,
                    special_product_style
                )

                price_display = (
                    Paragraph(
                        f"R{price:.2f}",
                        normal_price_style
                    )
                    if price is not None
                    else "—"
                )

            # =============================================
            # ADD ROW
            # =============================================

            data.append([
                product.product_no or "—",

                (
                    product.category.name
                    if product.category
                    else "—"
                ),

                product_display,

                price_display,
            ])

        # -------------------------------------------------
        # TABLE
        # -------------------------------------------------
        table = Table(
            data,
            colWidths=[
                3 * cm,
                4 * cm,
                7 * cm,
                5 * cm,
            ],
            repeatRows=1,
        )

        table.setStyle(
            TableStyle([
                # Header
                ("BACKGROUND", (0, 0), (-1, 0), TDM_GREEN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),

                # Body
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),

                # Alternating rows
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    colors.white,
                    LIGHT_GREY,
                ]),

                # Borders
                ("GRID", (0, 0), (-1, -1), 0.35, BORDER_GREY),

                # Alignment
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),

                # Vertical alignment
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

                # Padding
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ])
        )

        elements.append(table)

        elements.append(Spacer(1, 8))

    # =====================================================
    # ORDER CTA
    # =====================================================
    cta_style = ParagraphStyle(
        "CTA",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=TDM_GREEN,
        alignment=1,
    )

    cta_sub_style = ParagraphStyle(
        "CTASub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=DARK_TEXT,
        alignment=1,
    )

    cta_table = Table(
        [
            [
                Paragraph(
                    "READY TO ORDER?",
                    cta_style
                )
            ],
            [
                Paragraph(
                    "WhatsApp us on <b>062 231 1902</b> or call <b>087 265 5488</b>",
                    cta_sub_style
                )
            ],
        ],
        colWidths=[19 * cm],
    )

    cta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TDM_LIGHT_GREEN),

            ("BOX", (0, 0), (-1, -1), 0.6, TDM_GREEN),

            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 1), (-1, 1), 2),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 5),

            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )

    elements.append(cta_table)

    # =====================================================
    # BUILD PDF
    # =====================================================
    doc.build(
        elements,
        onFirstPage=add_footer,
        onLaterPages=add_footer
    )

    return response


@login_required
@require_POST
def product_import(request):
    try:
        # STEP 1: FILE PRESENCE
        if "excel_file" not in request.FILES:
            return JsonResponse({
                "success": False,
                "step": "File check",
                "error": "No file received in request.FILES"
            }, status=400)

        # STEP 2: FORM
        form = ProductExcelUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return JsonResponse({
                "success": False,
                "step": "Form validation",
                "error": form.errors.as_json()
            }, status=400)

        # STEP 3: IMPORT LOGIC
        result = import_products_from_excel(form.cleaned_data["excel_file"])

        return JsonResponse({
            "success": True,
            "step": "Import complete",
            "data": result
        })

    except Exception as e:
        # 🔥 THIS IS THE KEY PART 🔥
        return JsonResponse({
            "success": False,
            "step": "Unhandled backend exception",
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)

# -----------------------------------------------------
# Product CRUD
# -----------------------------------------------------
# --- Custom inline formset cleaner -------------------------------------------
class VariantFormSetClean(BaseInlineFormSet):
    """
    - Silently ignore extra/blank variant rows (no pack_size, no overrides, no name/image).
    - Enforce pack_size > 0 when provided.
    - Allow blank/auto SKUs (your ProductVariant.save will auto-build the SKU anyway).
    """
    def clean(self):
        super().clean()
        for form in self.forms:
            # Skip forms already marked for deletion or invalid (avoid KeyError on cleaned_data)
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            pack_size = form.cleaned_data.get("pack_size")
            name = form.cleaned_data.get("name")
            image = form.cleaned_data.get("image")
            wh_over = form.cleaned_data.get("wholesale_price_override")
            rt_over = form.cleaned_data.get("retail_price_override")

            # 1) Entirely blank variant row? -> mark for deletion so it won't error or save
            if (
                not pack_size and not name and not image
                and not wh_over and not rt_over
            ):
                form.cleaned_data["DELETE"] = True
                continue

            # 2) If pack_size present, it must be > 0
            if pack_size is not None:
                try:
                    if Decimal(pack_size) <= 0:
                        form.add_error("pack_size", "Pack size must be greater than 0.")
                except Exception:
                    form.add_error("pack_size", "Invalid pack size.")


@login_required
# your existing @staff_required decorator
@staff_required
@transaction.atomic
def product_create(request):
    VariantFormSet3 = inlineformset_factory(
        parent_model=Product,
        model=ProductVariant,
        form=ProductVariantForm,
        formset=VariantFormSetClean,   # <<< custom cleaner to ignore blank rows/SKUs
        extra=3,                        # show three variant blocks
        can_delete=True,
    )

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)

        if form.is_valid():
            # 1) create the Product first so the formset has an instance
            product = form.save()

            # 2) bind the formset to this product instance before validating
            vfs = VariantFormSet3(
                request.POST,
                request.FILES,
                instance=product,
                prefix="variants",
            )

            if vfs.is_valid():
                vfs.save()
                messages.success(
                    request,
                    f'Product “{product.sku or "—"} {product.name}” created successfully.'
                )
                return redirect("product-view", pk=product.pk)

            # formset invalid → raise a single banner error and fall through to render
            messages.error(request, "Please fix the errors below.")
        else:
            # product form invalid → we still need an unbound formset to re-render 3 blanks
            vfs = VariantFormSet3(prefix="variants")

    else:
        form = ProductForm()
        vfs = VariantFormSet3(prefix="variants")   # three empty variant blocks

    return render(
        request,
        "products/product_create.html",
        {
            "form": form,
            "variant_formset": vfs,
        },
    )


@login_required
@staff_required
@transaction.atomic
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if request.method == "POST":
        form = ProductForm(
            request.POST,
            request.FILES,
            instance=product,
        )

        if form.is_valid():
            product = form.save()

            messages.success(request, "Product updated.")
            return redirect("product-view", pk=product.pk)

        messages.error(request, "Please fix the errors below.")

    else:
        form = ProductForm(instance=product)

    return render(
        request,
        "products/product_edit.html",
        {
            "form": form,
            "product": product,
        },
    )

@login_required
@staff_required
def variant_create(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    if request.method == "POST":
        form = ProductVariantForm(request.POST, request.FILES)
        if form.is_valid():
            variant = form.save(commit=False)
            variant.product = product
            variant.save()
            messages.success(request, f"Variant “{variant.sku}” added.")
            return redirect("product-view", pk=product.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = ProductVariantForm(initial={"uom": product.uom, "scales_with_pack": True})

    return render(request, "products/variant_form.html", {"form": form, "product": product})




@login_required
@staff_required
def variant_edit(request, pk):
    variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=pk)
    if request.method == "POST":
        form = ProductVariantForm(request.POST, request.FILES, instance=variant)
        if form.is_valid():
            form.save()
            messages.success(request, "Variant updated.")
            return redirect("product-view", pk=variant.product_id)
        messages.error(request, "Please fix the errors below.")
    else:
        form = ProductVariantForm(instance=variant)
    return render(request, "products/variant_form.html", {"form": form, "product": variant.product})



@login_required
@staff_required
def product_view(request, pk):
    """
    Product detail page with pricing rows, product variants,
    special pricing information, sales trends and market position.
    """
    from datetime import datetime, time, timedelta
    from django.db.models import Sum
    from django.utils import timezone
    from orders.models import OrderItem

    # -----------------------------------------------------
    # Product
    # -----------------------------------------------------
    product = get_object_or_404(
        Product.objects.select_related("category"),
        pk=pk
    )

    # -----------------------------------------------------
    # Pricing rows
    # -----------------------------------------------------
    pricing_rows = list(
        ProductPricing.objects
        .filter(product=product)
        .select_related("supplier")
        .order_by("id")
    )

    pricing_rows.sort(
        key=lambda row: (
            row.supplier.name
            if row.supplier and row.supplier.name
            else "",
        )
    )

    # -----------------------------------------------------
    # Product Special
    # -----------------------------------------------------
    special = {
        "is_special": product.is_special,
        "label": product.special_label,
        "old_price": product.old_wholesale_price_inc,
        "current_price": (
            product.special_wholesale_price_inc
            if product.is_special
            and product.special_wholesale_price_inc is not None
            else product.wholesale_price_inc
        ),
        "saving": product.special_saving,
        "percentage": product.special_percentage,
    }

    # -----------------------------------------------------
    # Variants
    # -----------------------------------------------------
    variants = (
        product.variants
        .all()
        .order_by("pack_size", "id")
    )

    variant_rows = []

    for v in variants:
        wholesale_derived = v.price_for_channel("wholesale")
        retail_derived = v.price_for_channel("retail")

        variant_rows.append({
            "id": v.id,
            "name": v.name or f"{v.pack_size} {v.get_uom_display()}",
            "sku": v.sku,
            "pack_size": v.pack_size,
            "uom": v.get_uom_display(),
            "scales_with_pack": v.scales_with_pack,
            "wholesale_override": v.wholesale_price_override,
            "retail_override": v.retail_price_override,
            "wholesale_derived": wholesale_derived,
            "retail_derived": retail_derived,
            "image_url": v.image.url if v.image else None,
        })

    # -----------------------------------------------------
    # Product Trends & Market Position
    # -----------------------------------------------------

    period_options = [
        (7, "Last 7 days"),
        (30, "Last 30 days"),
        (90, "Last 90 days"),
        (180, "Last 6 months"),
        (365, "Last 12 months"),
    ]

    allowed_periods = {
        days for days, _label in period_options
    }

    try:
        trend_days = int(request.GET.get("trend_period", "30"))
    except (TypeError, ValueError):
        trend_days = 30

    if trend_days not in allowed_periods:
        trend_days = 30

    # -----------------------------------------------------
    # Reporting period
    # -----------------------------------------------------

    today = timezone.localdate()
    trend_start = today - timedelta(days=trend_days - 1)

    current_tz = timezone.get_current_timezone()

    # Start at midnight on the first reporting day.
    trend_start_dt = timezone.make_aware(
        datetime.combine(trend_start, time.min),
        current_tz
    )

    # Exclusive end: midnight immediately after today.
    trend_end_dt = timezone.make_aware(
        datetime.combine(today + timedelta(days=1), time.min),
        current_tz
    )

    # -----------------------------------------------------
    # Completed sales only
    #
    # IMPORTANT:
    # Use datetime comparisons instead of __date lookups.
    # This avoids MySQL CONVERT_TZ() date conversion.
    # -----------------------------------------------------

    completed_items = OrderItem.objects.filter(
        order__status="complete",
        order__order_date__gte=trend_start_dt,
        order__order_date__lt=trend_end_dt,
    )

    # -----------------------------------------------------
    # Individual product sales
    # -----------------------------------------------------

    product_items = list(
        completed_items
        .filter(product_id=product.pk)
        .select_related("order")
        .only(
            "quantity",
            "unit_price_excl",
            "discount_excl",
            "vat_percent",
            "order__order_date",
        )
    )

    total_units_sold = Decimal("0.00")
    total_sales_value = Decimal("0.00")

    # Daily points for short periods;
    # weekly points for longer periods.
    use_daily_buckets = trend_days <= 30

    bucket_totals = {}

    for item in product_items:
        quantity = item.quantity or Decimal("0.00")

        total_units_sold += quantity
        total_sales_value += item.line_total_inc

        order_day = timezone.localtime(
            item.order.order_date
        ).date()

        if use_daily_buckets:
            bucket_date = order_day
        else:
            days_from_start = (
                order_day - trend_start
            ).days

            bucket_date = (
                trend_start
                + timedelta(days=(days_from_start // 7) * 7)
            )

        bucket_totals[bucket_date] = (
            bucket_totals.get(
                bucket_date,
                Decimal("0.00")
            ) + quantity
        )

    # -----------------------------------------------------
    # Chart data
    # -----------------------------------------------------

    trend_labels = []
    trend_units = []

    if use_daily_buckets:
        bucket_date = trend_start

        while bucket_date <= today:
            trend_labels.append(
                bucket_date.strftime("%d %b")
            )

            trend_units.append(
                float(
                    bucket_totals.get(
                        bucket_date,
                        Decimal("0.00")
                    )
                )
            )

            bucket_date += timedelta(days=1)

    else:
        bucket_date = trend_start

        while bucket_date <= today:
            trend_labels.append(
                bucket_date.strftime("%d %b")
            )

            trend_units.append(
                float(
                    bucket_totals.get(
                        bucket_date,
                        Decimal("0.00")
                    )
                )
            )

            bucket_date += timedelta(days=7)

    # -----------------------------------------------------
    # Product ranking
    # -----------------------------------------------------

    def build_product_ranking(queryset):
        ranking = list(
            queryset
            .values("product_id", "product__name")
            .annotate(
                units_sold=Sum("quantity")
            )
            .order_by(
                "-units_sold",
                "product__name"
            )
        )

        product_rank = None

        for position, row in enumerate(ranking, start=1):
            row["rank"] = position

            if row["product_id"] == product.pk:
                product_rank = position

        return ranking, product_rank

    # -----------------------------------------------------
    # Category ranking
    # -----------------------------------------------------

    category_items = completed_items

    if product.category_id:
        category_items = category_items.filter(
            product__category_id=product.category_id
        )

        category_ranking, category_rank = (
            build_product_ranking(category_items)
        )
    else:
        category_ranking = []
        category_rank = None

    # -----------------------------------------------------
    # Overall ranking
    # -----------------------------------------------------

    overall_ranking, overall_rank = (
        build_product_ranking(completed_items)
    )

    # -----------------------------------------------------
    # Top 5 products
    # -----------------------------------------------------

    category_top_products = category_ranking[:5]
    overall_top_products = overall_ranking[:5]

    # -----------------------------------------------------
    # Product trend context
    # -----------------------------------------------------

    product_trend = {
        "period_days": trend_days,

        "total_units_sold": total_units_sold,
        "total_sales_value": total_sales_value,

        "category_rank": category_rank,
        "category_product_count": len(category_ranking),

        "overall_rank": overall_rank,
        "overall_product_count": len(overall_ranking),

        "trend_labels_json": __import__("json").dumps(
            trend_labels
        ),

        "trend_units_json": __import__("json").dumps(
            trend_units
        ),

        "category_top_products": category_top_products,
        "overall_top_products": overall_top_products,
    }

    # -----------------------------------------------------
    # Render
    # -----------------------------------------------------

    return render(
        request,
        "products/product_view.html",
        {
            "product": product,
            "pricing_rows": pricing_rows,
            "variant_rows": variant_rows,
            "special": special,
            "product_trend": product_trend,
            "trend_period_options": period_options,
        },
    )




# -----------------------------------------------------
# ProductPricing CRUD
# -----------------------------------------------------

@login_required
@staff_required
def product_pricing_list(request, product_id: int):
    """
    Simple redirect so the existing URL keeps working.
    If you want a dedicated pricing list page later, render a template here.
    """
    return redirect("product-view", pk=product_id)



@login_required
@staff_required
def product_pricing_edit(request, pricing_id):
    row = get_object_or_404(
        ProductPricing.objects.select_related("product", "supplier"),
        pk=pricing_id
    )
    product = row.product

    if request.method == "POST":
        form = ProductPricingForm(request.POST, instance=row, product=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier pricing updated.")
            return redirect("product-view", pk=product.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = ProductPricingForm(instance=row, product=product)

    return render(
        request,
        "products/product_pricing_edit.html",
        {"form": form, "row": row, "product": product}
    )



@login_required
@staff_required
def product_pricing_create(request, product_id):
    product = get_object_or_404(Product, pk=product_id)

    if request.method == "POST":
        # bind an instance with product set so model.clean() can read it during validation
        instance = ProductPricing(product=product)
        form = ProductPricingForm(request.POST, product=product, instance=instance)
        if form.is_valid():
            form.save()  # product is already on instance
            messages.success(request, "Pricing created.")
            return redirect(reverse("product-view", args=[product.id]))
    else:
        # also provide instance on GET so widgets, qs filters, etc. can use it
        form = ProductPricingForm(product=product, instance=ProductPricing(product=product))

    return render(
        request,
        "products/product_pricing_form.html",
        {"form": form, "product": product},
    )



@staff_required
@login_required
def product_pricing_edit(request, pk):
    pp = get_object_or_404(ProductPricing, pk=pk)
    product = pp.product

    if request.method == "POST":
        form = ProductPricingForm(request.POST, instance=pp, product=product)
        if form.is_valid():
            form.save()                    # product already set on instance
            messages.success(request, "Pricing updated.")
            return redirect("product-view", product.id)
    else:
        form = ProductPricingForm(instance=pp, product=product)

    return render(request, "products/product_pricing_form.html", {
        "product": product,
        "form": form,
        "mode": "edit",
        "pricing": pp,
    })


@login_required
@staff_required
def product_dashboard(request):
    """Product catalogue, pricing and supplier intelligence dashboard.

    Dashboard-wide KPI figures are based on the complete catalogue.
    Search/category/pricing filters apply to the product register table.
    Only active ProductPricing rows are treated as current supplier pricing.
    """
    from collections import defaultdict
    from decimal import Decimal

    q = (request.GET.get("q") or "").strip()
    category_id = (request.GET.get("category") or "").strip()
    pricing_status = (request.GET.get("pricing_status") or "").strip()
    supplier_id = (request.GET.get("supplier") or "").strip()

    base_products = Product.objects.all()
    active_pricing = ProductPricing.objects.filter(is_active=True)

    active_pricing_for_product = ProductPricing.objects.filter(
        product_id=OuterRef("pk"),
        is_active=True,
    )

    # -----------------------------------------------------------------
    # Catalogue health KPIs (whole catalogue)
    # -----------------------------------------------------------------
    total_products = base_products.count()
    products_with_pricing = base_products.filter(
        Exists(active_pricing_for_product)
    ).count()
    products_without_pricing = total_products - products_with_pricing
    products_without_images = base_products.filter(
        Q(image__isnull=True) | Q(image="")
    ).count()

    total_categories = Category.objects.count()
    top_level_categories = Category.objects.filter(parent__isnull=True).count()
    subcategories = Category.objects.filter(parent__isnull=False).count()

    products_with_variants = base_products.filter(
        Exists(ProductVariant.objects.filter(product_id=OuterRef("pk")))
    ).count()
    products_with_multiple_suppliers = 0

    # Pricing statistics. This is a markup percentage, not gross margin.
    pricing_summary = active_pricing.aggregate(
        avg_supplier_price=Avg("supplier_price_excl"),
        avg_wholesale_markup=Avg("wholesale_margin_percent"),
    )
    avg_supplier_price = pricing_summary["avg_supplier_price"]
    avg_wholesale_markup = pricing_summary["avg_wholesale_markup"]

    # -----------------------------------------------------------------
    # Active pricing rows loaded once for supplier comparisons and counts
    # -----------------------------------------------------------------
    pricing_rows = list(
        active_pricing.select_related("product", "supplier")
        .only(
            "id", "product_id", "supplier_id", "supplier_price_excl",
            "supplier_vat_percent", "wholesale_margin_percent",
            "wholesale_vat_percent", "retail_margin_percent",
            "retail_vat_percent", "is_active", "updated_at",
            "product__id", "product__name", "product__product_no",
            "supplier__id", "supplier__name",
        )
    )
    pricing_by_product = defaultdict(list)
    for row in pricing_rows:
        pricing_by_product[row.product_id].append(row)

    for rows in pricing_by_product.values():
        supplier_ids = {row.supplier_id for row in rows if row.supplier_id}
        if len(supplier_ids) > 1:
            products_with_multiple_suppliers += 1

    # -----------------------------------------------------------------
    # Top 10 best-selling products (completed orders only)
    # -----------------------------------------------------------------
    from django.db.models import Sum
    from orders.models import OrderItem

    sales_period_options = [
        (7, "Last 7 days"),
        (14, "Last 14 days"),
        (30, "Last 30 days"),
        (60, "Last 60 days"),
        (90, "Last 90 days"),
    ]
    try:
        sales_period_days = int(request.GET.get("sales_period", "7"))
    except (TypeError, ValueError):
        sales_period_days = 7
    if sales_period_days not in {7, 14, 30, 60, 90}:
        sales_period_days = 7

    sales_period_start = timezone.now() - timedelta(days=sales_period_days)

    # "Sold" means the order has reached complete status. Cancelled,
    # returned, pending and in-progress orders are not counted as sales.
    top_product_totals = list(
        OrderItem.objects.filter(
            order__status="complete",
            order__order_date__gte=sales_period_start,
        )
        .values("product_id")
        .annotate(quantity_sold=Sum("quantity"))
        .order_by("-quantity_sold", "product_id")[:10]
    )

    top_product_ids = [row["product_id"] for row in top_product_totals]
    sales_items_by_product = defaultdict(list)
    if top_product_ids:
        sales_items = (
            OrderItem.objects.filter(
                order__status="complete",
                order__order_date__gte=sales_period_start,
                product_id__in=top_product_ids,
            )
            .select_related("product")
        )
        for item in sales_items:
            sales_items_by_product[item.product_id].append(item)

    top_selling_products = []
    for total_row in top_product_totals:
        product_id = total_row["product_id"]
        items = sales_items_by_product.get(product_id, [])
        if not items:
            continue

        product = items[0].product
        quantity_sold = sum(
            (item.quantity or Decimal("0.00")) for item in items
        )
        total_sales_inc = sum(
            (item.line_total_inc or Decimal("0.00")) for item in items
        )
        average_selling_price_inc = (
            total_sales_inc / quantity_sold
            if quantity_sold else None
        )

        # Compare actual discounted selling price with the current lowest
        # active wholesale price (including VAT). This is not a historical
        # wholesale-cost snapshot.
        current_wholesale_price_inc = None
        if product.is_special and product.special_wholesale_price_inc is not None:
            current_wholesale_price_inc = product.special_wholesale_price_inc
        else:
            current_prices = [
                row.wholesale_price_inc
                for row in pricing_by_product.get(product_id, [])
                if row.wholesale_price_inc is not None
            ]
            if current_prices:
                current_wholesale_price_inc = min(current_prices)

        price_difference_inc = None
        price_difference_total_inc = None
        if (
            average_selling_price_inc is not None
            and current_wholesale_price_inc is not None
        ):
            price_difference_inc = (
                average_selling_price_inc - current_wholesale_price_inc
            )
            price_difference_total_inc = (
                price_difference_inc * quantity_sold
            )

        top_selling_products.append({
            "product": product,
            "quantity_sold": quantity_sold,
            "total_sales_inc": total_sales_inc,
            "average_selling_price_inc": average_selling_price_inc,
            "current_wholesale_price_inc": current_wholesale_price_inc,
            "price_difference_inc": price_difference_inc,
            "price_difference_total_inc": price_difference_total_inc,
        })

    # -----------------------------------------------------------------
    # Product knowledge overview
    # -----------------------------------------------------------------
    knowledge_qs = ProductKnowledge.objects.select_related("product")
    knowledge_records = list(knowledge_qs)
    knowledge_total = len(knowledge_records)
    knowledge_complete = sum(
        1 for item in knowledge_records
        if (item.completion_percentage or 0) >= 100
    )
    knowledge_incomplete = knowledge_total - knowledge_complete
    knowledge_approved = sum(1 for item in knowledge_records if item.is_approved)
    knowledge_completion_rate = (
        round((knowledge_complete / knowledge_total) * 100)
        if knowledge_total else 0
    )

    # -----------------------------------------------------------------
    # Category breakdown (counts are based on active supplier pricing)
    # -----------------------------------------------------------------
    category_breakdown = list(
        Category.objects.select_related("parent").prefetch_related("products")
    )
    for category in category_breakdown:
        category_products = list(category.products.all())
        category.product_count = len(category_products)
        category.priced_product_count = sum(
            1 for product in category_products
            if pricing_by_product.get(product.pk)
        )
        category.missing_pricing_count = (
            category.product_count - category.priced_product_count
        )

        # Average category pricing is calculated from active supplier pricing
        # rows. Derived model properties include VAT and are not DB fields.
        category_rows = [
            row
            for product in category_products
            for row in pricing_by_product.get(product.pk, [])
            if row.is_active
        ]
        supplier_costs = [row.supplier_price_incl for row in category_rows]
        wholesale_prices = [row.wholesale_price_inc for row in category_rows]
        retail_prices = [row.retail_price_inc for row in category_rows]

        category.avg_supplier_price_inc = (
            sum(supplier_costs, Decimal("0.00")) / len(supplier_costs)
            if supplier_costs else None
        )
        category.avg_wholesale_price_inc = (
            sum(wholesale_prices, Decimal("0.00")) / len(wholesale_prices)
            if wholesale_prices else None
        )
        category.avg_retail_price_inc = (
            sum(retail_prices, Decimal("0.00")) / len(retail_prices)
            if retail_prices else None
        )
    category_breakdown.sort(key=lambda item: (
        item.parent.name if item.parent else "",
        item.name or "",
    ))

    # -----------------------------------------------------------------
    # Action lists: missing active pricing and missing product images
    # -----------------------------------------------------------------
    pricing_alerts = list(
        base_products.select_related("category", "category__parent")
        .filter(~Exists(active_pricing_for_product))
        .order_by("name")[:20]
    )
    image_alerts = list(
        base_products.select_related("category", "category__parent")
        .filter(Q(image__isnull=True) | Q(image=""))
        .order_by("name")[:20]
    )

    # -----------------------------------------------------------------
    # Supplier price comparison: active prices only
    # -----------------------------------------------------------------
    supplier_comparison = []
    for product_id, rows in pricing_by_product.items():
        supplier_map = {}
        for row in rows:
            if row.supplier_id and row.supplier_price_excl is not None:
                # If multiple active rows exist for one supplier, show the
                # lowest recorded active supplier cost for comparison.
                current = supplier_map.get(row.supplier_id)
                if current is None or row.supplier_price_excl < current["price"]:
                    supplier_map[row.supplier_id] = {
                        "name": row.supplier.name,
                        "price": row.supplier_price_excl,
                    }
        if len(supplier_map) < 2:
            continue
        prices = [entry["price"] for entry in supplier_map.values()]
        product = rows[0].product
        supplier_comparison.append({
            "product": product,
            "supplier_count": len(supplier_map),
            "min_supplier_price": min(prices),
            "max_supplier_price": max(prices),
            "price_difference": max(prices) - min(prices),
            "suppliers": sorted(supplier_map.values(), key=lambda item: item["price"]),
        })
    supplier_comparison.sort(
        key=lambda item: item["price_difference"], reverse=True
    )
    supplier_comparison = supplier_comparison[:15]

    # -----------------------------------------------------------------
    # Recent additions and supplier price changes
    # -----------------------------------------------------------------
    recent_products = (
        Product.objects.select_related("category")
        .order_by("-created_at")[:8]
    )
    recent_pricing_updates = (
        ProductPricing.objects.select_related("product", "supplier")
        .order_by("-updated_at")[:10]
    )

    # -----------------------------------------------------------------
    # Filtered product register
    # -----------------------------------------------------------------
    filtered_qs = (
        Product.objects.select_related("category", "category__parent")
        .prefetch_related("pricing_rows", "variants")
    )
    if q:
        filtered_qs = filtered_qs.filter(
            Q(name__icontains=q)
            | Q(sku__icontains=q)
            | Q(product_no__icontains=q)
            | Q(category__name__icontains=q)
            | Q(category__parent__name__icontains=q)
        )
    if category_id:
        filtered_qs = filtered_qs.filter(category_id=category_id)
    if pricing_status == "missing":
        filtered_qs = filtered_qs.filter(~Exists(active_pricing_for_product))
    elif pricing_status == "has_pricing":
        filtered_qs = filtered_qs.filter(Exists(active_pricing_for_product))
    if supplier_id:
        selected_supplier_pricing = ProductPricing.objects.filter(
            product_id=OuterRef("pk"),
            supplier_id=supplier_id,
            is_active=True,
        )
        filtered_qs = filtered_qs.filter(Exists(selected_supplier_pricing))

    filtered_products = list(filtered_qs.order_by("name")[:100])
    for product in filtered_products:
        rows = [row for row in product.pricing_rows.all() if row.is_active]
        product.dashboard_pricing_count = len(rows)
        product.dashboard_supplier_count = len({
            row.supplier_id for row in rows if row.supplier_id
        })
        product.dashboard_variant_count = len(product.variants.all())
        product.dashboard_lowest_wholesale = min(
            (row.wholesale_price_inc for row in rows
             if row.wholesale_price_inc is not None),
            default=None,
        )

    categories = list(
        Category.objects.filter(parent__isnull=False)
        .select_related("parent").order_by("name")
    )
    categories.sort(key=lambda item: (
        item.parent.name if item.parent else "", item.name or ""
    ))

    suppliers = Supplier.objects.order_by("name")

    context = {
        "q": q,
        "category_id": category_id,
        "pricing_status": pricing_status,
        "supplier_id": supplier_id,
        "total_products": total_products,
        "products_with_pricing": products_with_pricing,
        "products_without_pricing": products_without_pricing,
        "products_without_images": products_without_images,
        "total_categories": total_categories,
        "top_level_categories": top_level_categories,
        "subcategories": subcategories,
        "products_with_variants": products_with_variants,
        "products_with_multiple_suppliers": products_with_multiple_suppliers,
        "avg_supplier_price": avg_supplier_price,
        "avg_wholesale_markup": avg_wholesale_markup,
        "category_breakdown": category_breakdown,
        "pricing_alerts": pricing_alerts,
        "image_alerts": image_alerts,
        "supplier_comparison": supplier_comparison,
        "recent_products": recent_products,
        "recent_pricing_updates": recent_pricing_updates,
        "filtered_products": filtered_products,
        "categories": categories,
        "suppliers": suppliers,
        "sales_period_days": sales_period_days,
        "sales_period_options": sales_period_options,
        "top_selling_products": top_selling_products,
        "knowledge_total": knowledge_total,
        "knowledge_complete": knowledge_complete,
        "knowledge_incomplete": knowledge_incomplete,
        "knowledge_approved": knowledge_approved,
        "knowledge_completion_rate": knowledge_completion_rate,
        "filtered_product_limit": 100,
    }
    return render(request, "products/product_dashboard.html", context)


# =============================================================
# PROCUREMENT
# =============================================================

@login_required
@staff_required
def procurement_list(request):
    qs = (
        Procurement.objects
        .select_related("created_by", "approved_by")
        .prefetch_related("items__product", "purchase_orders")
        .order_by("-procurement_date", "-id")
    )

    status = (request.GET.get("status") or "").strip()
    wave = (request.GET.get("wave") or "").strip()
    search = (request.GET.get("search") or "").strip()

    if status:
        qs = qs.filter(status=status)
    if wave:
        qs = qs.filter(wave=wave)
    if search:
        qs = qs.filter(
            Q(procurement_number__icontains=search)
            | Q(notes__icontains=search)
        )

    return render(
        request,
        "products/procurement_list.html",
        {
            "procurements": qs,
            "status_choices": Procurement.STATUS_CHOICES,
            "wave_choices": Procurement.WAVE_CHOICES,
            "selected_status": status,
            "selected_wave": wave,
            "search": search,
            "current": "procurement-list",
        },
    )


@login_required
@staff_required
@transaction.atomic
def procurement_create(request):
    ProcurementForm = modelform_factory(
        Procurement,
        fields=[
            "procurement_number",
            "procurement_date",
            "wave",
            "status",
            "created_by",
            "notes",
        ],
    )
    ProcurementItemFormSet = inlineformset_factory(
        Procurement,
        ProcurementItem,
        fields=["product", "required_quantity", "notes"],
        extra=5,
        can_delete=True,
    )

    if request.method == "POST":
        form = ProcurementForm(request.POST)
        formset = ProcurementItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            procurement = form.save(commit=False)

            if not procurement.procurement_number:
                procurement.procurement_number = (
                    f"PROC-{procurement.procurement_date:%Y%m%d}-"
                    f"{procurement.wave.upper()}"
                )

            if not procurement.created_by_id:
                procurement.created_by = request.user

            procurement.save()
            formset.instance = procurement
            formset.save()

            messages.success(
                request,
                f"Procurement {procurement.procurement_number} created successfully.",
            )
            return redirect("procurement-view", pk=procurement.pk)

        messages.error(request, "Please fix the errors below.")

    else:
        form = ProcurementForm(
            initial={
                "procurement_date": timezone.localdate(),
                "wave": "AM",
                "status": "draft",
                "created_by": request.user,
            }
        )
        formset = ProcurementItemFormSet()

    return render(
        request,
        "products/procurement_form.html",
        {"form": form, "formset": formset, "current": "procurement-create"},
    )


@login_required
@staff_required
def procurement_view(request, pk):
    procurement = get_object_or_404(
        Procurement.objects
        .select_related("created_by", "approved_by")
        .prefetch_related("items__product", "purchase_orders__supplier"),
        pk=pk,
    )
    return render(
        request,
        "products/procurement_view.html",
        {"procurement": procurement, "current": "procurement-view"},
    )


# =============================================================
# PURCHASE ORDERS
# =============================================================

@login_required
@staff_required
def purchase_order_list(request):
    qs = (
        PurchaseOrder.objects
        .select_related(
            "procurement",
            "supplier",
            "created_by",
            "approved_by",
        )
        .prefetch_related("items__product")
        .order_by("-order_date", "-id")
    )

    status = (request.GET.get("status") or "").strip()
    supplier_id = (request.GET.get("supplier") or "").strip()
    search = (request.GET.get("search") or "").strip()

    if status:
        qs = qs.filter(status=status)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if search:
        qs = qs.filter(
            Q(po_number__icontains=search)
            | Q(supplier_reference__icontains=search)
            | Q(procurement__procurement_number__icontains=search)
            | Q(supplier__name__icontains=search)
        )

    return render(
        request,
        "products/purchase_order_list.html",
        {
            "purchase_orders": qs,
            "status_choices": PurchaseOrder.STATUS_CHOICES,
            "suppliers": Supplier.objects.order_by("name"),
            "selected_status": status,
            "selected_supplier": supplier_id,
            "search": search,
            "current": "purchase-order-list",
        },
    )


@login_required
@staff_required
@transaction.atomic
def purchase_order_create(request):
    PurchaseOrderForm = modelform_factory(
        PurchaseOrder,
        fields=[
            "po_number",
            "procurement",
            "supplier",
            "order_date",
            "expected_delivery_date",
            "status",
            "supplier_reference",
            "created_by",
            "notes",
        ],
    )
    PurchaseOrderItemFormSet = inlineformset_factory(
        PurchaseOrder,
        PurchaseOrderItem,
        fields=[
            "procurement_item",
            "product",
            "ordered_quantity",
            "expected_unit_cost_excl",
            "notes",
        ],
        extra=5,
        can_delete=True,
    )

    procurement_id = request.GET.get("procurement")

    if request.method == "POST":
        form = PurchaseOrderForm(request.POST)
        formset = PurchaseOrderItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            purchase_order = form.save(commit=False)

            if not purchase_order.po_number:
                date_part = purchase_order.order_date.strftime("%Y%m%d")
                prefix = f"PO-{date_part}-"
                number = (
                    PurchaseOrder.objects
                    .filter(po_number__startswith=prefix)
                    .count()
                    + 1
                )
                purchase_order.po_number = f"{prefix}{number:04d}"

                while PurchaseOrder.objects.filter(
                    po_number=purchase_order.po_number
                ).exists():
                    number += 1
                    purchase_order.po_number = f"{prefix}{number:04d}"

            if not purchase_order.created_by_id:
                purchase_order.created_by = request.user

            purchase_order.save()
            formset.instance = purchase_order
            formset.save()

            messages.success(
                request,
                f"Purchase Order {purchase_order.po_number} created successfully.",
            )
            return redirect("purchase-order-view", pk=purchase_order.pk)

        messages.error(request, "Please fix the errors below.")

    else:
        form = PurchaseOrderForm(
            initial={
                "procurement": procurement_id or None,
                "order_date": timezone.localdate(),
                "status": "draft",
                "created_by": request.user,
            }
        )
        formset = PurchaseOrderItemFormSet()

    return render(
        request,
        "products/purchase_order_form.html",
        {"form": form, "formset": formset, "current": "purchase-order-create"},
    )


@login_required
@staff_required
def purchase_order_view(request, pk):
    purchase_order = get_object_or_404(
        PurchaseOrder.objects
        .select_related(
            "procurement",
            "supplier",
            "created_by",
            "approved_by",
        )
        .prefetch_related("items__product", "items__procurement_item"),
        pk=pk,
    )
    return render(
        request,
        "products/purchase_order_view.html",
        {"purchase_order": purchase_order, "current": "purchase-order-view"},
    )
