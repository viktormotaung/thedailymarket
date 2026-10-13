import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from products.models import Category
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from products.forms import (
    ProductExcelUploadForm,
    ProductForm,
    ProductKnowledgeForm,
)
from products.models import (
    Product,
    ProductKnowledge,
    ProductPricing,
    Procurement,
    ProcurementItem,
    PurchaseOrder,
    PurchaseOrderItem,
)
from products.services.product_excel_importer import (
    import_products_from_excel,
)
from seshibo_site.core.access import get_user_portal_access
from suppliers.models import Supplier


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



@login_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(
        Supplier.objects
        .select_related("account_manager")
        .prefetch_related("categories"),
        pk=pk,
    )

    return render(
        request,
        "supplier_detail.html",
        {
            "supplier": supplier,
            "current": "supply_chain_supplier_detail",
        },
    )


@login_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(
        Supplier.objects
        .select_related("account_manager")
        .prefetch_related("categories"),
        pk=pk,
    )

    if request.method == "POST":
        supplier.name = (request.POST.get("name") or "").strip()
        supplier.code = (request.POST.get("code") or "").strip()
        supplier.contact_person = (
            request.POST.get("contact_person") or ""
        ).strip()
        supplier.email = (request.POST.get("email") or "").strip()
        supplier.phone = (request.POST.get("phone") or "").strip()
        supplier.whatsapp = (request.POST.get("whatsapp") or "").strip()
        supplier.website = (request.POST.get("website") or "").strip()

        supplier.address_line1 = (
            request.POST.get("address_line1") or ""
        ).strip()
        supplier.address_line2 = (
            request.POST.get("address_line2") or ""
        ).strip()
        supplier.city = (request.POST.get("city") or "").strip()
        supplier.province = (
            request.POST.get("province") or ""
        ).strip()
        supplier.postal_code = (
            request.POST.get("postal_code") or ""
        ).strip()
        supplier.country = (
            request.POST.get("country") or ""
        ).strip()

        supplier.vat_number = (
            request.POST.get("vat_number") or ""
        ).strip()

        supplier.company_reg_number = (
            request.POST.get("company_reg_number") or ""
        ).strip()

        supplier.payment_terms = (
            request.POST.get("payment_terms") or ""
        ).strip()

        supplier.notes = (
            request.POST.get("notes") or ""
        ).strip()

        supplier.is_active = request.POST.get("is_active") == "1"
        supplier.visible = request.POST.get("visible") == "1"

        account_manager_id = (
            request.POST.get("account_manager") or ""
        ).strip()

        if account_manager_id:
            supplier.account_manager_id = account_manager_id
        else:
            supplier.account_manager = None

        category_ids = request.POST.getlist("categories")

        try:
            supplier.full_clean()
            supplier.save()
            supplier.categories.set(category_ids)

        except ValidationError as exc:
            messages.error(
                request,
                "Please correct the errors below.",
            )

            return render(
                request,
                "supplier_edit.html",
                {
                    "supplier": supplier,
                    "categories": Category.objects.order_by("name"),
                    "account_managers": User.objects.filter(
                        is_active=True
                    ).order_by(
                        "first_name",
                        "last_name",
                        "username",
                    ),
                    "selected_categories": category_ids,
                    "current": "supply_chain_supplier_edit",
                    "form_errors": exc,
                },
            )

        messages.success(
            request,
            "Supplier updated successfully.",
        )

        return redirect(
            "supply_chain:supply-chain-supplier-detail",
            pk=supplier.pk,
        )

    return render(
        request,
        "supplier_edit.html",
        {
            "supplier": supplier,
            "categories": Category.objects.order_by("name"),
            "account_managers": User.objects.filter(
                is_active=True
            ).order_by(
                "first_name",
                "last_name",
                "username",
            ),
            "selected_categories": list(
                supplier.categories.values_list(
                    "pk",
                    flat=True,
                )
            ),
            "current": "supply_chain_supplier_edit",
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
# PROCUREMENT CREATE
# ============================================================

@login_required
@transaction.atomic
def procurement_create(request):

    if request.method == "POST":

        procurement_date = (request.POST.get("procurement_date") or "").strip()
        wave = (request.POST.get("wave") or "").strip()
        status = (request.POST.get("status") or "draft").strip()
        notes = (request.POST.get("notes") or "").strip()

        # ----------------------------------------------------
        # VALIDATE DATE
        # ----------------------------------------------------

        if not procurement_date:
            messages.error(
                request,
                "Please select a procurement date.",
            )

            return render(
                request,
                "procurement_create.html",
                {
                    "products": Product.objects.order_by("name"),
                    "wave_choices": Procurement.WAVE_CHOICES,
                    "status_choices": Procurement.STATUS_CHOICES,
                    "current": "supply-chain-procurement-create",
                },
            )

        try:
            procurement_date_obj = datetime.strptime(
                procurement_date,
                "%Y-%m-%d",
            ).date()

        except ValueError:
            messages.error(
                request,
                "Please enter a valid procurement date.",
            )

            return render(
                request,
                "procurement_create.html",
                {
                    "products": Product.objects.order_by("name"),
                    "wave_choices": Procurement.WAVE_CHOICES,
                    "status_choices": Procurement.STATUS_CHOICES,
                    "current": "supply-chain-procurement-create",
                },
            )

        # ----------------------------------------------------
        # VALIDATE WAVE
        # ----------------------------------------------------

        if wave not in dict(Procurement.WAVE_CHOICES):

            messages.error(
                request,
                "Please select a valid procurement wave.",
            )

            return render(
                request,
                "procurement_create.html",
                {
                    "products": Product.objects.order_by("name"),
                    "wave_choices": Procurement.WAVE_CHOICES,
                    "status_choices": Procurement.STATUS_CHOICES,
                    "current": "supply-chain-procurement-create",
                },
            )

        # ----------------------------------------------------
        # VALIDATE STATUS
        # ----------------------------------------------------

        if status not in dict(Procurement.STATUS_CHOICES):

            messages.error(
                request,
                "Please select a valid procurement status.",
            )

            return render(
                request,
                "procurement_create.html",
                {
                    "products": Product.objects.order_by("name"),
                    "wave_choices": Procurement.WAVE_CHOICES,
                    "status_choices": Procurement.STATUS_CHOICES,
                    "current": "supply-chain-procurement-create",
                },
            )

        # ----------------------------------------------------
        # CHECK DATE + WAVE
        # ----------------------------------------------------

        if Procurement.objects.filter(
            procurement_date=procurement_date_obj,
            wave=wave,
        ).exists():

            messages.error(
                request,
                (
                    f"A {wave} procurement already exists for "
                    f"{procurement_date_obj:%d %b %Y}."
                ),
            )

            return render(
                request,
                "procurement_create.html",
                {
                    "products": Product.objects.order_by("name"),
                    "wave_choices": Procurement.WAVE_CHOICES,
                    "status_choices": Procurement.STATUS_CHOICES,
                    "current": "supply-chain-procurement-create",
                },
            )

        # ----------------------------------------------------
        # GET REQUIREMENTS
        # ----------------------------------------------------

        product_ids = request.POST.getlist("item_product[]")
        quantities = request.POST.getlist("item_quantity[]")
        item_notes = request.POST.getlist("item_notes[]")

        # Remove completely empty rows
        requirements = []

        for index, product_id in enumerate(product_ids):

            product_id = (product_id or "").strip()

            if not product_id:
                continue

            quantity = (
                quantities[index].strip()
                if index < len(quantities)
                else ""
            )

            item_note = (
                item_notes[index].strip()
                if index < len(item_notes)
                else ""
            )

            requirements.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "notes": item_note,
                }
            )

        # ----------------------------------------------------
        # REQUIRE AT LEAST ONE ITEM
        # ----------------------------------------------------

        if not requirements:

            messages.error(
                request,
                "Please add at least one procurement requirement.",
            )

            return render(
                request,
                "procurement_create.html",
                {
                    "products": Product.objects.order_by("name"),
                    "wave_choices": Procurement.WAVE_CHOICES,
                    "status_choices": Procurement.STATUS_CHOICES,
                    "current": "supply-chain-procurement-create",
                },
            )

        # ----------------------------------------------------
        # VALIDATE PRODUCTS + QUANTITIES
        # ----------------------------------------------------

        seen_products = set()

        for requirement in requirements:

            product_id = requirement["product_id"]
            quantity = requirement["quantity"]

            # Prevent duplicate product rows
            if product_id in seen_products:

                messages.error(
                    request,
                    "The same product cannot be added more than once.",
                )

                return render(
                    request,
                    "procurement_create.html",
                    {
                        "products": Product.objects.order_by("name"),
                        "wave_choices": Procurement.WAVE_CHOICES,
                        "status_choices": Procurement.STATUS_CHOICES,
                        "current": "supply-chain-procurement-create",
                    },
                )

            seen_products.add(product_id)

            # Validate product
            try:
                Product.objects.get(pk=product_id)

            except Product.DoesNotExist:

                messages.error(
                    request,
                    "One of the selected products is invalid.",
                )

                return render(
                    request,
                    "procurement_create.html",
                    {
                        "products": Product.objects.order_by("name"),
                        "wave_choices": Procurement.WAVE_CHOICES,
                        "status_choices": Procurement.STATUS_CHOICES,
                        "current": "supply-chain-procurement-create",
                    },
                )

            # Validate quantity
            try:
                quantity_decimal = Decimal(quantity)

            except Exception:

                messages.error(
                    request,
                    "All procurement quantities must be valid numbers.",
                )

                return render(
                    request,
                    "procurement_create.html",
                    {
                        "products": Product.objects.order_by("name"),
                        "wave_choices": Procurement.WAVE_CHOICES,
                        "status_choices": Procurement.STATUS_CHOICES,
                        "current": "supply-chain-procurement-create",
                    },
                )

            if quantity_decimal <= 0:

                messages.error(
                    request,
                    "Procurement quantities must be greater than zero.",
                )

                return render(
                    request,
                    "procurement_create.html",
                    {
                        "products": Product.objects.order_by("name"),
                        "wave_choices": Procurement.WAVE_CHOICES,
                        "status_choices": Procurement.STATUS_CHOICES,
                        "current": "supply-chain-procurement-create",
                    },
                )

            requirement["quantity_decimal"] = quantity_decimal

        # ----------------------------------------------------
        # GENERATE PROCUREMENT NUMBER
        # ----------------------------------------------------

        procurement_number = (
            f"PROC-"
            f"{procurement_date_obj.strftime('%Y%m%d')}-"
            f"{wave}"
        )

        # ----------------------------------------------------
        # CREATE PROCUREMENT
        # ----------------------------------------------------

        procurement = Procurement.objects.create(
            procurement_number=procurement_number,
            procurement_date=procurement_date_obj,
            wave=wave,
            status=status,
            notes=notes,
            created_by=request.user,
        )

        # ----------------------------------------------------
        # CREATE PROCUREMENT ITEMS
        # ----------------------------------------------------

        for requirement in requirements:

            ProcurementItem.objects.create(
                procurement=procurement,
                product_id=requirement["product_id"],
                required_quantity=requirement["quantity_decimal"],
                notes=requirement["notes"],
            )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        messages.success(
            request,
            (
                f"Procurement {procurement.procurement_number} "
                f"created successfully with "
                f"{len(requirements)} requirement"
                f"{'' if len(requirements) == 1 else 's'}."
            ),
        )

        return redirect(
            "supply_chain:supply-chain-procurement-detail",
            pk=procurement.pk,
        )

    # ========================================================
    # GET
    # ========================================================

    return render(
        request,
        "procurement_create.html",
        {
            "products": Product.objects.order_by("name"),
            "wave_choices": Procurement.WAVE_CHOICES,
            "status_choices": Procurement.STATUS_CHOICES,
            "current": "supply-chain-procurement-create",
        },
    )


