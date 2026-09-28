from datetime import timedelta
from decimal import Decimal
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from django.db import transaction
from django.db.models import (
    Avg,
    Exists,
    OuterRef,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from suppliers.models import Supplier
from products.models import (
    Product,
    ProductPricing,
    ProductKnowledge,
    Procurement,
    ProcurementItem,
    PurchaseOrder,
    PurchaseOrderItem,
)

from seshibo_site.core.access import get_user_portal_access


from products.forms import ProductExcelUploadForm, ProductForm, ProductKnowledgeForm
from products.services.product_excel_importer import import_products_from_excel

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


# ============================================================
# SUPPLY CHAIN DASHBOARD
# ============================================================

@login_required
def dashboard(request):
    access = get_user_portal_access(request.user)

    today = timezone.localdate()

    # --------------------------------------------------------
    # WEEK WINDOWS
    # Current week = Monday through today.
    # Previous comparison = the same number of elapsed days
    # from the immediately preceding week.
    # --------------------------------------------------------
    week_start = today - timedelta(days=today.weekday())
    elapsed_days = (today - week_start).days + 1

    previous_week_start = week_start - timedelta(days=7)
    previous_period_start = previous_week_start
    previous_period_end = previous_week_start + timedelta(days=elapsed_days - 1)

    # --------------------------------------------------------
    # PRODUCT CONTROL
    # --------------------------------------------------------
    total_products = Product.objects.count()

    # Match the Product Dashboard exactly:
    # a product is considered to have pricing when ANY
    # ProductPricing row exists for it, regardless of active/primary status.
    pricing_exists = ProductPricing.objects.filter(
        product_id=OuterRef("pk")
    )

    products_with_pricing = Product.objects.filter(
        Exists(pricing_exists)
    ).count()

    missing_pricing = Product.objects.filter(
        ~Exists(
            ProductPricing.objects.filter(
                product_id=OuterRef("pk")
            )
        )
    ).count()

    missing_images = Product.objects.filter(
        Q(image__isnull=True) | Q(image="")
    ).count()

    # Match the Product Dashboard exactly: average across ALL active
    # pricing rows, not only active primary rows.
    avg_wholesale_margin = ProductPricing.objects.filter(
        is_active=True
    ).aggregate(
        value=Avg("wholesale_margin_percent")
    )["value"]

    if avg_wholesale_margin is not None:
        avg_wholesale_margin = avg_wholesale_margin.quantize(
            Decimal("0.01")
        )

    # --------------------------------------------------------
    # PO VALUE EXPRESSION
    #
    # expected_total_excl is a model property, so it cannot
    # be aggregated directly by the database. Recreate the
    # calculation here for dashboard reporting.
    # --------------------------------------------------------
    po_value_expression = ExpressionWrapper(
        F("ordered_quantity") * F("expected_unit_cost_excl"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )

    def po_value(start_date, end_date, wave=None):
        qs = PurchaseOrderItem.objects.filter(
            purchase_order__procurement__procurement_date__range=(
                start_date,
                end_date,
            ),
        ).exclude(
            purchase_order__status="cancelled",
        )

        if wave:
            qs = qs.filter(
                purchase_order__procurement__wave=wave,
            )

        return (
            qs.aggregate(
                value=Sum(po_value_expression)
            )["value"]
            or Decimal("0.00")
        )

    # --------------------------------------------------------
    # PROCUREMENT / PO PULSE
    # --------------------------------------------------------
    current_po_qs = PurchaseOrder.objects.filter(
        procurement__procurement_date__range=(week_start, today)
    ).exclude(status="cancelled")

    previous_po_qs = PurchaseOrder.objects.filter(
        procurement__procurement_date__range=(
            previous_period_start,
            previous_period_end,
        )
    ).exclude(status="cancelled")

    current_po_value = po_value(week_start, today)
    previous_po_value = po_value(
        previous_period_start,
        previous_period_end,
    )

    if previous_po_value:
        po_value_change_pct = (
            (current_po_value - previous_po_value)
            / previous_po_value
            * Decimal("100")
        )
    else:
        po_value_change_pct = None

    current_po_count = current_po_qs.count()
    previous_po_count = previous_po_qs.count()

    current_procurement_qs = Procurement.objects.filter(
        procurement_date__range=(week_start, today)
    ).exclude(status="cancelled")

    previous_procurement_qs = Procurement.objects.filter(
        procurement_date__range=(
            previous_period_start,
            previous_period_end,
        )
    ).exclude(status="cancelled")

    current_procurement_count = current_procurement_qs.count()
    previous_procurement_count = previous_procurement_qs.count()

    current_procurement_item_count = ProcurementItem.objects.filter(
        procurement__procurement_date__range=(week_start, today),
        procurement__status__in=["open", "submitted", "approved", "closed"],
    ).count()

    previous_procurement_item_count = ProcurementItem.objects.filter(
        procurement__procurement_date__range=(
            previous_period_start,
            previous_period_end,
        ),
        procurement__status__in=["open", "submitted", "approved", "closed"],
    ).count()

    # --------------------------------------------------------
    # AM / PM PO VALUE
    # --------------------------------------------------------
    am_po_value = po_value(week_start, today, wave="AM")
    pm_po_value = po_value(week_start, today, wave="PM")

    total_wave_value = am_po_value + pm_po_value

    if total_wave_value:
        am_share_pct = (
            am_po_value / total_wave_value * Decimal("100")
        )
        pm_share_pct = (
            pm_po_value / total_wave_value * Decimal("100")
        )
    else:
        am_share_pct = Decimal("0.00")
        pm_share_pct = Decimal("0.00")

    # --------------------------------------------------------
    # PROCUREMENT COVERAGE
    #
    # A requirement can be split over multiple POs, therefore
    # coverage is calculated at ProcurementItem level.
    # Cancelled POs are excluded from ordered quantity.
    # --------------------------------------------------------
    coverage_items = ProcurementItem.objects.filter(
        procurement__procurement_date__range=(week_start, today),
        procurement__status__in=["open", "submitted", "approved", "closed"],
    ).annotate(
        ordered_quantity_total=Coalesce(
            Sum(
                "purchase_order_items__ordered_quantity",
                filter=~Q(
                    purchase_order_items__purchase_order__status="cancelled"
                ),
            ),
            Value(Decimal("0.00")),
        )
    )

    coverage_total = coverage_items.count()

    coverage_fully = 0
    coverage_partial = 0
    coverage_uncovered = 0

    for item in coverage_items:
        required = item.required_quantity or Decimal("0.00")
        ordered = item.ordered_quantity_total or Decimal("0.00")

        if ordered >= required:
            coverage_fully += 1
        elif ordered > 0:
            coverage_partial += 1
        else:
            coverage_uncovered += 1

    coverage_pct = (
        (
            Decimal(coverage_fully)
            / Decimal(coverage_total)
            * Decimal("100")
        )
        if coverage_total
        else Decimal("0.00")
    )

    # --------------------------------------------------------
    # CATEGORY PO VALUE - CURRENT PERIOD
    # --------------------------------------------------------
    category_rows = (
        PurchaseOrderItem.objects.filter(
            purchase_order__procurement__procurement_date__range=(
                week_start,
                today,
            ),
        )
        .exclude(purchase_order__status="cancelled")
        .values(
            "product__category__name",
        )
        .annotate(
            value=Sum(po_value_expression),
            po_count=Count(
                "purchase_order",
                distinct=True,
            ),
        )
        .order_by("-value")
    )

    category_data = [
        {
            "name": row["product__category__name"] or "Uncategorised",
            "value": float(row["value"] or 0),
            "po_count": row["po_count"],
        }
        for row in category_rows
    ]

    # --------------------------------------------------------
    # TOP PRODUCTS BY PO VALUE
    # --------------------------------------------------------
    product_rows = (
        PurchaseOrderItem.objects.filter(
            purchase_order__procurement__procurement_date__range=(
                week_start,
                today,
            ),
        )
        .exclude(purchase_order__status="cancelled")
        .values(
            "product_id",
            "product__product_no",
            "product__name",
            "product__category__name",
        )
        .annotate(
            value=Sum(po_value_expression),
            quantity=Sum("ordered_quantity"),
        )
        .order_by("-value")[:10]
    )

    top_products = [
        {
            "product_no": row["product__product_no"],
            "name": row["product__name"],
            "category": row["product__category__name"] or "Uncategorised",
            "value": float(row["value"] or 0),
            "quantity": float(row["quantity"] or 0),
        }
        for row in product_rows
    ]

    # --------------------------------------------------------
    # DAILY PO TREND - LAST 14 DAYS
    # --------------------------------------------------------
    trend_start = today - timedelta(days=13)

    trend_rows = (
        PurchaseOrderItem.objects.filter(
            purchase_order__procurement__procurement_date__range=(
                trend_start,
                today,
            ),
        )
        .exclude(purchase_order__status="cancelled")
        .values(
            "purchase_order__procurement__procurement_date",
            "purchase_order__procurement__wave",
        )
        .annotate(
            value=Sum(po_value_expression),
        )
        .order_by(
            "purchase_order__procurement__procurement_date",
            "purchase_order__procurement__wave",
        )
    )

    trend_map = {}

    for row in trend_rows:
        date_key = row[
            "purchase_order__procurement__procurement_date"
        ].isoformat()

        wave_key = row[
            "purchase_order__procurement__wave"
        ] or "OTHER"

        trend_map.setdefault(
            date_key,
            {"AM": 0.0, "PM": 0.0, "OTHER": 0.0},
        )

        trend_map[date_key][wave_key] = float(
            row["value"] or 0
        )

    trend_data = []

    for offset in range(14):
        date_value = trend_start + timedelta(days=offset)
        date_key = date_value.isoformat()

        values = trend_map.get(
            date_key,
            {"AM": 0.0, "PM": 0.0, "OTHER": 0.0},
        )

        trend_data.append(
            {
                "date": date_key,
                "label": date_value.strftime("%d %b"),
                "AM": values["AM"],
                "PM": values["PM"],
                "total": (
                    values["AM"]
                    + values["PM"]
                    + values["OTHER"]
                ),
            }
        )

    # --------------------------------------------------------
    # 4-WEEK REFERENCE
    #
    # This is intentionally a reference point rather than a
    # forecast. It gives the dashboard a basis for anticipating
    # what the next procurement cycle may look like.
    # --------------------------------------------------------
    four_week_start = week_start - timedelta(days=28)
    four_week_end = week_start - timedelta(days=1)

    four_week_po_value = po_value(
        four_week_start,
        four_week_end,
    )

    average_weekly_po_value = (
        four_week_po_value / Decimal("4")
    )

    if average_weekly_po_value:
        current_vs_4_week_avg_pct = (
            (
                current_po_value - average_weekly_po_value
            )
            / average_weekly_po_value
            * Decimal("100")
        )
    else:
        current_vs_4_week_avg_pct = None

    # --------------------------------------------------------
    # NEXT PROCUREMENT
    # --------------------------------------------------------
    next_procurement = (
        Procurement.objects
        .filter(procurement_date__gt=today)
        .exclude(status="cancelled")
        .order_by("procurement_date", "wave", "id")
        .first()
    )

    next_procurement_item_count = 0

    if next_procurement:
        next_procurement_item_count = next_procurement.items.count()

    # --------------------------------------------------------
    # ATTENTION ITEMS
    # --------------------------------------------------------
    pending_approval_count = PurchaseOrder.objects.filter(
        status="pending_approval"
    ).count()

    not_sent_count = PurchaseOrder.objects.filter(
        status="approved"
    ).count()

    overdue_delivery_count = PurchaseOrder.objects.filter(
        expected_delivery_date__lt=today,
        status__in=[
            "approved",
            "sent",
            "partially_received",
        ],
    ).count()

    context = {
        "current": "supply_chain_dashboard",

        # Product control
        "total_products": total_products,
        "products_with_pricing": products_with_pricing,
        "missing_pricing": missing_pricing,
        "missing_images": missing_images,
        "avg_wholesale_margin": avg_wholesale_margin,

        # Procurement / PO pulse
        "current_po_value": current_po_value,
        "previous_po_value": previous_po_value,
        "po_value_change_pct": po_value_change_pct,
        "current_po_count": current_po_count,
        "previous_po_count": previous_po_count,
        "current_procurement_count": current_procurement_count,
        "previous_procurement_count": previous_procurement_count,
        "current_procurement_item_count": current_procurement_item_count,
        "previous_procurement_item_count": previous_procurement_item_count,

        # AM / PM
        "am_po_value": am_po_value,
        "pm_po_value": pm_po_value,
        "am_share_pct": am_share_pct,
        "pm_share_pct": pm_share_pct,

        # Coverage
        "coverage_total": coverage_total,
        "coverage_fully": coverage_fully,
        "coverage_partial": coverage_partial,
        "coverage_uncovered": coverage_uncovered,
        "coverage_pct": coverage_pct,

        # Analysis
        "category_data": category_data,
        "top_products": top_products,
        "trend_data": trend_data,

        # Anticipation / reference
        "average_weekly_po_value": average_weekly_po_value,
        "current_vs_4_week_avg_pct": current_vs_4_week_avg_pct,
        "next_procurement": next_procurement,
        "next_procurement_item_count": next_procurement_item_count,

        # Attention
        "pending_approval_count": pending_approval_count,
        "not_sent_count": not_sent_count,
        "overdue_delivery_count": overdue_delivery_count,

        # Useful date labels for the template
        "dashboard_today": today,
        "week_start": week_start,
        "previous_period_start": previous_period_start,
        "previous_period_end": previous_period_end,

        # JSON-ready data for Chart.js / template scripts.
        "trend_data_json": json.dumps(trend_data),
        "category_data_json": json.dumps(category_data),
    }

    context.update(access)

    return render(
        request,
        "supply_chain_dashboard.html",
        context,
    )


# ============================================================
# SUPPLIERS
# ============================================================

@login_required
def suppliers_list(request):
    suppliers = (
        Supplier.objects
        .select_related("account_manager")
        .prefetch_related("categories")
        .order_by("name")
    )

    search = (request.GET.get("search") or "").strip()
    active = (request.GET.get("active") or "").strip()

    if search:
        suppliers = suppliers.filter(
            Q(code__icontains=search)
            | Q(name__icontains=search)
            | Q(contact_person__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
            | Q(whatsapp__icontains=search)
            | Q(city__icontains=search)
        )

    if active in ("0", "1"):
        suppliers = suppliers.filter(
            is_active=(active == "1")
        )

    return render(
        request,
        "suppliers_list.html",
        {
            "suppliers": suppliers,
            "search": search,
            "selected_active": active,
            "current": "supply_chain_suppliers",
        },
    )



# ============================================================
# PRODUCTS
# ============================================================

@login_required
def products_list(request):
    products = (
        Product.objects
        .select_related("category")
        .order_by("name")
    )

    search = (request.GET.get("search") or "").strip()

    if search:
        products = products.filter(
            Q(name__icontains=search)
            | Q(product_no__icontains=search)
            | Q(sku__icontains=search)
        )

    return render(
        request,
        "products_list.html",
        {
            "products": products,
            "search": search,
            "current": "supply_chain_products",
        },
    )


@login_required
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects
        .select_related("category", "category__parent")
        .prefetch_related("pricing_rows__supplier"),
        pk=pk,
    )

    pricing_rows = product.pricing_rows.all().order_by(
        "-is_primary",
        "-is_active",
        "supplier__name",
    )
    knowledge = ProductKnowledge.objects.filter(product=product).first()

    return render(
        request,
        "product_detail.html",
        {
            "product": product,
            "pricing_rows": pricing_rows,
            "knowledge": knowledge,
            "current": "supply_chain_products",
        },
    )


@login_required
@transaction.atomic
def product_edit(request, pk):
    """
    Supply Chain product edit view.

    This uses the existing ProductForm and product edit template, but
    keeps the request inside the Supply Chain URL namespace.
    """
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
            return redirect(
                "supply_chain:supply-chain-product-detail",
                pk=product.pk,
            )

        messages.error(request, "Please fix the errors below.")
    else:
        form = ProductForm(instance=product)

    return render(
        request,
        "product_edit.html",
        {
            "form": form,
            "product": product,
        },
    )


@login_required
def product_knowledge(request, pk):
    """
    Supply Chain Product Knowledge view.

    This uses the existing ProductKnowledge view data and template,
    but is reached directly from the Supply Chain URL namespace.
    """
    product = get_object_or_404(
        Product.objects.select_related("category"),
        pk=pk,
    )

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
        product=product,
    )

    return render(
        request,
        "product_knowledge.html",
        {
            "knowledge": knowledge,
            "product": knowledge.product,
            "current": "supply-chain-product-knowledge",
        },
    )


@login_required
def product_knowledge_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)

    knowledge = get_object_or_404(
        ProductKnowledge.objects.select_related("product"),
        product=product,
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
                "supply_chain:product-knowledge-view",
                pk=product.pk,
            )

    else:
        form = ProductKnowledgeForm(
            instance=knowledge,
        )

    return render(
        request,
        "product_knowledge_edit.html",
        {
            "knowledge": knowledge,
            "product": product,
            "form": form,
            "current": "product-knowledge-edit",
        },
    )


