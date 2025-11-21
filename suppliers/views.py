from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Supplier
from django.db.models import Q
from products.models import Category
from .forms import SupplierForm 
from django.contrib import messages





def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url='/portal/client/login/')

@login_required
@staff_required
def supplier_list(request):
    qs = (Supplier.objects
          .select_related("account_manager")
          .prefetch_related("categories")
          .order_by("name"))

    # Dropdown sources
    filter_categories = Category.objects.filter(is_active=True).order_by("name")

    # GET params
    search = (request.GET.get("search") or "").strip()
    category_id = request.GET.get("category") or ""
    active = request.GET.get("active") or ""   # "1" / "0" / ""

    # Search across common fields
    if search:
        qs = qs.filter(
            Q(code__icontains=search) |
            Q(name__icontains=search) |
            Q(contact_person__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search) |
            Q(whatsapp__icontains=search) |
            Q(address_line1__icontains=search) |
            Q(address_line2__icontains=search) |
            Q(city__icontains=search) |
            Q(province__icontains=search) |
            Q(postal_code__icontains=search)
        )

    # Category filter
    if category_id.isdigit():
        qs = qs.filter(categories__id=int(category_id))

    # Status filter
    if active in ("0", "1"):
        qs = qs.filter(is_active=(active == "1"))

    suppliers = qs

    return render(request, "suppliers/supplier_list.html", {
        "suppliers": suppliers,
        "filter_categories": filter_categories,
        # keep any flash messages you already set elsewhere:
        "success_message": request.GET.get("ok", ""),   # optional
        "error_message": request.GET.get("err", ""),    # optional
    })


@login_required
@staff_required
def supplier_create(request):
    if request.method == "POST":
        form = SupplierForm(request.POST, request.FILES)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f"Supplier '{supplier.name}' created successfully.")
            return redirect("supplier-view", pk=supplier.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = SupplierForm()

    return render(request, "suppliers/supplier_create.html", {"form": form})


@login_required
@staff_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(
        Supplier.objects.select_related("account_manager").prefetch_related("categories"),
        pk=pk,
    )

    if request.method == "POST":
        form = SupplierForm(request.POST, request.FILES, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, f"Supplier '{supplier.name}' updated successfully.")
            return redirect("supplier-view", pk=supplier.pk)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = SupplierForm(instance=supplier)

    return render(request, "suppliers/supplier_edit.html", {"form": form, "supplier": supplier})


@login_required
@staff_required
def supplier_view(request, pk):
    supplier = get_object_or_404(
        Supplier.objects.select_related("account_manager").prefetch_related("categories"),
        pk=pk,
    )

    context = {
        "supplier": supplier,
        # optional flash messages (?ok=... or ?err=...)
        "success_message": request.GET.get("ok", ""),
        "error_message": request.GET.get("err", ""),
    }
    return render(request, "suppliers/supplier_view.html", context)