@login_required
def procurement_detail(request, pk):
    procurement = get_object_or_404(
        Procurement.objects
        .select_related(
            "created_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
            "purchase_orders__supplier",
            "purchase_orders__items__product",
        ),
        pk=pk,
    )

    return render(
        request,
        "procurement_detail.html",
        {
            "procurement": procurement,
            "current": "supply_chain_procurement",
        },
    )



@login_required
@transaction.atomic
def procurement_edit(request, pk):
    procurement = get_object_or_404(
        Procurement.objects
        .select_related(
            "created_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
            "purchase_orders__supplier",
        ),
        pk=pk,
    )

    products = (
        Product.objects
        .select_related("category")
        .order_by("name")
    )

    if request.method == "POST":

        # ========================================================
        # PROCUREMENT DETAILS
        # ========================================================

        wave = (
            request.POST.get("wave") or ""
        ).strip()

        status = (
            request.POST.get("status") or ""
        ).strip()

        notes = (
            request.POST.get("notes") or ""
        ).strip()

        # --------------------------------------------------------
        # Validate procurement details
        # --------------------------------------------------------

        valid_waves = dict(Procurement.WAVE_CHOICES)
        valid_statuses = dict(Procurement.STATUS_CHOICES)

        errors = []

        if not wave:
            errors.append(
                "Procurement wave is required."
            )
        elif wave not in valid_waves:
            errors.append(
                "Invalid procurement wave."
            )

        if not status:
            errors.append(
                "Procurement status is required."
            )
        elif status not in valid_statuses:
            errors.append(
                "Invalid procurement status."
            )

        # ========================================================
        # READ REQUIREMENT ROWS
        # ========================================================

        item_ids = request.POST.getlist("item_id[]")
        product_ids = request.POST.getlist("product_id[]")
        quantities = request.POST.getlist(
            "required_quantity[]"
        )
        item_notes = request.POST.getlist(
            "item_notes[]"
        )

        submitted_items = []

        # --------------------------------------------------------
        # Validate every submitted requirement before saving
        # --------------------------------------------------------

        for index, product_id in enumerate(product_ids):

            product_id = (product_id or "").strip()

            # Ignore completely empty rows.
            if not product_id:
                continue

            # ----------------------------------------------------
            # Product
            # ----------------------------------------------------

            try:
                product = Product.objects.get(
                    pk=product_id
                )

            except Product.DoesNotExist:
                errors.append(
                    "One of the selected products could not be found."
                )
                continue

            # ----------------------------------------------------
            # Quantity
            # ----------------------------------------------------

            quantity_value = (
                quantities[index]
                if index < len(quantities)
                else ""
            )

            quantity_value = (
                quantity_value or ""
            ).strip()

            if not quantity_value:
                errors.append(
                    f"Required quantity is required for {product.name}."
                )
                continue

            try:
                quantity = Decimal(quantity_value)

            except (InvalidOperation, ValueError):
                errors.append(
                    (
                        f"Invalid quantity for "
                        f"{product.name}."
                    )
                )
                continue

            if quantity < Decimal("0.00"):
                errors.append(
                    (
                        f"Quantity for "
                        f"{product.name} "
                        f"cannot be negative."
                    )
                )
                continue

            # ----------------------------------------------------
            # Notes
            # ----------------------------------------------------

            note_value = (
                item_notes[index]
                if index < len(item_notes)
                else ""
            )

            note_value = (
                note_value or ""
            ).strip()

            # ----------------------------------------------------
            # Existing item ID
            # ----------------------------------------------------

            item_id = (
                item_ids[index]
                if index < len(item_ids)
                else ""
            )

            item_id = (
                item_id or ""
            ).strip()

            submitted_items.append(
                {
                    "item_id": item_id,
                    "product": product,
                    "quantity": quantity,
                    "notes": note_value,
                }
            )

        # ========================================================
        # CHECK FOR DUPLICATE PRODUCTS
        # ========================================================
        #
        # ProcurementItem has a unique constraint for:
        #
        #     procurement + product
        #
        # Therefore we must prevent the edit form from submitting
        # the same product more than once.
        #
        # ========================================================

        seen_products = set()

        for item_data in submitted_items:

            product_id = item_data["product"].pk

            if product_id in seen_products:
                errors.append(
                    (
                        f"{item_data['product'].name} "
                        f"has been added more than once."
                    )
                )
            else:
                seen_products.add(product_id)

        # ========================================================
        # IF VALIDATION FAILED
        # ========================================================

        if errors:

            for error in errors:
                messages.error(
                    request,
                    error,
                )

        else:

            # ====================================================
            # UPDATE PROCUREMENT
            # ====================================================

            procurement.wave = wave
            procurement.status = status
            procurement.notes = notes

            procurement.save()

            # ====================================================
            # TRACK ITEMS THAT REMAIN
            # ====================================================

            submitted_item_ids = set()

            # ====================================================
            # CREATE / UPDATE PROCUREMENT ITEMS
            # ====================================================

            for item_data in submitted_items:

                item_id = item_data["item_id"]

                product = item_data["product"]
                quantity = item_data["quantity"]
                item_note = item_data["notes"]

                # ------------------------------------------------
                # EXISTING ITEM
                # ------------------------------------------------

                if item_id:

                    item = get_object_or_404(
                        ProcurementItem,
                        pk=item_id,
                        procurement=procurement,
                    )

                    item.product = product
                    item.required_quantity = quantity
                    item.notes = item_note

                    item.save()

                    submitted_item_ids.add(
                        item.pk
                    )

                # ------------------------------------------------
                # NEW ITEM
                # ------------------------------------------------

                else:

                    item = ProcurementItem.objects.create(
                        procurement=procurement,
                        product=product,
                        required_quantity=quantity,
                        notes=item_note,
                    )

                    submitted_item_ids.add(
                        item.pk
                    )

            # ====================================================
            # DELETE REMOVED REQUIREMENTS
            # ====================================================
            #
            # Anything that existed previously but was removed
            # from the edit page is deleted here.
            #
            # ====================================================

            ProcurementItem.objects.filter(
                procurement=procurement,
            ).exclude(
                pk__in=submitted_item_ids,
            ).delete()

            # ====================================================
            # SUCCESS
            # ====================================================

            messages.success(
                request,
                (
                    f"Procurement "
                    f"{procurement.procurement_number} "
                    f"updated successfully."
                ),
            )

            return redirect(
                "supply_chain:supply-chain-procurement-detail",
                pk=procurement.pk,
            )

    # ============================================================
    # RENDER EDIT PAGE
    # ============================================================

    return render(
        request,
        "procurement_edit.html",
        {
            "procurement": procurement,
            "products": products,
            "wave_choices": Procurement.WAVE_CHOICES,
            "status_choices": Procurement.STATUS_CHOICES,
            "current": "supply-chain-procurement-edit",
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





@login_required
def purchase_order_pdf(request, pk):
    purchase_order = get_object_or_404(
        PurchaseOrder.objects
        .select_related(
            "procurement",
            "supplier",
            "created_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
            "items__procurement_item",
        ),
        pk=pk,
    )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{purchase_order.po_number}.pdf"'
    )

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Purchase Order {purchase_order.po_number}",
        author="The Daily Market",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "PO_Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        spaceAfter=6,
    )

    subtitle_style = ParagraphStyle(
        "PO_Subtitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#666666"),
        alignment=TA_CENTER,
        spaceAfter=16,
    )

    heading_style = ParagraphStyle(
        "PO_Heading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0b5c39"),
        spaceBefore=8,
        spaceAfter=8,
    )

    body_style = ParagraphStyle(
        "PO_Body",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )

    small_style = ParagraphStyle(
        "PO_Small",
        parent=body_style,
        fontSize=8,
        leading=10,
    )

    # White text specifically for the green table header
    header_style = ParagraphStyle(
        "PO_Header",
        parent=small_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    right_style = ParagraphStyle(
        "PO_Right",
        parent=body_style,
        alignment=TA_RIGHT,
    )

    story = []

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "THE DAILY MARKET",
            title_style,
        )
    )

    story.append(
        Paragraph(
            f"PURCHASE ORDER · {purchase_order.po_number}",
            subtitle_style,
        )
    )

    # ---------------------------------------------------------
    # PURCHASE ORDER INFORMATION
    # ---------------------------------------------------------

    info_data = [
        [
            Paragraph("<b>PO Number</b>", body_style),
            Paragraph(
                str(purchase_order.po_number),
                body_style,
            ),
            Paragraph("<b>Order Date</b>", body_style),
            Paragraph(
                purchase_order.order_date.strftime("%d %b %Y")
                if purchase_order.order_date
                else "—",
                body_style,
            ),
        ],
        [
            Paragraph("<b>Supplier</b>", body_style),
            Paragraph(
                str(purchase_order.supplier or "—"),
                body_style,
            ),
            Paragraph("<b>Status</b>", body_style),
            Paragraph(
                purchase_order.get_status_display(),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Fulfilment</b>", body_style),
            Paragraph(
                purchase_order.get_fulfilment_type_display()
                if purchase_order.fulfilment_type
                else "Delivery",
                body_style,
            ),
            Paragraph("<b>On or Before</b>", body_style),
            Paragraph(
                purchase_order.expected_delivery_date.strftime("%d %b %Y")
                if purchase_order.expected_delivery_date
                else "—",
                body_style,
            ),
        ],
        [
            Paragraph("<b>Procurement</b>", body_style),
            Paragraph(
                str(purchase_order.procurement.procurement_number)
                if purchase_order.procurement
                else "—",
                body_style,
            ),
            Paragraph("<b>Supplier Reference</b>", body_style),
            Paragraph(
                purchase_order.supplier_reference or "—",
                body_style,
            ),
        ],
        [
            Paragraph("<b>Created By</b>", body_style),
            Paragraph(
                str(purchase_order.created_by)
                if purchase_order.created_by
                else "—",
                body_style,
            ),
            Paragraph("<b>Approved By</b>", body_style),
            Paragraph(
                str(purchase_order.approved_by)
                if purchase_order.approved_by
                else "—",
                body_style,
            ),
        ],
    ]

    info_table = Table(
        info_data,
        colWidths=[
            28 * mm,
            57 * mm,
            35 * mm,
            55 * mm,
        ],
        hAlign="LEFT",
    )

    info_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f3f5f4"),
                ),
                (
                    "BACKGROUND",
                    (2, 0),
                    (2, -1),
                    colors.HexColor("#f3f5f4"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#d9d9d9"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#e5e5e5"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    story.append(info_table)
    story.append(Spacer(1, 8 * mm))

    # ---------------------------------------------------------
    # PURCHASE ORDER ITEMS
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "PURCHASE ORDER ITEMS",
            heading_style,
        )
    )

    item_data = [
        [
            Paragraph("Product", header_style),
            Paragraph("Product No.", header_style),
            Paragraph("Qty", header_style),
            Paragraph("Unit Cost EXCL", header_style),
            Paragraph("Total EXCL", header_style),
            Paragraph("Notes", header_style),
        ]
    ]

    for item in purchase_order.items.all():
        product_name = (
            str(item.product.name)
            if item.product
            else "—"
        )

        product_no = (
            str(item.product.product_no)
            if item.product and item.product.product_no
            else "—"
        )

        unit_cost = (
            f"R{item.expected_unit_cost_excl:,.2f}"
            if item.expected_unit_cost_excl is not None
            else "—"
        )

        line_total = (
            f"R{item.expected_total_excl:,.2f}"
            if item.expected_unit_cost_excl is not None
            else "—"
        )

        item_data.append(
            [
                Paragraph(
                    product_name,
                    small_style,
                ),
                Paragraph(
                    product_no,
                    small_style,
                ),
                Paragraph(
                    f"{item.ordered_quantity:,.2f}",
                    right_style,
                ),
                Paragraph(
                    unit_cost,
                    right_style,
                ),
                Paragraph(
                    line_total,
                    right_style,
                ),
                Paragraph(
                    item.notes or "—",
                    small_style,
                ),
            ]
        )

    items_table = Table(
        item_data,
        colWidths=[
            58 * mm,
            25 * mm,
            17 * mm,
            27 * mm,
            27 * mm,
            26 * mm,
        ],
        repeatRows=1,
        hAlign="LEFT",
    )

    items_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#0b5c39"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.35,
                    colors.HexColor("#d9d9d9"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [
                        colors.white,
                        colors.HexColor("#f8f9fa"),
                    ],
                ),
            ]
        )
    )

    story.append(items_table)
    story.append(Spacer(1, 7 * mm))

    # ---------------------------------------------------------
    # TOTALS
    # ---------------------------------------------------------

    actual_total = (
        f"R{purchase_order.actual_total:,.2f}"
        if purchase_order.actual_total is not None
        else "Not entered"
    )

    totals_data = [
        [
            Paragraph(
                "<b>Estimated Total EXCL VAT</b>",
                body_style,
            ),
            Paragraph(
                f"<b>R{purchase_order.estimated_total:,.2f}</b>",
                right_style,
            ),
        ],
        [
            Paragraph(
                "<b>Expected VAT</b>",
                body_style,
            ),
            Paragraph(
                f"<b>R{purchase_order.expected_vat:,.2f}</b>",
                right_style,
            ),
        ],
        [
            Paragraph(
                "<b>Expected Total INCL VAT</b>",
                body_style,
            ),
            Paragraph(
                f"<b>R{purchase_order.expected_total_incl:,.2f}</b>",
                right_style,
            ),
        ],
        [
            Paragraph(
                "<b>Actual Total EXCL VAT</b>",
                body_style,
            ),
            Paragraph(
                f"<b>{actual_total}</b>",
                right_style,
            ),
        ],
    ]

    totals_table = Table(
        totals_data,
        colWidths=[
            60 * mm,
            45 * mm,
        ],
        hAlign="RIGHT",
    )

    totals_table.setStyle(
        TableStyle(
            [
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#d9d9d9"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#e5e5e5"),
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor("#f8f9fa"),
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
            ]
        )
    )

    story.append(totals_table)

    # ---------------------------------------------------------
    # NOTES
    # ---------------------------------------------------------

    if purchase_order.notes:
        story.append(Spacer(1, 7 * mm))

        story.append(
            Paragraph(
                "NOTES",
                heading_style,
            )
        )

        story.append(
            Paragraph(
                purchase_order.notes.replace(
                    "\n",
                    "<br/>",
                ),
                body_style,
            )
        )

    # ---------------------------------------------------------
    # FOOTER
    # ---------------------------------------------------------

    story.append(Spacer(1, 12 * mm))

    story.append(
        Paragraph(
            "Generated by The Daily Market Supply Chain Platform.",
            ParagraphStyle(
                "Footer",
                parent=small_style,
                textColor=colors.HexColor("#777777"),
                alignment=TA_CENTER,
            ),
        )
    )

    # ---------------------------------------------------------
    # BUILD PDF
    # ---------------------------------------------------------

    doc.build(story)

    return response


