from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils.dateparse import parse_datetime, parse_date
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Count, Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from deliveries.models import DeliveryStop
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.conf import settings



from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum, Count, F, Q, Value, DecimalField, IntegerField, ExpressionWrapper
)

from django.shortcuts import render

from .models import Order, OrderItem
from clients.models import Client
from products.models import Category, Product
from django.forms import ModelForm, inlineformset_factory, widgets
from django.forms.models import inlineformset_factory
from django.contrib import messages
from profiles.models import StaffProfile



def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url='/portal/client/login/')

@login_required
@staff_required
def order_list(request):
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

    return render(request, "orders/order_list.html", {
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



class CreateOrderForm(ModelForm):

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
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),

            # 🔒 Visible but disabled
            "channel": widgets.Select(
                attrs={"class": "form-select", "disabled": "disabled"}
            ),

            "status": widgets.Select(
                attrs={"class": "form-select", "disabled": "disabled"}
            ),

            "customer_notes": widgets.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),

            "discount_total_excl": widgets.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),

            "delivery_fee_excl": widgets.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),

            "delivery_fee_vat_percent": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),

            "notes": widgets.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set preset values for display
        self.fields["channel"].initial = "STAFF"
        self.fields["status"].initial = "pending"

        # Mark fields as not required (since disabled fields don’t POST)
        self.fields["channel"].required = False
        self.fields["status"].required = False

    # 🔒 Hard-enforce system values
    def save(self, commit=True):
        instance = super().save(commit=False)

        instance.channel = "STAFF"
        instance.status = "pending"

        if commit:
            instance.save()

        return instance


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
@staff_required
def order_create(request):
    """
    Create an order + items with dynamic add/remove via formset.
    """
    if request.method == "POST":
        form = CreateOrderForm(request.POST)

        if form.is_valid():
            order = form.save(commit=False)

            if request.user.is_authenticated:
                order.created_by = request.user

            order.save()

            # Now bind formset to real saved order
            formset = OrderItemFormSet(
                request.POST,
                instance=order,
                prefix="items"
            )

            if formset.is_valid():
                formset.save()

                # roll-up totals after items saved
                order.recalc_totals(save=True)

                messages.success(request, f"Order #{order.id} created.")
                return redirect("order-view", pk=order.id)
        else:
            formset = OrderItemFormSet(
                request.POST,
                instance=Order(),
                prefix="items"
            )

    else:
        form = CreateOrderForm()
        formset = OrderItemFormSet(
            instance=Order(),
            prefix="items"
        )

    return render(
        request,
        "orders/order_create.html",
        {
            "form": form,
            "formset": formset,
            "prefix": "items",
        },
    )


@login_required
@staff_required
def order_edit(request, pk):
    """
    Edit an order and its items.
    Only allows edits for specific statuses.
    """

    order = get_object_or_404(
        Order.objects.select_related("client").prefetch_related("items__product", "items__category"),
        pk=pk,
    )

    # ✅ Allowed statuses
    ALLOWED_STATUSES = {
        "pending",
        "approved",
        "awaiting_payment",
        "credit_blocked",
    }

    # 🚫 Block editing if not allowed (GET protection)
    if order.status not in ALLOWED_STATUSES:
        messages.error(request, "Order cannot be updated currently.")
        return redirect("order-view", pk=order.id)

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(request.POST, instance=order, prefix="items")

        if form.is_valid() and formset.is_valid():

            # 🔒 Double-check (POST protection)
            if order.status not in ALLOWED_STATUSES:
                messages.error(request, "Order cannot be updated currently.")
                return redirect("order-view", pk=order.id)

            order = form.save()

            items = formset.save(commit=False)

            for item in items:
                item.order = order
                item.save()

            for deleted in formset.deleted_objects:
                deleted.delete()

            order.recalc_totals(save=True)

            messages.success(request, f"Order #{order.id} updated.")
            return redirect("order-view", pk=order.id)

    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(instance=order, prefix="items")

    return render(
        request,
        "orders/order_edit.html",
        {
            "order": order,
            "form": form,
            "formset": formset,
            "prefix": "items",
        },
    )


@login_required
@staff_required
def order_view(request, pk):
    order = get_object_or_404(
        Order.objects
        .select_related("client", "created_by", "reviewed_by", "approved_by")
        .prefetch_related("items__product", "items__category", "audits"),
        pk=pk
    )

    order.recalc_totals(save=False)

    try:
        invoice = order.invoice
    except Exception:
        invoice = None

    items = order.items.all().order_by("id")

    audits = order.audits.all().order_by("-performed_at")

    # 🔹 DELIVERY STOP
    delivery_stop = (
        DeliveryStop.objects
        .filter(order=order)
        .order_by("-id")
        .first()
    )

    return render(
        request,
        "orders/order_view.html",
        {
            "order": order,
            "items": items,
            "invoice": invoice,
            "audits": audits,
            "delivery_stop": delivery_stop,
        },
    )



@login_required
@staff_required
def order_delete(request, pk):
    """
    Delete an order only if the logged-in user's StaffProfile auth code matches
    the code typed into the confirmation modal. Uses StaffProfile.check_auth_code()
    if available; otherwise falls back to a plain string comparison (constant-time).
    """
    order = get_object_or_404(Order.objects.select_related("client"), pk=pk)

    if request.method != "POST":
        messages.error(request, "Please confirm deletion using the Delete button.")
        return redirect("order-view", pk=order.pk)

    auth_code = (request.POST.get("auth_code") or "").strip()
    if not auth_code:
        messages.error(request, "Authorisation code is required.")
        return redirect("order-view", pk=order.pk)

    profile = getattr(request.user, "staff_profile", None)
    if not profile:
        messages.error(
            request,
            "No staff profile found for your account. Ask an admin to set up your staff profile and authorisation code."
        )
        return redirect("order-view", pk=order.pk)

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
@staff_required
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
@staff_required
def delivery_note_view(request, stop_id):
    from deliveries.models import DeliveryStop

    stop = get_object_or_404(
        DeliveryStop.objects
        .select_related("order", "order__client", "run")
        .prefetch_related("order__items__product"),
        id=stop_id
    )

    order = stop.order
    items = order.items.all()

    return render(
        request,
        "orders/delivery_note.html",
        {
            "stop": stop,
            "order": order,
            "items": items,
        },
    )

@login_required
@staff_required
def send_delivery_note_email(request, stop_id):

    stop = get_object_or_404(
        DeliveryStop.objects.select_related(
            "order",
            "order__client"
        ).prefetch_related("order__items"),
        id=stop_id
    )

    order = stop.order
    client = order.client

    if not client.email:
        messages.error(request, "Client has no email address.")
        return redirect("delivery-note-view", stop_id=stop.id)

    ctx = {
        "stop": stop,
        "order": order,
        "client": client,
        "items": order.items.all(),
    }

    subject = f"Delivery Confirmation · Order #{order.id}"

    html_body = render_to_string(
        "email/delivery_note_email.html",
        ctx
    )

    text_body = render_to_string(
        "email/delivery_note_email.txt",
        ctx
    )

    msg = EmailMultiAlternatives(
        subject,
        text_body,
        settings.DEFAULT_FROM_EMAIL,
        [client.email],
    )

    msg.attach_alternative(html_body, "text/html")
    msg.send()

    messages.success(
        request,
        f"Delivery note sent to {client.email}"
    )

    return redirect("delivery-note-view", stop_id=stop.id)

