# C:\Seshibo Daily Market\seshibo_site\sales\views.py
from decimal import Decimal
from datetime import timedelta, date, datetime
from django.db import models as db_models  # <--- import db models utilities (Sum, Count, etc.)
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Count, Q
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
import calendar
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from clients.models import Prospect, ProspectUpdate, Client
from clients.forms import ProspectForm, ProspectUpdateForm
from products.models import Category
from django.utils.timezone import localdate
from invoices.models import CommissionEntry, MonthlyCommission  # adjust import path if needed
from orders.models import Order, OrderItem
from django import forms
from django.forms import ModelForm, inlineformset_factory, widgets
from django.db.models import (
    Sum, Count, F, Q, Value, DecimalField, IntegerField, ExpressionWrapper
)
from django.contrib.auth import get_user_model
from django.db.models.functions import Coalesce
from invoices.models import Invoice
from django.utils.timezone import now
from tasks.models import Task


User = get_user_model()
DAY_OPTIONS = [7, 14, 30, 60]

@login_required
def sales_dashboard(request):
    """
    Sales dashboard for reps.
    For now this uses simple placeholder values so the template renders
    without errors. You can replace these with real queries later.
    """

    # ----- Date range handling -----
    range_param = (request.GET.get("range") or "today").lower()
    now = timezone.now()
    today = timezone.localdate()

    if range_param == "7d":
        start_dt = now - timedelta(days=7)
        range_label = "Last 7 days"
        range_param = "7d"
    elif range_param == "month":
        # from first day of current month at midnight
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        range_label = "This month"
        range_param = "month"
    else:
        # default: today
        start_dt = timezone.make_aware(
            datetime.combine(today, datetime.min.time())
        )
        range_label = "Today"
        range_param = "today"

    end_dt = now

    # ----- Placeholder metrics (swap with real queries later) -----
    target_amount = Decimal("0.00")
    achieved_amount = Decimal("0.00")
    target_progress = 0
    deals_closed_count = 0

    pipeline_summary = []      # e.g. [{"stage_label": "New", "count": 5}, ...]
    prospects_total = 0
    recent_prospects = []      # e.g. [{"name": "ABC Restaurant", "stage_label": "Contacted"}, ...]

    recent_orders = []         # e.g. [{"id": 1, "created_at": ..., "client_name": "...", "total": ..., "status": "..."}]
    tasks = []                 # e.g. task objects/structs with .title, .due_at/.created_at, .is_done

    # Chart data – simple empty defaults for now
    sales_labels = []          # e.g. ["1", "2", "3", ...]
    sales_data = []            # e.g. [3, 5, 2, ...]

    context = {
        "range": range_param,
        "range_label": range_label,
        "target_amount": target_amount,
        "achieved_amount": achieved_amount,
        "target_progress": target_progress,
        "deals_closed_count": deals_closed_count,
        "pipeline_summary": pipeline_summary,
        "prospects_total": prospects_total,
        "recent_prospects": recent_prospects,
        "recent_orders": recent_orders,
        "tasks": tasks,
        "sales_labels": sales_labels,
        "sales_data": sales_data,
        "start_dt": start_dt,
        "end_dt": end_dt,
    }

    return render(request, "sales/dashboard.html", context)