@login_required
def purchase_order_detail(request, pk):
    purchase_order = get_object_or_404(
        PurchaseOrder.objects
        .select_related(
            "procurement",
            "supplier",
            "created_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
            "items__procurement_item",
        ),
        pk=pk,
    )

    # ============================================================
    # UPDATE ACTUAL PURCHASE ORDER TOTAL
    # ============================================================

    if request.method == "POST":
        action = request.POST.get("action")

        # ========================================================
        # UPDATE PURCHASE ORDER STATUS
        # ========================================================

        if action == "update_status":
            new_status = (request.POST.get("status") or "").strip()

            allowed_statuses = {
                "pending_approval",
                "approved",
                "sent",
                "cancelled",
            }

            if new_status not in allowed_statuses:
                messages.error(
                    request,
                    "Invalid Purchase Order status.",
                )
                return redirect(
                    "supply_chain:supply-chain-purchase-order-detail",
                    pk=purchase_order.pk,
                )

            # Approved and cancelled are terminal statuses from
            # the Purchase Order detail page.
            if purchase_order.status in {
                "approved",
                "cancelled",
            }:
                messages.error(
                    request,
                    "This Purchase Order status can no longer be changed.",
                )
                return redirect(
                    "supply_chain:supply-chain-purchase-order-detail",
                    pk=purchase_order.pk,
                )

            purchase_order.status = new_status

            update_fields = [
                "status",
                "updated_at",
            ]

            if new_status == "approved":
                purchase_order.approved_by = request.user
                purchase_order.approved_at = timezone.now()

                update_fields.extend([
                    "approved_by",
                    "approved_at",
                ])

            elif new_status == "sent":
                purchase_order.sent_at = timezone.now()
                update_fields.append("sent_at")

            purchase_order.save(
                update_fields=update_fields
            )

            messages.success(
                request,
                f"Purchase Order status updated to "
                f"'{purchase_order.get_status_display()}'.",
            )

            return redirect(
                "supply_chain:supply-chain-purchase-order-detail",
                pk=purchase_order.pk,
            )

        if action == "update_actual_total":
            raw_actual_total = (
                request.POST.get("actual_total") or ""
            ).strip()

            # ----------------------------------------------------
            # CLEAR ACTUAL TOTAL
            # ----------------------------------------------------

            if not raw_actual_total:
                purchase_order.actual_total = None

                purchase_order.save(
                    update_fields=[
                        "actual_total",
                        "updated_at",
                    ]
                )

                messages.success(
                    request,
                    "Actual Purchase Order total cleared.",
                )

                return redirect(
                    "supply_chain:supply-chain-purchase-order-detail",
                    pk=purchase_order.pk,
                )

            # ----------------------------------------------------
            # SAVE ACTUAL TOTAL
            # ----------------------------------------------------

            try:
                actual_total = Decimal(
                    raw_actual_total
                )

                if actual_total < Decimal("0.00"):
                    raise InvalidOperation

                actual_total = actual_total.quantize(
                    Decimal("0.01")
                )

            except (InvalidOperation, ValueError):
                messages.error(
                    request,
                    "Please enter a valid actual total.",
                )

            else:
                purchase_order.actual_total = actual_total

                purchase_order.save(
                    update_fields=[
                        "actual_total",
                        "updated_at",
                    ]
                )

                messages.success(
                    request,
                    "Actual Purchase Order total updated successfully.",
                )

                return redirect(
                    "supply_chain:supply-chain-purchase-order-detail",
                    pk=purchase_order.pk,
                )

    # ============================================================
    # RENDER PURCHASE ORDER DETAIL
    # ============================================================

    return render(
        request,
        "purchase_order_detail.html",
        {
            "purchase_order": purchase_order,
            "current": "supply_chain_purchase_order_detail",
        },
    )


