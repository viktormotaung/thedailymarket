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
from django.db import transaction
from datetime import timedelta
from django.utils import timezone
import django.forms as forms
from decimal import Decimal
from django.shortcuts import render, get_object_or_404
from .models import Quotation
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum, Count, F, Q, Value, DecimalField, IntegerField, ExpressionWrapper
)
from communications.services.whatsapp import send_quotation_whatsapp
from django.shortcuts import render
from communications.services.whatsapp import (
    send_quotation_whatsapp
)
from .models import Order, OrderItem, Quotation, QuotationItem
from clients.models import Client
from products.models import Category, Product
from django.forms import ModelForm, inlineformset_factory, widgets
from django.forms.models import inlineformset_factory
from django.contrib import messages
from profiles.models import StaffProfile

from communications.models import CommunicationLog
from communications.services.whatsapp import send_quotation_whatsapp
from django.utils import timezone
from django.views.decorators.http import require_POST

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

    ZERO_DEC = Value(
        Decimal("0.00"),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    ZERO_INT = Value(
        0,
        output_field=IntegerField()
    )

    line_excl_expr = ExpressionWrapper(
        (
            Coalesce(F("items__unit_price_excl"), ZERO_DEC) -
            Coalesce(F("items__discount_excl"), ZERO_DEC)
        ) * Coalesce(F("items__quantity"), ZERO_DEC),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    vat_expr = ExpressionWrapper(
        line_excl_expr * (
            Coalesce(F("items__vat_percent"), ZERO_DEC) / Decimal("100.00")
        ),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    qs = (
        qs.annotate(
            total_quantity=Coalesce(
                Sum("items__quantity"),
                ZERO_DEC,
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),
            item_count=Coalesce(
                Count("items", distinct=True),
                ZERO_INT,
                output_field=IntegerField()
            ),
            total_excl=Coalesce(
                Sum(line_excl_expr),
                ZERO_DEC,
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),
            total_vat=Coalesce(
                Sum(vat_expr),
                ZERO_DEC,
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),
        )
        .annotate(
            total_amount=ExpressionWrapper(
                F("total_excl") + F("total_vat"),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
        .order_by("-submitted_at")
        .distinct()
    )

    return render(
        request,
        "orders/order_list.html",
        {
            "orders": qs,
            "filter_status": status or "",
            "filter_channel": channel or "",
            "search": q or "",
        }
    )



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
    order = get_object_or_404(
        Order.objects
        .select_related("client")
        .prefetch_related("items__product", "items__category"),
        pk=pk,
    )

    invoice = getattr(order, "invoice", None)

    if invoice and invoice.status == "paid":
        messages.error(request, "Paid orders cannot be edited.")
        return redirect("order-view", pk=order.id)

    ALLOWED_STATUSES = {
        "pending",
        "approved",
        "awaiting_payment",
        "credit_blocked",
    }

    if order.status not in ALLOWED_STATUSES:
        messages.error(request, "Order cannot be updated currently.")
        return redirect("order-view", pk=order.id)

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(
            request.POST,
            instance=order,
            prefix="items"
        )

        if form.is_valid() and formset.is_valid():

            invoice = getattr(order, "invoice", None)

            if invoice and invoice.status == "paid":
                messages.error(request, "Paid orders cannot be edited.")
                return redirect("order-view", pk=order.id)

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

        messages.error(request, "Please correct the errors below.")

    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(
            instance=order,
            prefix="items"
        )

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

    invoice_paid = False
    if invoice and invoice.status == "paid":
        invoice_paid = True

    items = order.items.all().order_by("id")

    item_rows = []

    for item in items:
        qty = item.quantity or Decimal("0.00")
        unit_excl = item.unit_price_excl or Decimal("0.00")
        discount_per_unit = item.discount_excl or Decimal("0.00")
        vat_pct = item.vat_percent or Decimal("0.00")

        gross_excl = unit_excl * qty
        discount_total = discount_per_unit * qty
        line_excl = gross_excl - discount_total
        vat_amount = line_excl * (vat_pct / Decimal("100.00"))
        line_inc = line_excl + vat_amount

        discount_pct = Decimal("0.00")
        if unit_excl > 0 and discount_per_unit > 0:
            discount_pct = (discount_per_unit / unit_excl) * Decimal("100.00")

        item_rows.append({
            "item": item,
            "qty": qty,
            "unit_excl": unit_excl,
            "discount_per_unit": discount_per_unit,
            "discount_total": discount_total,
            "discount_pct": discount_pct,
            "vat_pct": vat_pct,
            "line_excl": line_excl,
            "vat_amount": vat_amount,
            "line_inc": line_inc,
        })

    audits = order.audits.all().order_by("-performed_at")

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
            "item_rows": item_rows,
            "invoice": invoice,
            "invoice_paid": invoice_paid,
            "audits": audits,
            "delivery_stop": delivery_stop,
        },
    )

@login_required
@staff_required
def order_delete(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("client"),
        pk=pk
    )

    invoice = getattr(order, "invoice", None)

    if invoice and invoice.status == "paid":
        messages.error(request, "Paid orders cannot be deleted.")
        return redirect("order-view", pk=order.pk)

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

    is_valid = False

    if hasattr(profile, "check_auth_code"):
        try:
            is_valid = profile.check_auth_code(auth_code)
        except Exception:
            is_valid = False
    else:
        stored = getattr(profile, "employee_auth_code", "") or ""
        is_valid = bool(stored) and hmac.compare_digest(stored, auth_code)

    if not is_valid:
        messages.error(request, "Invalid authorisation code.")
        return redirect("order-view", pk=order.pk)

    oid = order.pk
    client_label = str(order.client)

    try:
        with transaction.atomic():
            order.delete_with_audit(
                request=request,
                reason=request.POST.get("reason", ""),
                auth_verified=True,
                auth_method="staff_code",
            )

        messages.success(request, f"Order #{oid} ({client_label}) was deleted.")
        return redirect("staff-orders")

    except Exception as e:
        messages.error(request, f"Could not delete order: {e}")
        return redirect("order-view", pk=oid)

@login_required
@staff_required
def ajax_products_by_category(request):
    cat_id = request.GET.get("category_id")

    if not cat_id:
        return JsonResponse({"results": []})

    products = (
        Product.objects
        .filter(category_id=cat_id)
        .prefetch_related("pricing_rows")
        .order_by("name")
    )

    results = []

    for product in products:
        best_price_excl = None
        best_vat_percent = None

        active_pricing_rows = product.pricing_rows.filter(is_active=True)

        for pricing in active_pricing_rows:
            price_excl = pricing.wholesale_price_excl
            vat_percent = pricing.wholesale_vat_percent

            if price_excl is None or price_excl <= Decimal("0.00"):
                continue

            if best_price_excl is None or price_excl < best_price_excl:
                best_price_excl = price_excl
                best_vat_percent = vat_percent

        if best_price_excl is not None:

            vat_multiplier = (
                Decimal("1.00") +
                (best_vat_percent / Decimal("100.00"))
            )

            best_price_incl = (
                best_price_excl * vat_multiplier
            ).quantize(Decimal("0.01"))

            text = (
                f"{product.sku} · {product.name} "
                f"({product.uom}) — "
                f"R{best_price_excl:.2f} excl · "
                f"R{best_price_incl:.2f} incl"
            )
        else:
            text = (
                f"{product.sku} · {product.name} "
                f"({product.uom}) — No active price"
            )

        results.append({
            "id": product.id,
            "text": text,
            "price_excl": str(best_price_excl or Decimal("0.00")),
            "vat_percent": str(best_vat_percent or Decimal("0.00")),
        })

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



@login_required
@staff_required
def quotation_list(request):

    qs = (
        Quotation.objects
        .select_related(
            "client",
            "prospect",
            "created_by",
            "converted_order",
            "accepted_by",
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    status = request.GET.get("status")
    q = request.GET.get("q")

    if status:
        qs = qs.filter(status=status)

    if q:
        qs = qs.filter(
            Q(client__name__icontains=q) |
            Q(client__organization__icontains=q) |

            Q(prospect__name__icontains=q) |
            Q(prospect__organization__icontains=q) |

            Q(customer_notes__icontains=q) |
            Q(notes__icontains=q)
        )

    return render(
        request,
        "orders/quotation_list.html",
        {
            "quotations": qs,
            "filter_status": status or "",
            "search": q or "",
            "current": "staff-quotations",
        }
    )


# =========================================================
# FORMS
# =========================================================

class QuotationCreateForm(ModelForm):

    quotation_target = forms.ChoiceField(
        choices=[
            ("client", "Existing Client"),
            ("prospect", "Prospect"),
        ],
        widget=forms.RadioSelect,
        initial="client",
        required=True,
    )

    class Meta:
        model = Quotation

        fields = [
            "quotation_target",

            "client",
            "prospect",

            "customer_notes",

            "discount_total_excl",
            "delivery_fee_excl",
            "delivery_fee_vat_percent",

            "notes",
        ]

        widgets = {

            "client": widgets.Select(
                attrs={"class": "form-select"}
            ),

            "prospect": widgets.Select(
                attrs={"class": "form-select"}
            ),

            "customer_notes": widgets.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),

            "discount_total_excl": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "delivery_fee_excl": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
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
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def clean(self):

        cleaned = super().clean()

        target = cleaned.get("quotation_target")
        client = cleaned.get("client")
        prospect = cleaned.get("prospect")

        if target == "client":

            if not client:
                raise ValidationError(
                    "Please select a client."
                )

            cleaned["prospect"] = None

        elif target == "prospect":

            if not prospect:
                raise ValidationError(
                    "Please select a prospect."
                )

            cleaned["client"] = None

        return cleaned


class QuotationEditForm(ModelForm):

    class Meta:
        model = Quotation

        fields = [
            "client",
            "prospect",

            "status",

            "customer_notes",

            "discount_total_excl",
            "delivery_fee_excl",
            "delivery_fee_vat_percent",

            "notes",
        ]

        widgets = {

            "client": widgets.Select(
                attrs={"class": "form-select"}
            ),

            "prospect": widgets.Select(
                attrs={"class": "form-select"}
            ),

            "status": widgets.Select(
                attrs={"class": "form-select"}
            ),

            "customer_notes": widgets.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),

            "discount_total_excl": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "delivery_fee_excl": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
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
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }


# =========================================================
# ITEM FORM
# =========================================================

class QuotationItemForm(ModelForm):

    class Meta:
        model = QuotationItem

        fields = [
            "category",
            "product",
            "quantity",
            "unit_price_excl",
            "discount_excl",
            "vat_percent",
        ]

        widgets = {

            "category": widgets.Select(
                attrs={"class": "form-select"}
            ),

            "product": widgets.Select(
                attrs={"class": "form-select"}
            ),

            "quantity": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0.01",
                }
            ),

            "unit_price_excl": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "readonly": True,
                }
            ),

            "discount_excl": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "vat_percent": widgets.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                    "readonly": True,
                }
            ),
        }