@login_required
def prospects(request):
    """
    Sales prospects pipeline:
    - GET: list + filters + pipeline summary + sample stats
    - POST: quick 'Record Sample' from the modal at the top.
    """

    # ----- Handle quick 'Record Sample' POST from the modal -----
    if request.method == "POST":
        prospect_id = request.POST.get("prospect_id")
        if prospect_id:
            prospect = get_object_or_404(Prospect, pk=prospect_id)
            sample_details = (request.POST.get("sample_details") or "").strip()
            sample_date_str = (request.POST.get("sample_date") or "").strip()

            # Parse sample date; if invalid/missing, use now
            if sample_date_str:
                try:
                    # sample_date_str is just a date (YYYY-MM-DD)
                    sample_date = datetime.fromisoformat(sample_date_str)
                    if timezone.is_naive(sample_date):
                        sample_date = timezone.make_aware(sample_date)
                except ValueError:
                    sample_date = timezone.now()
            else:
                sample_date = timezone.now()

            old_stage = prospect.stage
            new_stage = old_stage
            if old_stage in ["NEW", "CONTACTED"]:
                new_stage = "SAMPLES_GIVEN"

            # Create the update
            ProspectUpdate.objects.create(
                prospect=prospect,
                user=request.user,
                action_type="SAMPLE",
                outcome="SAMPLE_DROPPED",
                action_at=sample_date,
                old_stage=old_stage,
                new_stage=new_stage,
                notes=sample_details,
            )

            # Update prospect stage + last_contact
            prospect.stage = new_stage
            prospect.last_contact_at = sample_date
            prospect.save(update_fields=["stage", "last_contact_at", "updated_at"])

        return redirect("sales-prospects")

    # ----- GET: filtering / listing -----
    qs = (
        Prospect.objects
        .select_related("owner")
        .annotate(
            samples_count=Count(
                "updates",
                filter=Q(updates__action_type="SAMPLE"),
                distinct=True,
            )
        )
    )

    # Search
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(organization__icontains=q)
            | Q(contact_name__icontains=q)
            | Q(notes__icontains=q)
        )

    # Stage filter (UI uses lowercase values; model uses uppercase codes)
    stage_filter = (request.GET.get("stage") or "").strip().upper()
    valid_stages = {code for code, _ in Prospect.STAGE_CHOICES}
    if stage_filter and stage_filter in valid_stages:
        qs = qs.filter(stage=stage_filter)

    # Has samples filter
    has_samples = (request.GET.get("has_samples") or "").strip()
    if has_samples == "yes":
        qs = qs.filter(samples_count__gt=0)
    elif has_samples == "no":
        qs = qs.filter(samples_count=0)

    # Total (after filters)
    prospects_total = qs.count()

    # Pipeline summary for the filtered set
    stage_label_map = dict(Prospect.STAGE_CHOICES)
    pipeline_raw = (
        qs.values("stage")
        .annotate(count=Count("id"))
        .order_by("stage")
    )
    pipeline_summary = [
        {
            "stage": row["stage"],
            "stage_label": stage_label_map.get(row["stage"], row["stage"]),
            "count": row["count"],
        }
        for row in pipeline_raw
    ]

    # Sample stats
    prospects_with_samples = qs.filter(samples_count__gt=0).count()
    samples_total = ProspectUpdate.objects.filter(
        prospect__in=qs,
        action_type="SAMPLE",
    ).count()
    samples_converted = (
        qs.filter(stage="WON", updates__action_type="SAMPLE")
        .distinct()
        .count()
    )

    if prospects_with_samples > 0:
        rate = int(round((samples_converted / prospects_with_samples) * 100))
        sample_conversion_rate = f"{rate}%"
    else:
        sample_conversion_rate = "0%"

    context = {
        "prospects": qs.order_by("-created_at"),
        "prospects_total": prospects_total,
        "pipeline_summary": pipeline_summary,
        "prospects_with_samples": prospects_with_samples,
        "samples_total": samples_total,
        "samples_converted": samples_converted,
        "sample_conversion_rate": sample_conversion_rate,
        "today": timezone.localdate(),  # used in the modal default date
    }
    return render(request, "prospects/prospects.html", context)


@login_required
def prospect_create(request):
    """
    Create a new prospect.
    """
    if request.method == "POST":
        form = ProspectForm(request.POST)
        if form.is_valid():
            prospect = form.save(commit=False)
            prospect.owner = request.user
            prospect.save()
            return redirect("sales-prospects")
    else:
        form = ProspectForm()

    return render(request, "prospects/prospect_form.html", {"form": form})


@login_required
def prospect_detail(request, pk: int):
    """
    Single prospect view with its update timeline.
    """
    prospect = get_object_or_404(
        Prospect.objects.select_related("owner"),
        pk=pk,
    )
    updates = (
        prospect.updates
        .select_related("user")
        .order_by("-action_at", "-created_at")
    )

    # Empty form for quick activity log from the detail page (if you want)
    update_form = ProspectUpdateForm(current_stage=prospect.stage)

    context = {
        "prospect": prospect,
        "updates": updates,
        "update_form": update_form,
    }
    return render(request, "prospects/prospect_detail.html", context)


