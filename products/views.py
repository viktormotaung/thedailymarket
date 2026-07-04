# products/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db.models import Q, Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from suppliers.models import Supplier
from .models import Product, Category, ProductPricing
from .forms import ProductForm, ProductVariantFormSet, ProductPricingForm 
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
from .models import Product, ProductVariant
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image
from django.conf import settings
import os



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
            w_vals = [
                r.wholesale_price_inc
                for r in active_rows
                if r.wholesale_price_inc is not None
            ]
            r_vals = [
                r.retail_price_inc
                for r in active_rows
                if r.retail_price_inc is not None
            ]

            if w_vals:
                min_wholesale_inc = min(w_vals)
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





@login_required
@staff_required
def download_price_list(request):
    subcategory_ids = request.GET.getlist("subcategories")

    price_type = request.GET.get(
        "price_type",
        "wholesale"
    ).lower()

    qs = (
        Product.objects
        .select_related("category", "category__parent")
        .prefetch_related("pricing_rows")
        .filter(category__parent__isnull=False)
        .order_by("product_no")
    )

    if subcategory_ids:
        qs = qs.filter(category_id__in=subcategory_ids)

    response = HttpResponse(content_type="application/pdf")

    # Force browser/phone download
    response["Content-Type"] = "application/pdf"
    response["Content-Disposition"] = (
        f'attachment; filename="The_Daily_Market_{price_type.title()}_Price_List.pdf"'
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

    # =========================
    # FOOTER
    # =========================
    generated_at = timezone.localtime().strftime("%d %b %Y %H:%M")

    def add_footer(canvas, doc):
        canvas.saveState()

        footer_text = (
            f"Generated on {generated_at} | Page {canvas.getPageNumber()}"
        )

        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(
            A4[0] / 2,
            0.7 * cm,
            footer_text
        )

        canvas.restoreState()

    # =========================
    # LOGO
    # =========================
    logo_path = os.path.join(
        settings.BASE_DIR,
        "static",
        "images",
        "seshibo-logo.png"
    )

    if os.path.exists(logo_path):
        logo = Image(
            logo_path,
            width=4 * cm,
            height=4 * cm
        )
        elements.append(logo)

    elements.append(Spacer(1, 6))

    # =========================
    # HEADER
    # =========================
    elements.append(
        Paragraph(
            "Reg: 2024/232233/07",
            styles["Normal"]
        )
    )

    elements.append(
        Paragraph(
            "Whatsapp: 064 458 7575",
            styles["Normal"]
        )
    )

    elements.append(
        Paragraph(
            "info@thedailymarket.co.za / www.thedailymarket.co.za",
            styles["Normal"]
        )
    )

    elements.append(Spacer(1, 10))

    elements.append(
        Paragraph(
            f"<b>{price_type.title()} Product Price List</b>",
            styles["Heading2"]
        )
    )

    elements.append(Spacer(1, 12))

    # =========================
    # TABLE DATA
    # =========================
    data = [["Category", "Subcategory", "Product", "Price (Incl VAT)"]]

    for product in qs:
        if price_type == "retail":

            prices = [
                row.retail_price_inc
                for row in product.pricing_rows.all()
                if row.is_active
                and row.retail_price_inc is not None
            ]

        else:

            prices = [
                row.wholesale_price_inc
                for row in product.pricing_rows.all()
                if row.is_active
                and row.wholesale_price_inc is not None
            ]

        price = min(prices) if prices else None

        data.append([
            product.category.parent.name
            if product.category and product.category.parent else "—",

            product.category.name
            if product.category else "—",

            product.name,

            f"R{price:.2f}"
            if price is not None else "—",
        ])

    # =========================
    # TABLE
    # =========================
    table = Table(
        data,
        colWidths=[
            3 * cm,
            4 * cm,
            7 * cm,
            3 * cm,
        ],
        repeatRows=1,
    )

    table.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.black),

            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),

            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ])
    )

    elements.append(table)

    # =========================
    # BUILD PDF
    # =========================
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

    VariantFormSet3 = inlineformset_factory(
        parent_model=Product,
        model=ProductVariant,
        form=ProductVariantForm,
        formset=VariantFormSetClean,  # <<< use the same cleaner in edit
        extra=1,                      # one blank row on edit is usually enough
        can_delete=True,
    )

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        formset = VariantFormSet3(
            request.POST, request.FILES, instance=product, prefix="variants"
        )
        if form.is_valid() and formset.is_valid():
            product = form.save()
            formset.save()   # create/update/delete variants
            messages.success(request, "Product updated.")
            return redirect("product-view", pk=product.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = ProductForm(instance=product)
        formset = VariantFormSet3(instance=product, prefix="variants")

    return render(request, "products/product_edit.html", {
        "form": form,
        "product": product,
        "variant_formset": formset,
    })



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
    Product detail page with pricing rows and product variants.
    """
    product = get_object_or_404(
        Product.objects.select_related("category"),
        pk=pk
    )

    # Pricing rows (unchanged)
    pricing_rows = (
        ProductPricing.objects
        .filter(product=product)
        .select_related("supplier")
        .order_by("supplier__name")
    )

    # Build simple rows for variants so the template stays dumb
    variants = (
        product.variants
        .all()
        .order_by("pack_size", "id")
    )

    variant_rows = []
    for v in variants:
        # safe helpers
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
            "image_url": (v.image.url if v.image else None),
        })

    return render(
        request,
        "products/product_view.html",
        {
            "product": product,
            "pricing_rows": pricing_rows,
            "variant_rows": variant_rows,
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