# ============================================================
# SUPPLY CHAIN PRODUCT IMPORT
# ============================================================

@login_required
@require_POST
def products_import(request):
    """
    Supply Chain-owned product import endpoint.

    The Supply Chain app owns the URL and user-facing workflow.
    The existing product Excel service remains the import engine.
    """

    if "excel_file" not in request.FILES:
        messages.error(
            request,
            "Please select an Excel file to import.",
        )
        return redirect(
            "supply_chain:supply-chain-products"
        )

    form = ProductExcelUploadForm(
        request.POST,
        request.FILES,
    )

    if not form.is_valid():
        messages.error(
            request,
            "The product import file could not be validated.",
        )
        return redirect(
            "supply_chain:supply-chain-products"
        )

    try:
        result = import_products_from_excel(
            form.cleaned_data["excel_file"],
            db="default",
        )

        created = result.get("created", 0)
        updated = result.get("updated", 0)

        messages.success(
            request,
            (
                "Product import completed successfully: "
                f"{created} created, {updated} updated."
            ),
        )

    except Exception as exc:
        messages.error(
            request,
            f"Product import failed: {exc}",
        )

    return redirect(
        "supply_chain:supply-chain-products"
    )


# ============================================================
# SUPPLY CHAIN PRODUCT PRICE LIST
# ============================================================