@login_required
def prospect_update_create(request, prospect_id: int):
    """
    Log a new activity (call/WhatsApp/visit/sample/etc.) on a prospect.
    """
    prospect = get_object_or_404(Prospect, pk=prospect_id)

    if request.method == "POST":
        form = ProspectUpdateForm(
            request.POST,
            current_stage=prospect.stage,
        )
        form.instance.prospect = prospect
        form.instance.user = request.user

        if form.is_valid():
            form.save()
            # You can change this to the detail view if you prefer:
            # return redirect("sales-prospect-detail", pk=prospect.id)
            return redirect("sales-prospects")
    else:
        form = ProspectUpdateForm(current_stage=prospect.stage)

    return render(
        request,
        "prospects/prospect_update_form.html",
        {"form": form, "prospect": prospect},
    )


# -------------------------------------------------------------------
# Placeholder views for other sales sections (can be filled in later)
# -------------------------------------------------------------------
@login_required
def clients(request):
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

    return render(request, "clients/clients.html", {
        "clients": clients,
        "filter_categories": filter_categories,
        "client_types": client_types,
        "provinces": provinces,
        "account_types": account_types,
        "credit_statuses": credit_statuses,
        "statuses": statuses,
    })
    
def view_client(request, pk):
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
        "clients/client_detail.html",
        {
            "client": client,
            "orders": orders,  # NEW
            "success_message": request.GET.get("ok", ""),
            "error_message": request.GET.get("err", ""),
        },
    )

def edit_client(request, pk):
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

    return render(request, "clients/edit_client.html", {"form": form, "client": client})

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
def orders(request):
    qs = (
        Order.objects
        .select_related("client")
        .prefetch_related("items")
    )

    # Optional filters
    status = request.GET.get("status")
    channel = request.GET.get("channel")
    q = request.GET.get("q")

    if status:
        qs = qs.filter(status=status)
    if channel:
        qs = qs.filter(channel=channel)
    if q:
        qs = qs.filter(
            Q(client__name__icontains=q) |
            Q(client__organization__icontains=q) |
            Q(customer_notes__icontains=q) |
            Q(notes__icontains=q)
        )

    # Safe decimal fallbacks
    ZERO_DEC = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))
    ZERO_INT = Value(0, output_field=IntegerField())

    # A computed fallback for total (inc) if grand_total_inc is 0.00
    computed_total_fallback = ExpressionWrapper(
        Coalesce(F("subtotal_excl"), ZERO_DEC) +
        Coalesce(F("vat_total"), ZERO_DEC) +
        Coalesce(F("delivery_fee_excl"), ZERO_DEC),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    qs = qs.annotate(
        total_quantity=Coalesce(Sum("items__quantity"), ZERO_DEC, output_field=DecimalField(max_digits=12, decimal_places=2)),
        item_count=Coalesce(Count("items", distinct=True), ZERO_INT, output_field=IntegerField()),
        total_amount=Coalesce(
            F("grand_total_inc"),
            computed_total_fallback,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    ).order_by("-submitted_at").distinct()

    return render(request, "orders/orders.html", {
        "orders": qs,
        "filter_status": status or "",
        "filter_channel": channel or "",
        "search": q or "",
    })


class OrderForm(ModelForm):
    class Meta:
        model = Order
        fields = [
            "client",
            "order_date",
            "channel",
            "status",
            "customer_notes",
            "discount_total_excl",
            "delivery_fee_excl",
            "delivery_fee_vat_percent",
            "notes",
        ]
        widgets = {
            "client": widgets.Select(attrs={"class": "form-select"}),
            "order_date": widgets.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "channel": widgets.Select(attrs={"class": "form-select"}),
            "status": widgets.Select(attrs={"class": "form-select"}),
            "customer_notes": widgets.Textarea(attrs={"class": "form-control", "rows": 3}),
            "discount_total_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "delivery_fee_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "delivery_fee_vat_percent": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}),
            "notes": widgets.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class OrderItemForm(ModelForm):
    class Meta:
        model = OrderItem
        fields = [
            "category",
            "product",
            "quantity",
            "unit_price_excl",
            "discount_excl",
            "vat_percent",
        ]
        widgets = {
            "category": widgets.Select(attrs={"class": "form-select"}),
            "product": widgets.Select(attrs={"class": "form-select"}),
            "quantity": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "unit_price_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "discount_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "vat_percent": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}),
        }