QuotationItemFormSet = inlineformset_factory(
    parent_model=Quotation,
    model=QuotationItem,
    form=QuotationItemForm,

    fields=[
        "category",
        "product",
        "quantity",
        "unit_price_excl",
        "discount_excl",
        "vat_percent",
    ],

    extra=0,
    can_delete=True,

    validate_min=False,
    min_num=0,
)


# =========================================================
# CREATE
# =========================================================

@login_required
@staff_required
def quotation_create(request):

    print("\n========== QUOTATION CREATE START ==========")

    if request.method == "POST":

        print("[DEBUG] POST received")
        print("[DEBUG] POST data:", request.POST)

        form = QuotationCreateForm(request.POST)

        formset = QuotationItemFormSet(
            request.POST,
            prefix="items"
        )

        print("[DEBUG] Form valid?", form.is_valid())
        print("[DEBUG] Form errors:", form.errors)

        print("[DEBUG] Formset valid?", formset.is_valid())
        print("[DEBUG] Formset errors:", formset.errors)

        if form.is_valid() and formset.is_valid():

            try:

                with transaction.atomic():

                    quotation = form.save(commit=False)

                    quotation.created_by = request.user
                    quotation.status = "draft"

                    quotation.quotation_date = timezone.now()

                    quotation.valid_until = (
                        timezone.now() + timedelta(hours=72)
                    ).date()

                    quotation.save()

                    print("[DEBUG] Quotation saved:", quotation.id)

                    items = formset.save(commit=False)

                    for item in items:
                        item.quotation = quotation
                        item.save()

                    for deleted in formset.deleted_objects:
                        deleted.delete()

                    quotation.recalc_totals(save=True)

                    print("[DEBUG] Totals recalculated")

                messages.success(
                    request,
                    f"Quotation #{quotation.id} created."
                )

                print("========== QUOTATION CREATE SUCCESS ==========\n")

                return redirect("staff-quotations")

            except Exception as e:

                print("[ERROR]", e)

                messages.error(
                    request,
                    f"Quotation could not be created: {e}"
                )

        else:

            messages.error(
                request,
                "Please correct the errors below."
            )

    else:

        form = QuotationCreateForm()

        formset = QuotationItemFormSet(
            prefix="items"
        )

    print("========== QUOTATION CREATE END ==========\n")

    return render(
        request,
        "orders/quotation_create.html",
        {
            "form": form,
            "formset": formset,
            "prefix": "items",
        },
    )