@login_required
def procurement_pdf(request, pk):
    procurement = get_object_or_404(
        Procurement.objects
        .select_related(
            "created_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
        ),
        pk=pk,
    )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="Procurement-{procurement.procurement_number}.pdf"'
    )

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Procurement {procurement.procurement_number}",
        author="The Daily Market",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Procurement_Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        spaceAfter=6,
    )

    subtitle_style = ParagraphStyle(
        "Procurement_Subtitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#666666"),
        alignment=TA_CENTER,
        spaceAfter=16,
    )

    heading_style = ParagraphStyle(
        "Procurement_Heading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0b5c39"),
        spaceBefore=8,
        spaceAfter=8,
    )

    body_style = ParagraphStyle(
        "Procurement_Body",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )

    small_style = ParagraphStyle(
        "Procurement_Small",
        parent=body_style,
        fontSize=8,
        leading=10,
    )

    header_style = ParagraphStyle(
        "Procurement_Header",
        parent=small_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    right_style = ParagraphStyle(
        "Procurement_Right",
        parent=body_style,
        alignment=TA_RIGHT,
    )

    story = []

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "THE DAILY MARKET",
            title_style,
        )
    )

    story.append(
        Paragraph(
            f"PROCUREMENT · {procurement.procurement_number}",
            subtitle_style,
        )
    )

    # ---------------------------------------------------------
    # PROCUREMENT INFORMATION
    # ---------------------------------------------------------

    info_data = [
        [
            Paragraph("<b>Procurement Number</b>", body_style),
            Paragraph(
                str(procurement.procurement_number),
                body_style,
            ),
            Paragraph("<b>Date</b>", body_style),
            Paragraph(
                procurement.procurement_date.strftime("%d %b %Y")
                if procurement.procurement_date
                else "—",
                body_style,
            ),
        ],
        [
            Paragraph("<b>Wave</b>", body_style),
            Paragraph(
                procurement.get_wave_display()
                if procurement.wave
                else "—",
                body_style,
            ),
            Paragraph("<b>Status</b>", body_style),
            Paragraph(
                procurement.get_status_display(),
                body_style,
            ),
        ],
        [
            Paragraph("<b>Created By</b>", body_style),
            Paragraph(
                procurement.created_by.get_full_name()
                or procurement.created_by.username
                if procurement.created_by
                else "—",
                body_style,
            ),
            Paragraph("<b>Created</b>", body_style),
            Paragraph(
                procurement.created_at.strftime("%d %b %Y %H:%M")
                if procurement.created_at
                else "—",
                body_style,
            ),
        ],
        [
            Paragraph("<b>Approved By</b>", body_style),
            Paragraph(
                procurement.approved_by.get_full_name()
                or procurement.approved_by.username
                if procurement.approved_by
                else "—",
                body_style,
            ),
            Paragraph("<b>Approved At</b>", body_style),
            Paragraph(
                procurement.approved_at.strftime("%d %b %Y %H:%M")
                if procurement.approved_at
                else "—",
                body_style,
            ),
        ],
        [
            Paragraph("<b>Last Updated</b>", body_style),
            Paragraph(
                procurement.updated_at.strftime("%d %b %Y %H:%M")
                if procurement.updated_at
                else "—",
                body_style,
            ),
            Paragraph("<b>Requirements</b>", body_style),
            Paragraph(
                str(procurement.items.count()),
                body_style,
            ),
        ],
    ]

    info_table = Table(
        info_data,
        colWidths=[
            35 * mm,
            50 * mm,
            35 * mm,
            55 * mm,
        ],
        hAlign="LEFT",
    )

    info_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f3f5f4"),
                ),
                (
                    "BACKGROUND",
                    (2, 0),
                    (2, -1),
                    colors.HexColor("#f3f5f4"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor("#d9d9d9"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.25,
                    colors.HexColor("#e5e5e5"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    story.append(info_table)
    story.append(Spacer(1, 8 * mm))

    # ---------------------------------------------------------
    # PROCUREMENT REQUIREMENTS
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "PROCUREMENT REQUIREMENTS",
            heading_style,
        )
    )

    requirements = list(
        procurement.items.all()
    )

    if requirements:

        item_data = [
            [
                Paragraph("Product", header_style),
                Paragraph("Product No.", header_style),
                Paragraph("SKU", header_style),
                Paragraph("Required Qty", header_style),
                Paragraph("Notes", header_style),
            ]
        ]

        for item in requirements:

            product_name = (
                str(item.product.name)
                if item.product
                else "—"
            )

            product_no = (
                str(item.product.product_no)
                if item.product and item.product.product_no
                else "—"
            )

            sku = (
                str(item.product.sku)
                if item.product and item.product.sku
                else "—"
            )

            quantity = (
                f"{item.required_quantity:,.2f}"
                if item.required_quantity is not None
                else "—"
            )

            item_data.append(
                [
                    Paragraph(
                        product_name,
                        small_style,
                    ),
                    Paragraph(
                        product_no,
                        small_style,
                    ),
                    Paragraph(
                        sku,
                        small_style,
                    ),
                    Paragraph(
                        quantity,
                        right_style,
                    ),
                    Paragraph(
                        item.notes or "—",
                        small_style,
                    ),
                ]
            )

        items_table = Table(
            item_data,
            colWidths=[
                60 * mm,
                27 * mm,
                25 * mm,
                27 * mm,
                36 * mm,
            ],
            repeatRows=1,
            hAlign="LEFT",
        )

        items_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#0b5c39"),
                    ),
                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (-1, 0),
                        colors.white,
                    ),
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.35,
                        colors.HexColor("#d9d9d9"),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP",
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [
                            colors.white,
                            colors.HexColor("#f8f9fa"),
                        ],
                    ),
                ]
            )
        )

        story.append(items_table)

    else:

        story.append(
            Paragraph(
                "No procurement requirements recorded.",
                body_style,
            )
        )

    # ---------------------------------------------------------
    # NOTES
    # ---------------------------------------------------------

    if procurement.notes:

        story.append(
            Spacer(
                1,
                8 * mm,
            )
        )

        story.append(
            Paragraph(
                "NOTES",
                heading_style,
            )
        )

        story.append(
            Paragraph(
                procurement.notes.replace(
                    "\n",
                    "<br/>",
                ),
                body_style,
            )
        )

    # ---------------------------------------------------------
    # FOOTER
    # ---------------------------------------------------------

    story.append(
        Spacer(
            1,
            12 * mm,
        )
    )

    story.append(
        Paragraph(
            "Generated by The Daily Market Supply Chain Platform.",
            ParagraphStyle(
                "Procurement_Footer",
                parent=small_style,
                textColor=colors.HexColor("#777777"),
                alignment=TA_CENTER,
            ),
        )
    )

    # ---------------------------------------------------------
    # BUILD PDF
    # ---------------------------------------------------------

    doc.build(story)

    return response