@login_required
def products_download_price_list(request):
    """
    Supply Chain-owned product price-list generator.

    This does not redirect to the old Products app price-list URL.
    It generates the PDF directly from the current ProductPricing data.
    """

    subcategory_ids = request.GET.getlist(
        "subcategories"
    )

    price_type = (
        request.GET.get(
            "price_type",
            "wholesale",
        )
        or "wholesale"
    ).lower().strip()

    if price_type not in {
        "wholesale",
        "retail",
    }:
        price_type = "wholesale"

    products = (
        Product.objects
        .select_related(
            "category",
            "category__parent",
        )
        .prefetch_related(
            "pricing_rows",
        )
        .filter(
            category__parent__isnull=False,
            visible="YES",
        )
        .order_by(
            "product_no",
        )
    )

    if subcategory_ids:
        products = products.filter(
            category_id__in=subcategory_ids
        )

    response = HttpResponse(
        content_type="application/pdf"
    )

    response["Content-Disposition"] = (
        'attachment; '
        f'filename="The_Daily_Market_'
        f'{price_type.title()}_Price_List.pdf"'
    )

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

    # --------------------------------------------------------
    # STYLES
    # --------------------------------------------------------

    tdm_green = colors.HexColor("#0b5c39")
    light_grey = colors.HexColor("#f3f3f3")
    border_grey = colors.HexColor("#cfcfcf")

    company_style = ParagraphStyle(
        "SupplyChainCompany",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=19,
        textColor=tdm_green,
        spaceAfter=2,
    )

    subtitle_style = ParagraphStyle(
        "SupplyChainSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
    )

    title_style = ParagraphStyle(
        "SupplyChainPriceListTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        textColor=colors.white,
        alignment=TA_CENTER,
    )

    white_subtitle_style = ParagraphStyle(
        "SupplyChainPriceListWhiteSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=TA_CENTER,
    )

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    elements.append(
        Paragraph(
            "THE DAILY MARKET",
            company_style,
        )
    )

    elements.append(
        Paragraph(
            "Supply Chain Product Price List",
            subtitle_style,
        )
    )

    elements.append(
        Spacer(1, 8)
    )

    title_table = Table(
        [
            [
                Paragraph(
                    f"{price_type.title()} Product Price List",
                    title_style,
                )
            ],
            [
                Paragraph(
                    "Prices include VAT",
                    white_subtitle_style,
                )
            ],
        ],
        colWidths=[19 * cm],
    )

    title_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    tdm_green,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    elements.append(title_table)
    elements.append(Spacer(1, 8))

    elements.append(
        Paragraph(
            "Reg: 2024/232233/07",
            styles["Normal"],
        )
    )
    elements.append(
        Paragraph(
            "WhatsApp Orders: 064 458 7575",
            styles["Normal"],
        )
    )
    elements.append(
        Paragraph(
            "info@thedailymarket.co.za | www.thedailymarket.co.za",
            styles["Normal"],
        )
    )

    elements.append(Spacer(1, 10))

    # --------------------------------------------------------
    # DATA
    # --------------------------------------------------------

    data = [
        [
            "Product No.",
            "Category",
            "Subcategory",
            "Product",
            "Price (Incl VAT)",
        ]
    ]

    for product in products:
        active_rows = [
            row
            for row in product.pricing_rows.all()
            if row.is_active
        ]

        if price_type == "retail":
            prices = [
                row.retail_price_inc
                for row in active_rows
                if row.retail_price_inc is not None
            ]
        else:
            prices = [
                row.wholesale_price_inc
                for row in active_rows
                if row.wholesale_price_inc is not None
            ]

        price = min(prices) if prices else None

        parent_name = (
            product.category.parent.name
            if product.category
            and product.category.parent
            else "—"
        )

        category_name = (
            product.category.name
            if product.category
            else "—"
        )

        data.append(
            [
                product.product_no or "—",
                parent_name,
                category_name,
                product.name or "—",
                (
                    f"R{price:.2f}"
                    if price is not None
                    else "—"
                ),
            ]
        )

    table = Table(
        data,
        colWidths=[
            2.2 * cm,
            3.2 * cm,
            3.5 * cm,
            7.0 * cm,
            3.0 * cm,
        ],
        repeatRows=1,
    )

    table.setStyle(
        TableStyle(
            [
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    border_grey,
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    tdm_green,
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold",
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7.5,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, 0),
                    "CENTER",
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (0, -1),
                    "CENTER",
                ),
                (
                    "ALIGN",
                    (4, 1),
                    (4, -1),
                    "RIGHT",
                ),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [
                        colors.white,
                        light_grey,
                    ],
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4,
                ),
            ]
        )
    )

    elements.append(table)

    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

    generated_at = timezone.localtime().strftime(
        "%d %b %Y %H:%M"
    )

    def add_footer(canvas, doc):
        canvas.saveState()

        footer_text = (
            f"Generated on {generated_at} | "
            f"Page {canvas.getPageNumber()}"
        )

        canvas.setFont(
            "Helvetica",
            8,
        )

        canvas.drawCentredString(
            A4[0] / 2,
            0.7 * cm,
            footer_text,
        )

        canvas.restoreState()

    doc.build(
        elements,
        onFirstPage=add_footer,
        onLaterPages=add_footer,
    )

    return response