# =========================================================
# VIEW
# =========================================================

@login_required
@staff_required
def quotation_view(request, pk):

    quotation = get_object_or_404(
        Quotation.objects
        .select_related(
            "client",
            "prospect",
            "created_by",
            "accepted_by",
            "converted_order",
        )
        .prefetch_related(
            "items__product",
            "items__category",
        ),
        pk=pk
    )

    quotation.recalc_totals(save=False)

    item_rows = []

    for item in quotation.items.all().order_by("id"):

        qty = item.quantity or Decimal("0.00")

        unit_excl = item.unit_price_excl or Decimal("0.00")

        discount_per_unit = item.discount_excl or Decimal("0.00")

        vat_pct = item.vat_percent or Decimal("0.00")

        gross_excl = unit_excl * qty

        discount_total = discount_per_unit * qty

        line_excl = gross_excl - discount_total

        vat_amount = line_excl * (
            vat_pct / Decimal("100.00")
        )

        line_inc = line_excl + vat_amount

        discount_pct = Decimal("0.00")

        if unit_excl > 0 and discount_per_unit > 0:
            discount_pct = (
                discount_per_unit / unit_excl
            ) * Decimal("100.00")

        item_rows.append({
            "item": item,
            "qty": qty,
            "unit_excl": unit_excl,
            "discount_per_unit": discount_per_unit,
            "discount_total": discount_total,
            "discount_pct": discount_pct,
            "vat_pct": vat_pct,
            "line_excl": line_excl,
            "vat_amount": vat_amount,
            "line_inc": line_inc,
        })

    return render(
        request,
        "orders/quotation_view.html",
        {
            "quotation": quotation,
            "item_rows": item_rows,
        }
    )


