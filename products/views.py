# products/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db.models import Q, Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from suppliers.models import Supplier
from .models import Product, Category, ProductPricing
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

    price_list_subcategories = Category.objects.filter(
        is_active=True,
        parent__isnull=False
    ).select_related("parent").order_by("parent__name", "name")

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
        .order_by(
            "product__product_no",
            "product__name",
        )
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

    # -----------------------------------------------------
    # Categories
    # -----------------------------------------------------

    categories = (
        Category.objects
        .filter(
            products__isnull=False
        )
        .distinct()
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

    knowledge_records = (
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
        .order_by(
            "product__product_no",
            "product__name",
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
        .order_by(
            "category__parent__name",
            "product_no",
        )
    )

    if subcategory_ids:
        qs = qs.filter(category_id__in=subcategory_ids)

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
            "<b>WhatsApp Orders:</b> 064 458 7575",
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
                    "WhatsApp us on <b>064 458 7575</b> or call <b>087 265 5488</b>",
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
    and special pricing information.
    """
    product = get_object_or_404(
        Product.objects.select_related("category"),
        pk=pk
    )

    # -----------------------------------------------------
    # Pricing rows
    # -----------------------------------------------------
    pricing_rows = (
        ProductPricing.objects
        .filter(product=product)
        .select_related("supplier")
        .order_by("supplier__name")
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

    return render(
        request,
        "products/product_view.html",
        {
            "product": product,
            "pricing_rows": pricing_rows,
            "variant_rows": variant_rows,
            "special": special,
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
    q = (request.GET.get("q") or "").strip()
    category_id = request.GET.get("category") or ""
    pricing_status = request.GET.get("pricing_status") or ""

    products_qs = (
        Product.objects
        .select_related("category", "category__parent")
        .prefetch_related("pricing_rows", "variants")
        .all()
    )

    if q:
        products_qs = products_qs.filter(
            Q(name__icontains=q) |
            Q(sku__icontains=q) |
            Q(product_no__icontains=q) |
            Q(category__name__icontains=q) |
            Q(category__parent__name__icontains=q)
        )

    if category_id:
        products_qs = products_qs.filter(category_id=category_id)

    if pricing_status == "missing":
        products_qs = products_qs.filter(pricing_rows__isnull=True)

    elif pricing_status == "has_pricing":
        products_qs = products_qs.filter(pricing_rows__isnull=False)

    products_qs = products_qs.distinct()

    total_products = Product.objects.count()
    products_with_pricing = (
        Product.objects
        .filter(pricing_rows__isnull=False)
        .distinct()
        .count()
    )
    products_without_pricing = (
        Product.objects
        .filter(pricing_rows__isnull=True)
        .distinct()
        .count()
    )
    products_without_images = (
        Product.objects
        .filter(Q(image__isnull=True) | Q(image=""))
        .count()
    )

    total_categories = Category.objects.count()
    top_level_categories = Category.objects.filter(parent__isnull=True).count()
    subcategories = Category.objects.filter(parent__isnull=False).count()

    active_pricing_rows = ProductPricing.objects.filter(is_active=True)

    avg_supplier_price = active_pricing_rows.aggregate(
        avg_supplier_price=Avg("supplier_price_excl")
    )["avg_supplier_price"]

    avg_wholesale_margin = active_pricing_rows.aggregate(
        avg_wholesale_margin=Avg("wholesale_margin_percent")
    )["avg_wholesale_margin"]

    avg_wholesale_margin = active_pricing_rows.aggregate(
        avg_wholesale_margin=Avg("wholesale_margin_percent")
    )["avg_wholesale_margin"]

    products_with_variants = (
        Product.objects
        .filter(variants__isnull=False)
        .distinct()
        .count()
    )

    products_without_variants = (
        Product.objects
        .filter(variants__isnull=True)
        .distinct()
        .count()
    )

    products_with_multiple_suppliers = (
        Product.objects
        .annotate(supplier_count=Count("pricing_rows__supplier", distinct=True))
        .filter(supplier_count__gt=1)
        .count()
    )

    category_breakdown = (
        Category.objects
        .annotate(
            product_count=Count("products", distinct=True),
            pricing_count=Count("products__pricing_rows", distinct=True),
            variant_count=Count("products__variants", distinct=True),
        )
        .order_by("parent__name", "name")
    )

    pricing_alerts = (
        Product.objects
        .select_related("category", "category__parent")
        .filter(pricing_rows__isnull=True)
        .order_by("category__parent__name", "category__name", "name")[:20]
    )

    image_alerts = (
        Product.objects
        .select_related("category", "category__parent")
        .filter(Q(image__isnull=True) | Q(image=""))
        .order_by("category__parent__name", "category__name", "name")[:20]
    )

    supplier_comparison = (
        Product.objects
        .annotate(
            supplier_count=Count("pricing_rows__supplier", distinct=True),
            min_supplier_price=Min("pricing_rows__supplier_price_excl"),
            max_supplier_price=Max("pricing_rows__supplier_price_excl"),
        )
        .filter(supplier_count__gt=1)
        .order_by("-supplier_count", "name")[:20]
    )

    recent_products = (
        Product.objects
        .select_related("category", "category__parent")
        .order_by("-created_at")[:10]
    )

    recent_pricing_updates = (
        ProductPricing.objects
        .select_related("product", "supplier", "product__category")
        .order_by("-updated_at")[:10]
    )

    filtered_products = (
        products_qs
        .annotate(
            pricing_count=Count("pricing_rows", distinct=True),
            variant_count=Count("variants", distinct=True),
            supplier_count=Count("pricing_rows__supplier", distinct=True),
        )
        .order_by("category__parent__name", "category__name", "name")[:100]
    )

    categories = (
        Category.objects
        .filter(parent__isnull=False)
        .order_by("parent__name", "name")
    )

    ctx = {
        "q": q,
        "category_id": category_id,
        "pricing_status": pricing_status,

        "total_products": total_products,
        "products_with_pricing": products_with_pricing,
        "products_without_pricing": products_without_pricing,
        "products_without_images": products_without_images,
        "total_categories": total_categories,
        "top_level_categories": top_level_categories,
        "subcategories": subcategories,
        "products_with_variants": products_with_variants,
        "products_without_variants": products_without_variants,
        "products_with_multiple_suppliers": products_with_multiple_suppliers,

        "avg_supplier_price": avg_supplier_price,
        "avg_wholesale_margin": avg_wholesale_margin,
        "avg_wholesale_margin": avg_wholesale_margin,

        "category_breakdown": category_breakdown,
        "pricing_alerts": pricing_alerts,
        "image_alerts": image_alerts,
        "supplier_comparison": supplier_comparison,
        "recent_products": recent_products,
        "recent_pricing_updates": recent_pricing_updates,
        "filtered_products": filtered_products,
        "categories": categories,
    }

    return render(
        request,
        "products/product_dashboard.html",
        ctx
    )