# ============================================================
# PROCUREMENT
# ============================================================

@login_required
def procurement_list(request):
    procurements = (
        Procurement.objects
        .select_related(
            "created_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
            "purchase_orders",
        )
        .order_by(
            "-procurement_date",
            "-id",
        )
    )

    status = (request.GET.get("status") or "").strip()
    wave = (request.GET.get("wave") or "").strip()
    search = (request.GET.get("search") or "").strip()

    if status:
        procurements = procurements.filter(
            status=status
        )

    if wave:
        procurements = procurements.filter(
            wave=wave
        )

    if search:
        procurements = procurements.filter(
            Q(procurement_number__icontains=search)
            | Q(notes__icontains=search)
        )

    return render(
        request,
        "procurement_list.html",
        {
            "procurements": procurements,
            "status_choices": Procurement.STATUS_CHOICES,
            "wave_choices": Procurement.WAVE_CHOICES,
            "selected_status": status,
            "selected_wave": wave,
            "search": search,
            "current": "supply_chain_procurement",
        },
    )

# ============================================================
# PURCHASE ORDERS
# ============================================================

@login_required
def purchase_orders_list(request):
    purchase_orders = (
        PurchaseOrder.objects
        .select_related(
            "procurement",
            "supplier",
            "created_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
        )
        .order_by(
            "-order_date",
            "-id",
        )
    )

    status = (request.GET.get("status") or "").strip()
    supplier_id = (request.GET.get("supplier") or "").strip()
    search = (request.GET.get("search") or "").strip()

    if status:
        purchase_orders = purchase_orders.filter(
            status=status
        )

    if supplier_id:
        purchase_orders = purchase_orders.filter(
            supplier_id=supplier_id
        )

    if search:
        purchase_orders = purchase_orders.filter(
            Q(po_number__icontains=search)
            | Q(supplier_reference__icontains=search)
            | Q(procurement__procurement_number__icontains=search)
            | Q(supplier__name__icontains=search)
        )

    return render(
        request,
        "purchase_orders_list.html",
        {
            "purchase_orders": purchase_orders,
            "status_choices": PurchaseOrder.STATUS_CHOICES,
            "suppliers": Supplier.objects.order_by("name"),
            "selected_status": status,
            "selected_supplier": supplier_id,
            "search": search,
            "current": "supply_chain_purchase_orders",
        },
    )