# =========================================================
# EDIT
# =========================================================

@login_required
@staff_required
def quotation_edit(request, pk):

    quotation = get_object_or_404(
        Quotation.objects
        .select_related(
            "client",
            "prospect",
            "created_by",
            "converted_order",
        )
        .prefetch_related(
            "items__product",
            "items__category",
        ),
        pk=pk,
    )

    if quotation.converted_order_id:

        messages.error(
            request,
            "This quotation has already been converted to an order and cannot be edited."
        )

        return redirect(
            "quotation-view",
            pk=quotation.id
        )

    if quotation.status not in ["draft", "sent"]:

        messages.error(
            request,
            "Only draft or sent quotations can be edited."
        )

        return redirect(
            "quotation-view",
            pk=quotation.id
        )

    old_status = quotation.status

    if request.method == "POST":

        form = QuotationEditForm(
            request.POST,
            instance=quotation
        )

        formset = QuotationItemFormSet(
            request.POST,
            instance=quotation,
            prefix="items"
        )

        if form.is_valid() and formset.is_valid():

            try:

                with transaction.atomic():

                    quotation = form.save(commit=False)

                    quotation.created_by = (
                        quotation.created_by or request.user
                    )

                    quotation.save()

                    items = formset.save(commit=False)

                    for item in items:
                        item.quotation = quotation
                        item.save()

                    for deleted in formset.deleted_objects:
                        deleted.delete()

                    quotation.recalc_totals(save=True)

                    # =====================================
                    # ACCEPTED
                    # =====================================

                    if (
                        old_status != "accepted"
                        and quotation.status == "accepted"
                    ):

                        quotation.accepted_by = request.user

                        quotation.accepted_at = timezone.now()

                        quotation.save(update_fields=[
                            "accepted_by",
                            "accepted_at",
                            "updated_at",
                        ])

                        # Existing client
                        if quotation.client:

                            order = quotation.convert_to_order(
                                user=request.user
                            )

                            messages.success(
                                request,
                                f"Quotation #{quotation.id} accepted and converted to Order #{order.id}."
                            )

                            return redirect(
                                "order-view",
                                pk=order.id
                            )

                        # Prospect
                        else:

                            messages.warning(
                                request,
                                "Quotation accepted. Convert the prospect into a client before creating an order."
                            )

                            return redirect(
                                "quotation-view",
                                pk=quotation.id
                            )

                messages.success(
                    request,
                    f"Quotation #{quotation.id} updated."
                )

                return redirect(
                    "quotation-view",
                    pk=quotation.id
                )

            except Exception as e:

                messages.error(
                    request,
                    f"Could not update quotation: {e}"
                )

                return redirect(
                    "quotation-edit",
                    pk=quotation.id
                )

        messages.error(
            request,
            "Please correct the errors below."
        )

    else:

        form = QuotationEditForm(
            instance=quotation
        )

        formset = QuotationItemFormSet(
            instance=quotation,
            prefix="items"
        )

    return render(
        request,
        "orders/quotation_edit.html",
        {
            "quotation": quotation,
            "form": form,
            "formset": formset,
            "prefix": "items",
        },
    )