OrderItemFormSet = inlineformset_factory(
    parent_model=Order,
    model=OrderItem,
    form=OrderItemForm,
    fields=["category", "product", "quantity", "unit_price_excl", "discount_excl", "vat_percent"],
    extra=0,               # rows added via JS using empty_form
    can_delete=True,
    validate_min=False,
    min_num=0,
)


# --- Views ---
@login_required
def create_order(request):
    """
    Create an order + items with dynamic add/remove via formset.
    """
    if request.method == "POST":
        form = OrderForm(request.POST)
        # validate items against a dummy instance; we’ll attach the saved order before saving items
        dummy_parent = Order()
        formset = OrderItemFormSet(request.POST, instance=dummy_parent, prefix="items")

        if form.is_valid() and formset.is_valid():
            order = form.save(commit=False)
            if request.user.is_authenticated:
                order.created_by = request.user
            order.save()

            formset.instance = order
            formset.save()

            # roll-up totals after items saved
            order.recalc_totals(save=True)

            messages.success(request, f"Order #{order.id} created.")
            return redirect("view-order", pk=order.id)
    else:
        form = OrderForm()
        formset = OrderItemFormSet(instance=Order(), prefix="items")  # empty; rows added with JS

    return render(
        request,
        "orders/create_order.html",
        {
            "form": form,
            "formset": formset,
            "prefix": "items",   # used by the template JS as a fallback
        },
    )


@login_required
def edit_order(request, pk):
    """
    Edit an order and its items.
    """
    order = get_object_or_404(
        Order.objects.select_related("client").prefetch_related("items__product", "items__category"),
        pk=pk,
    )

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(request.POST, instance=order, prefix="items")

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()

            # keep totals in sync
            order.recalc_totals(save=True)

            messages.success(request, f"Order #{order.id} updated.")
            return redirect("view-order", pk=order.id)
    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(instance=order, prefix="items")

    return render(
        request,
        "orders/edit_order.html",
        {
            "order": order,
            "form": form,
            "formset": formset,
            "prefix": "items",
        },
    )


@login_required
def view_order(request, pk):
    """
    Order detail view — shows order, items and related invoice (if any).
    Recalculates totals in-memory (no DB write) so displayed totals are fresh.
    """
    order = get_object_or_404(
        Order.objects
             .select_related("client", "created_by", "reviewed_by", "approved_by")
             .prefetch_related("items__product", "items__category"),
        pk=pk
    )

    # keep totals fresh (no DB write)
    # (assumes Order.recalc_totals(save=False) exists)
    try:
        order.recalc_totals(save=False)
    except Exception:
        # If recalc_totals doesn't exist or fails, we continue — it's not fatal for view rendering
        pass

    # invoice (if one-to-one exists)
    invoice = None
    try:
        invoice = order.invoice  # uses OneToOne relation if present
    except AttributeError:
        invoice = None
    except Exception:
        # fallback: if some other error occurs, don't crash the view
        invoice = None

    items = order.items.all().order_by("id")
    return render(request, "orders/view_order.html", {
        "order": order,
        "items": items,
        "invoice": invoice,
    })

