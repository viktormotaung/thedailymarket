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

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet
from django.shortcuts import get_object_or_404, redirect, render

from products.models import Product, ProductVariant
from products.forms import (
    ProductForm,
    ProductVariantForm,
)
from .forms import ProductForm, ProductVariantForm
from .models import Product, ProductVariant
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
    Prefetches pricing rows + suppliers; computes a small row summary
    showing ONE price per product: the cheapest incl-VAT for retail & wholesale.
    """
    qs = (
        Product.objects
        .select_related("category")
        .prefetch_related("pricing_rows__supplier")
        .order_by("name")
    )

    # Filters
    filter_categories = Category.objects.order_by("name")
    filter_suppliers = Supplier.objects.order_by("name")

    search = (request.GET.get("search") or "").strip()
    category_id = (request.GET.get("category") or "").strip()
    supplier_id = (request.GET.get("supplier") or "").strip()

    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(sku__icontains=search))

    if category_id:
        qs = qs.filter(category_id=category_id)

    if supplier_id:
        active_for_supplier = ProductPricing.objects.filter(
            product=OuterRef("pk"),
            supplier_id=supplier_id,
            is_active=True,
        )
        qs = qs.annotate(_has_supplier=Exists(active_for_supplier)).filter(_has_supplier=True)

    products = list(qs)

    # Build light-weight row summaries (no extra queries thanks to prefetch)
    rows = []
    for p in products:
        active_rows = [r for r in p.pricing_rows.all() if r.is_active]
        active_supplier_count = len(active_rows)

        min_wholesale_inc = None
        min_retail_inc = None

        if active_rows:
            w_vals = [r.wholesale_price_inc for r in active_rows if r.wholesale_price_inc is not None]
            r_vals = [r.retail_price_inc for r in active_rows if r.retail_price_inc is not None]
            if w_vals:
                min_wholesale_inc = min(w_vals)
            if r_vals:
                min_retail_inc = min(r_vals)

        rows.append({
            "product": p,
            "active_supplier_count": active_supplier_count,
            "min_wholesale_inc": min_wholesale_inc,
            "min_retail_inc": min_retail_inc,
        })

    return render(
        request,
        "products/product_list.html",
        {
            "rows": rows,
            "filter_categories": filter_categories,
            "filter_suppliers": filter_suppliers,
        },
    )


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