def public_quotation_view(request, token):

    quotation = get_object_or_404(
        Quotation.objects.prefetch_related(
            "items",
            "items__product",
        ),
        public_token=token,
    )

    items = list(quotation.items.all())

    for item in items:

        unit_price_excl = (
            item.unit_price_excl
            or Decimal("0.00")
        )

        vat_percent = (
            item.vat_percent
            or Decimal("0.00")
        )

        line_total_excl = (
            item.line_total_excl
            or Decimal("0.00")
        )

        line_vat_amount = (
            item.line_vat_amount
            or Decimal("0.00")
        )

        item.display_unit_price_inc = (
            unit_price_excl
            + (
                unit_price_excl
                * vat_percent
                / Decimal("100")
            )
        )

        item.display_line_total_inc = (
            line_total_excl
            + line_vat_amount
        )

    return render(
        request,
        "orders/public_quotation.html",
        {
            "quotation": quotation,
            "items": items,
        },
    )

@login_required
@staff_required
def send_quotation_whatsapp_view(request, pk):

    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "error": "Invalid request method."
        }, status=405)

    quotation = get_object_or_404(
        Quotation.objects.select_related(
            "client",
            "prospect",
        ),
        pk=pk,
    )

    recipient = quotation.client or quotation.prospect

    if not recipient:
        return JsonResponse({
            "success": False,
            "error": "No client/prospect found."
        }, status=400)

    phone = (
        request.POST.get("phone")
        or getattr(recipient, "phone", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "error": "No WhatsApp number found."
        }, status=400)

    phone = (
        phone
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )

    client_name = (
        getattr(recipient, "organization", None)
        or getattr(recipient, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/orders/q/"
        f"{quotation.public_token}/"
    )

    result = send_quotation_whatsapp(
        to=phone,
        client_name=client_name,
        quotation_number=f"QT-{quotation.id}",
        amount=quotation.grand_total_inc,
        link=link,
        quotation=quotation,
    )

    # ==========================================
    # FAILED SEND
    # ==========================================
    if not result.get("messages"):

        error_message = (
            result.get("error", {})
            .get("message", "Unknown WhatsApp error")
        )

        CommunicationLog.objects.create(
            channel=CommunicationLog.CHANNEL_WHATSAPP,
            status=CommunicationLog.STATUS_FAILED,

            recipient_name=client_name,
            recipient_contact=phone,

            subject=f"Quotation QT-{quotation.id}",

            message=(
                f"Failed WhatsApp quotation send.\n"
                f"Quotation ID: {quotation.id}\n"
                f"Link: {link}"
            ),

            related_model="Quotation",
            related_object_id=quotation.id,

            provider="Meta WhatsApp Cloud API",
            provider_response=result,
            error_message=error_message,

            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "error": error_message,
            "result": result,
        }, status=400)

    # ==========================================
    # SUCCESSFUL SEND
    # ==========================================
    message_id = result["messages"][0].get("id")

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_WHATSAPP,
        status=CommunicationLog.STATUS_SENT,

        recipient_name=client_name,
        recipient_contact=phone,

        subject=f"Quotation QT-{quotation.id}",

        message=(
            f"Quotation sent via WhatsApp.\n"
            f"Quotation ID: {quotation.id}\n"
            f"Link: {link}"
        ),

        related_model="Quotation",
        related_object_id=quotation.id,

        provider="Meta WhatsApp Cloud API",
        provider_message_id=message_id,
        provider_response=result,

        sent_by=request.user,
        sent_at=timezone.now(),
    )

    quotation.status = "sent"

    quotation.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return JsonResponse({
        "success": True,
        "message": "Quotation sent successfully.",
        "whatsapp_message_id": message_id,
        "result": result,
    })