@login_required
def delete_order(request, pk):
    """
    Delete an order only if the logged-in user's StaffProfile auth code matches
    the code typed into the confirmation modal. Uses StaffProfile.check_auth_code()
    if available; otherwise falls back to a plain string comparison (constant-time).
    """
    order = get_object_or_404(Order.objects.select_related("client"), pk=pk)

    if request.method != "POST":
        messages.error(request, "Please confirm deletion using the Delete button.")
        return redirect("view-order", pk=order.pk)

    auth_code = (request.POST.get("auth_code") or "").strip()
    if not auth_code:
        messages.error(request, "Authorisation code is required.")
        return redirect("view-order", pk=order.pk)

    profile = getattr(request.user, "staff_profile", None)
    if not profile:
        messages.error(
            request,
            "No staff profile found for your account. Ask an admin to set up your staff profile and authorisation code."
        )
        return redirect("view=order", pk=order.pk)

    # Validate the code
    is_valid = False
    # Preferred: secure check if your model provides it
    if hasattr(profile, "check_auth_code"):
        try:
            is_valid = profile.check_auth_code(auth_code)
        except Exception:
            is_valid = False
    else:
        # Fallback if you stored a plain code field named 'employee_auth_code'
        stored = getattr(profile, "employee_auth_code", "") or ""
        # constant-time compare
        is_valid = bool(stored) and hmac.compare_digest(stored, auth_code)

    if not is_valid:
        messages.error(request, "Invalid authorisation code.")
        return redirect("order-view", pk=order.pk)

    # All good – delete the order
    oid = order.pk
    client_label = str(order.client)
    try:
        with transaction.atomic():
            order.delete_with_audit(
            request=request,
            reason=request.POST.get("reason", ""),
            auth_verified=True,            # you already validated the staff code
            auth_method="staff_code",
        )

        messages.success(request, f"Order #{oid} ({client_label}) was deleted.")
        return redirect("staff-orders")
    except Exception as e:
        messages.error(request, f"Could not delete order: {e}")
        return redirect("order-view", pk=oid)
        order.delete



@login_required
def ajax_products_by_category(request):
    cat_id = request.GET.get("category_id")
    if not cat_id:
        return JsonResponse({"results": []})

    qs = (
        Product.objects
        .filter(category_id=cat_id)
        .order_by("name")
        .values("id", "sku", "name", "uom")
    )
    results = [{"id": p["id"], "text": f'{p["sku"]} · {p["name"]} ({p["uom"]})'} for p in qs]
    return JsonResponse({"results": results})


@login_required
def invoices(request):
    """
    List invoices with optional filters:
      - q: search across client name, client organization, order CL number
      - status: invoice status (unpaid/partial/paid/overdue)
      - from / to: invoice_date range (YYYY-MM-DD)
      - page: paginator page
    """
    qs = Invoice.objects.select_related("client", "order").all().order_by("-invoice_date", "-created_at")

    # --- Filters from GET ---
    search = request.GET.get("q", "").strip()
    filter_status = request.GET.get("status", "").strip()
    date_from = request.GET.get("from", "").strip()
    date_to = request.GET.get("to", "").strip()

    if search:
        qs = qs.filter(
            Q(client__name__icontains=search) |
            Q(client__organization__icontains=search) |
            Q(order__cl_number__icontains=search)
        )

    if filter_status:
        qs = qs.filter(status=filter_status)

    if date_from:
        try:
            qs = qs.filter(invoice_date__gte=date_from)
        except Exception:
            # ignore invalid date formats (template will just show nothing)
            pass

    if date_to:
        try:
            qs = qs.filter(invoice_date__lte=date_to)
        except Exception:
            pass

    # --- Pagination (optional) ---
    per_page = 25
    page = request.GET.get("page", 1)
    paginator = Paginator(qs, per_page)
    try:
        invoices_page = paginator.page(page)
    except PageNotAnInteger:
        invoices_page = paginator.page(1)
    except EmptyPage:
        invoices_page = paginator.page(paginator.num_pages)

    # --- status choices for template ---
    status_choices = Invoice.STATUS_CHOICES  # tuples (val, label)

    context = {
        "invoices": invoices_page,        # page object (iterable in template)
        "search": search,
        "status_choices": status_choices,
        "filter_status": filter_status,
        "date_from": date_from,
        "date_to": date_to,
        "paginator": paginator,
        "page_obj": invoices_page,
    }

    return render(request, "invoices/invoices.html", context)
    

@login_required
def view_invoice(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "client", "order", "order__client", "order__created_by"
        ).prefetch_related(
            "order__items", "order__items__product", "order__items__category"
        ),
        pk=pk,
    )

    order = invoice.order
    client = invoice.client
    items = order.items.all()

    today = localdate()
    is_overdue = (
        invoice.status != "paid"
        and invoice.due_date is not None
        and invoice.due_date < today
    )
    deposit_outstanding = max(invoice.amount_due - (invoice.deposit_paid or 0), 0)

    return render(
        request,
        "invoices/view_invoice.html",
        {
            "invoice": invoice,
            "order": order,
            "client": client,
            "items": items,
            "is_overdue": is_overdue,
            "deposit_outstanding": deposit_outstanding,
        },
    )


