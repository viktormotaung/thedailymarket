from django import forms
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from .models import Client
from products.models import Category
from django.contrib import messages
from orders.models import Order



def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url='/portal/client/login/')

@login_required
@staff_required
def client_list(request):
    qs = (Client.objects
          .select_related("account_manager")
          .prefetch_related("categories")
          .order_by("name"))

    # Dropdown data (pulled from model choices so it stays in sync)
    client_types = Client.CLIENT_TYPES
    provinces = Client.PROVINCES
    account_types = Client.ACCOUNT_TYPES
    credit_statuses = Client.CREDIT_STATUS
    statuses = Client.STATUS
    filter_categories = Category.objects.filter(is_active=True).order_by("name")

    # GET params
    search = (request.GET.get("search") or "").strip()
    client_type = request.GET.get("client_type") or ""
    province = request.GET.get("province") or ""
    account_type = request.GET.get("account_type") or ""
    credit_status = request.GET.get("credit_status") or ""
    status = request.GET.get("status") or ""
    category_id = request.GET.get("category") or ""

    # Search
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(organization__icontains=search) |
            Q(contact_person__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search) |
            Q(whatsapp__icontains=search) |
            Q(suburb__icontains=search) |
            Q(city__icontains=search)
        )

    # Filters
    if client_type:
        qs = qs.filter(client_type=client_type)
    if province:
        qs = qs.filter(province=province)
    if account_type:
        qs = qs.filter(account_type=account_type)
    if credit_status:
        qs = qs.filter(credit_status=credit_status)
    if status:
        qs = qs.filter(status=status)
    if category_id.isdigit():
        qs = qs.filter(categories__id=int(category_id))

    clients = qs.distinct()

    return render(request, "clients/client_list.html", {
        "clients": clients,
        "filter_categories": filter_categories,
        "client_types": client_types,
        "provinces": provinces,
        "account_types": account_types,
        "credit_statuses": credit_statuses,
        "statuses": statuses,
    })


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            # Identity & Ownership
            "name", "organization", "client_type", "account_manager",
            "price_type",  # <-- added
            # Contact
            "contact_person", "email", "phone", "whatsapp",
            # Address
            "address_line1", "address_line2", "suburb", "city", "province",
            "postal_code", "country",
            # Compliance
            "vat_number", "company_reg_number",
            # Categorisation & Account
            "categories", "status", "account_type", "credit_status",
            # Spend & Notes
            "estimated_weekly_spend", "notes",
        ]
        widgets = {
            # text inputs
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "organization": forms.TextInput(attrs={"class": "form-control"}),
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "whatsapp": forms.TextInput(attrs={"class": "form-control"}),
            "address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "suburb": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "vat_number": forms.TextInput(attrs={"class": "form-control"}),
            "company_reg_number": forms.TextInput(attrs={"class": "form-control"}),
            "estimated_weekly_spend": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            # selects
            "client_type": forms.Select(attrs={"class": "form-select"}),
            "account_manager": forms.Select(attrs={"class": "form-select"}),
            "province": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "account_type": forms.Select(attrs={"class": "form-select"}),
            "credit_status": forms.Select(attrs={"class": "form-select"}),
            "price_type": forms.Select(attrs={"class": "form-select"}),  # <-- added
            # many-to-many
            "categories": forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only active categories in a nice order
        self.fields["categories"].queryset = Category.objects.filter(is_active=True).order_by("name")

        # Placeholders
        self.fields["email"].widget.attrs.setdefault("placeholder", "name@example.com")
        self.fields["phone"].widget.attrs.setdefault("placeholder", "e.g. 072 123 4567")
        self.fields["whatsapp"].widget.attrs.setdefault("placeholder", "e.g. 072 123 4567")

        # Optional: default to Retail if none chosen yet
        if not self.instance.pk and not self.initial.get("price_type"):
            self.fields["price_type"].initial = "Retail"



@login_required
@staff_required
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            messages.success(request, f"Client '{client.name}' created successfully.")
            return redirect("client-view", pk=client.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = ClientForm()

    return render(request, "clients/client_create.html", {"form": form})


@login_required
@staff_required
def client_edit(request, pk):
    client = get_object_or_404(
        Client.objects.select_related("account_manager").prefetch_related("categories"),
        pk=pk
    )

    if request.method == "POST":
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            client = form.save()
            messages.success(request, "Client updated successfully.")
            return redirect("client-view", pk=client.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = ClientForm(instance=client)

    return render(request, "clients/client_edit.html", {"form": form, "client": client})


@login_required
@staff_required
def client_view(request, pk):
    client = get_object_or_404(
        Client.objects.select_related("account_manager").prefetch_related("categories"),
        pk=pk
    )
    # Last 10 orders for this client; include fields we display
    orders = (
        Order.objects
        .filter(client=client)
        .only("id", "order_date", "status", "grand_total_inc")
        .order_by("-order_date")[:10]
    )

    return render(
        request,
        "clients/client_view.html",
        {
            "client": client,
            "orders": orders,  # NEW
            "success_message": request.GET.get("ok", ""),
            "error_message": request.GET.get("err", ""),
        },
    )