@require_POST
def public_accept_quotation_view(request, token):
    quotation = get_object_or_404(
        Quotation.objects.select_related("client", "prospect"),
        public_token=token,
    )

    if quotation.status in ["accepted", "rejected", "expired"]:
        return JsonResponse({
            "success": False,
            "error": f"Quotation already {quotation.status}."
        }, status=400)

    quotation.status = "accepted"
    quotation.accepted_at = timezone.now()
    quotation.public_decision_ip = request.META.get("REMOTE_ADDR")
    quotation.public_decision_user_agent = request.META.get("HTTP_USER_AGENT", "")

    quotation.save(update_fields=[
        "status",
        "accepted_at",
        "public_decision_ip",
        "public_decision_user_agent",
        "updated_at",
    ])

    order_id = None

    if quotation.client:
        order = quotation.convert_to_order(user=None)
        order_id = order.id

    return JsonResponse({
        "success": True,
        "message": "Quotation accepted successfully.",
        "order_id": order_id,
    })


@require_POST
def public_reject_quotation_view(request, token):
    quotation = get_object_or_404(
        Quotation.objects.select_related("client", "prospect"),
        public_token=token,
    )

    if quotation.status in ["accepted", "rejected", "expired"]:
        return JsonResponse({
            "success": False,
            "error": f"Quotation already {quotation.status}."
        }, status=400)

    reason = (request.POST.get("reason") or "").strip()

    quotation.status = "rejected"
    quotation.rejected_at = timezone.now()
    quotation.rejection_reason = reason
    quotation.public_decision_ip = request.META.get("REMOTE_ADDR")
    quotation.public_decision_user_agent = request.META.get("HTTP_USER_AGENT", "")

    quotation.save(update_fields=[
        "status",
        "rejected_at",
        "rejection_reason",
        "public_decision_ip",
        "public_decision_user_agent",
        "updated_at",
    ])

    return JsonResponse({
        "success": True,
        "message": "Quotation rejected successfully.",
    })