@login_required
def commission(request):
    """
    Commission dashboard view with filtering:
      - Admins (is_staff or in 'Administrator' group) can view all agents and choose agent via ?agent=<id>
      - Non-admins only see their own commissions; agent selector is hidden.
      - Optional date filters: ?from=YYYY-MM-DD and ?to=YYYY-MM-DD
    """
    user = request.user

    # Admin check (staff or member of Administrator group)
    is_admin = user.is_staff or user.groups.filter(name="Administrator").exists()

    # If admin: provide agents list (users who manage clients)
    agents = None
    if is_admin:
        # Users that have at least one managed client (managed_clients related_name)
        agents = User.objects.filter(managed_clients__isnull=False).distinct().order_by("first_name", "last_name", "username")

    # Determine target_rep:
    # - Admin can optionally view a specific agent via ?agent=<id>
    # - Non-admin always restricted to themselves
    target_rep = None
    if is_admin:
        agent_param = request.GET.get("agent")
        if agent_param:
            try:
                target_rep = User.objects.get(pk=int(agent_param))
            except (User.DoesNotExist, ValueError):
                target_rep = None
    else:
        target_rep = user

    # Parse optional date filters
    def _parse_date(s):
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except Exception:
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except Exception:
                return None

    date_from = _parse_date(request.GET.get("from"))
    date_to = _parse_date(request.GET.get("to"))

    # Default periods (week and month)
    today = localdate()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    current_year = today.year
    current_month = today.month
    current_month_name = today.strftime("%B")

    # If user provided a custom date range, use that as the "month" period shown on cards;
    # otherwise use calendar month
    if date_from and date_to:
        month_first = date_from
        month_last = date_to
    else:
        month_first = date(current_year, current_month, 1)
        month_last = date(current_year, current_month, calendar.monthrange(current_year, current_month)[1])

    # Base queryset for commission entries (paid invoices)
    entries_qs = CommissionEntry.objects.select_related("invoice", "invoice__client", "rep").order_by("-invoice__paid_date")

    # Apply rep filter if applicable
    if target_rep:
        entries_qs = entries_qs.filter(rep=target_rep)

    # Week queryset (Mon-Sun)
    week_qs = entries_qs.filter(invoice__paid_date__gte=week_start, invoice__paid_date__lte=week_end)
    this_week_agg = week_qs.aggregate(total=db_models.Sum("amount"))
    this_week_total = this_week_agg.get("total") or Decimal("0.00")
    this_week_count = week_qs.count()

    # Month (or custom range) queryset
    month_qs = entries_qs
    if month_first:
        month_qs = month_qs.filter(invoice__paid_date__gte=month_first)
    if month_last:
        month_qs = month_qs.filter(invoice__paid_date__lte=month_last)

    month_agg = month_qs.aggregate(total=db_models.Sum("amount"))
    this_month_total = month_agg.get("total") or Decimal("0.00")

    # MonthlyCommission lookup (only meaningful when target_rep is a single user and using current calendar month)
    monthly_commission = None
    this_month_unpaid = Decimal("0.00")
    this_month_bonus = Decimal("0.00")
    this_month_bonus_eligible = False
    if target_rep and not (date_from and date_to):
        monthly_commission = MonthlyCommission.objects.filter(rep=target_rep, year=current_year, month=current_month).first()
        if monthly_commission:
            if not monthly_commission.paid:
                this_month_unpaid = monthly_commission.total_payout or Decimal("0.00")
            this_month_bonus = monthly_commission.monthly_cash_bonus or Decimal("0.00")
            this_month_bonus_eligible = (monthly_commission.monthly_cash_bonus and monthly_commission.monthly_cash_bonus > 0)

    # Commission entries for the table (limit for performance). Consider pagination for production.
    commission_entries = month_qs[:200]

    context = {
        "is_admin_viewing": is_admin,
        "agents": agents,
        "target_rep": target_rep,
        "this_week_total": this_week_total,
        "this_week_count": this_week_count,
        "week_start": week_start,
        "week_end": week_end,
        "this_month_total": this_month_total,
        "this_month_unpaid": this_month_unpaid,
        "this_month_bonus": this_month_bonus,
        "this_month_bonus_eligible": this_month_bonus_eligible,
        "current_month_name": current_month_name,
        "current_year": current_year,
        "commission_entries": commission_entries,
        "monthly_commission": monthly_commission,
        "filter_date_from": date_from,
        "filter_date_to": date_to,
    }
    return render(request, "commission/commission.html", context)

@login_required
def commission_view(request, pk):
    # get the commission entry
    commission = get_object_or_404(CommissionEntry, pk=pk)

    # Security: staff can view any; non-staff can view only if they are the owner
    if not request.user.is_staff and commission.rep != request.user:
        # You can render a 403 template or raise PermissionDenied
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied()

    return render(request, "commission/commission_view.html", {"commission": commission})


def _parse_date_local(date_str: str):
    """Parse YYYY-MM-DD to aware start/end of that day in local TZ."""
    try:
        d = datetime.fromisoformat(date_str).date()
        start_naive = datetime.combine(d, time.min)
        end_naive = datetime.combine(d, time.max)
        return timezone.make_aware(start_naive), timezone.make_aware(end_naive)
    except Exception:
        return None, None

@login_required
def tickets(request):
    """
    Staff task board with filters:
    - q: search in title/description
    - status: PENDING|OPEN|CLOSED
    - priority: LOW|MEDIUM|HIGH|URGENT
    - department: Department choices
    - mine=1: only tasks assigned to me
    - period: 7|14|30|60 (days back, by created_at)
    - due_from/due_to: YYYY-MM-DD range on due_at
    - order: created_at|-created_at|due_at|-due_at|priority|-priority|status|-status|department|-department|title|-title
    - page, per_page
    """
    qs = Task.objects.select_related("assigned_to", "content_type")

    # --- Query params ---
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    department = (request.GET.get("department") or "").strip()
    mine = request.GET.get("mine") == "1"
    period = (request.GET.get("period") or "").strip()
    due_from = (request.GET.get("due_from") or "").strip()
    due_to = (request.GET.get("due_to") or "").strip()

    # Search
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    # Choice filters
    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if department:
        qs = qs.filter(department=department)
    if mine:
        qs = qs.filter(assigned_to=request.user)

    # Period (created_at)
    if period.isdigit() and int(period) in (7, 14, 30, 60):
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=int(period)))

    # Due range (due_at)
    if due_from:
        start_from, _ = _parse_date_local(due_from)
        if start_from:
            qs = qs.filter(due_at__gte=start_from)
    if due_to:
        _, end_to = _parse_date_local(due_to)
        if end_to:
            qs = qs.filter(due_at__lte=end_to)

    # Ordering
    allowed_order = {
        "created_at", "-created_at",
        "due_at", "-due_at",
        "priority", "-priority",
        "status", "-status",
        "department", "-department",
        "title", "-title",
    }
    order = request.GET.get("order") or "-created_at"
    if order not in allowed_order:
        order = "-created_at"
    qs = qs.order_by(order)

    # Stats (global, not filtered)
    now = timezone.now()
    base = Task.objects.all()
    stats = {
        "total": base.count(),
        "mine": base.filter(assigned_to=request.user).count(),
        "open": base.filter(status__in=[Task.Status.PENDING, Task.Status.OPEN]).count(),
        "closed": base.filter(status=Task.Status.CLOSED).count(),
        "overdue": base.filter(
            due_at__lt=now,
            status__in=[Task.Status.PENDING, Task.Status.OPEN],
        ).count(),
        "by_status": dict(base.values_list("status").annotate(c=Count("id"))),
        "by_department": dict(base.values_list("department").annotate(c=Count("id"))),
    }

    # Pagination
    per_page_qs = request.GET.get("per_page")
    try:
        per_page = max(1, min(int(per_page_qs or 25), 200))
    except Exception:
        per_page = 25

    paginator = Paginator(qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # Optional flash messages
    success_message = request.GET.get("ok") or ""
    error_message = request.GET.get("err") or ""

    ctx = {
        "page_obj": page_obj,
        "object_list": page_obj.object_list,
        "stats": stats,
        "filters": {
            "q": q,
            "status": status,
            "priority": priority,
            "department": department,
            "mine": mine,
            "period": period,
            "due_from": due_from,
            "due_to": due_to,
            "order": order,
            "per_page": per_page,
        },
        "choices": {
            "status": Task.Status.choices,
            "priority": Task.Priority.choices,
            "department": Task.Department.choices,
        },
        "ui": {
            "period_options": [7, 14, 30, 60],
            "order_options": [
                "created_at", "-created_at",
                "due_at", "-due_at",
                "priority", "-priority",
                "status", "-status",
                "department", "-department",
                "title", "-title",
            ],
            "per_page_options": [10, 25, 50, 100, 200],
        },
        "success_message": success_message,
        "error_message": error_message,
    }
    return render(request, "tickets/tickets.html", ctx)





# --- Optional quick actions (wire to buttons/links if needed) ---
@login_required
def task_close(request, pk: int):
    task = Task.objects.filter(pk=pk).first()
    if not task:
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Task+not+found")
    if not (request.user.is_staff or request.user == task.assigned_to or request.user == task.created_by):
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Not+authorized")
    task.status = Task.Status.CLOSED
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?ok=Task+closed")


@login_required
def task_reopen(request, pk: int):
    task = Task.objects.filter(pk=pk).first()
    if not task:
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Task+not+found")
    if not (request.user.is_staff or request.user == task.assigned_to or request.user == task.created_by):
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Not+authorized")
    task.status = Task.Status.OPEN
    task.completed_at = None
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?ok=Task+reopened")


@login_required
def view_ticket(request, pk):
    task = get_object_or_404(Task, pk=pk)

    # Optional: load comments if you have a TaskComment model with FK "task" and related_name "comments"
    try:
        comments_qs = task.comments.order_by("-created_at")
    except Exception:
        comments_qs = []

    # Optional: build a related URL if the linked object exposes get_absolute_url()
    related_url = None
    if task.related_object:
        try:
            if hasattr(task.related_object, "get_absolute_url"):
                related_url = task.related_object.get_absolute_url()
        except Exception:
            related_url = None

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        # Basic authorization: staff OR the assignee OR the creator
        is_authorized = (
            request.user.is_staff
            or request.user == getattr(task, "assigned_to", None)
            or request.user == getattr(task, "created_by", None)
        )
        if not is_authorized:
            messages.error(request, "Not authorized to update this task.")
            return redirect(request.path)

        if action == "close":
            task.status = Task.Status.CLOSED
            task.completed_at = timezone.now()
            task.save(update_fields=["status", "completed_at", "updated_at"])
            messages.success(request, "Task closed.")
            return redirect(request.path)

        elif action == "pending":
            task.status = Task.Status.PENDING
            # keep completed_at as-is (usually None or a past value)
            task.save(update_fields=["status", "updated_at"])
            messages.success(request, "Task marked as pending.")
            return redirect(request.path)

        elif action == "reopen":
            task.status = Task.Status.OPEN
            task.completed_at = None
            task.save(update_fields=["status", "completed_at", "updated_at"])
            messages.success(request, "Task reopened.")
            return redirect(request.path)

        elif action == "add_comment":
            body = (request.POST.get("comment") or "").strip()
            if not body:
                messages.error(request, "Comment cannot be empty.")
                return redirect(request.path)

            # Only if you have a TaskComment model
            try:
                from .models import TaskComment  # adjust import if located elsewhere
                TaskComment.objects.create(
                    task=task,
                    body=body,
                    author=request.user if request.user.is_authenticated else None,
                    author_name=str(request.user) if request.user.is_authenticated else "System",
                )
                messages.success(request, "Comment added.")
            except Exception:
                messages.error(request, "Comments are not enabled.")
            return redirect(request.path)

        elif action == "delete":
            # Optional: allow only staff or creator to delete
            if not (request.user.is_staff or request.user == getattr(task, "created_by", None)):
                messages.error(request, "Not authorized to delete this task.")
                return redirect(request.path)
            task.delete()
            messages.success(request, "Task deleted.")
            return redirect("tasks")  # back to list

        else:
            messages.error(request, "Unknown action.")
            return redirect(request.path)

    # GET: render page
    return render(
        request,
        "tickets/view_ticket.html",
        {
            "task": task,
            "comments": comments_qs,
            "related_url": related_url,
        },
    )



@login_required
def profile(request):
    return render(request, "profile/profile.html")
