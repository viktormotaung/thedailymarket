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
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import transaction
from datetime import timedelta
from django.utils import timezone
import django.forms as forms
from decimal import Decimal
import json
import hmac
from django.shortcuts import render, get_object_or_404
from .models import Quotation
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum, Count, F, Q, Value, DecimalField, IntegerField, ExpressionWrapper
)
from django.urls import reverse
from communications.services.whatsapp import send_quotation_whatsapp
from django.shortcuts import render
from communications.services.whatsapp import (
    send_quotation_whatsapp
)
from communications.services.smsportal import send_sms
from .models import Order, OrderItem, Quotation, QuotationItem
from clients.models import Client
from credit.models import CreditAccount
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


def get_client_trade_assist_account(client):
    """
    Return the single TradeAssist account linked to a client.

    CreditAccount.client is a OneToOneField, so there can only be one
    account per client. Accessing the reverse relation avoids arbitrary
    .first() selection and does not modify the account.
    """
    if not client:
        return None

    try:
        return client.credit_account
    except CreditAccount.DoesNotExist:
        return None


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
    """
    Display an order and its linked Trade Assist account position.

    This view is READ-ONLY:
    - It does not create an invoice.
    - It does not allocate or reserve buying power.
    - It does not change CreditAccount.credit_used.
    - The payment/allocation workflow remains responsible for verifying
      the upfront contribution and making an atomic TA allocation.
    """
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

    invoice_paid = bool(invoice and invoice.status == "paid")

    # ---------------------------------------------------------
    # Trade Assist account snapshot (read-only)
    # ---------------------------------------------------------
    credit_account = None
    credit_account_available = Decimal("0.00")
    credit_contribution_pct = Decimal("100.00")
    credit_can_allocate = False

    try:
        credit_account = (
            order.client.credit_account
        )
    except Exception:
        credit_account = None

    order_total = Decimal(str(order.grand_total_inc or "0.00"))

    if credit_account:
        credit_account_available = (
            credit_account.credit_available
            if hasattr(credit_account, "credit_available")
            else (
                Decimal(str(credit_account.credit_limit or "0.00"))
                - Decimal(str(credit_account.credit_used or "0.00"))
            )
        )
        credit_account_available = max(
            Decimal("0.00"),
            Decimal(str(credit_account_available))
        )

        try:
            credit_contribution_pct = Decimal(
                str(credit_account.credit_deposit_pct or "100.00")
            )
        except Exception:
            credit_contribution_pct = Decimal("100.00")

        # Eligibility shown here is informative only. The actual allocation
        # process must repeat these checks under transaction.atomic/select_for_update.
        credit_can_allocate = bool(
            credit_account.status == "ACTIVE"
            and getattr(credit_account, "can_allocate", False)
            and credit_account_available > Decimal("0.00")
        )

    # If an invoice already exists, display its saved financial snapshots.
    # Otherwise show an indicative split using the current account terms.
    if invoice:
        order_upfront_amount = Decimal(
            str(getattr(invoice, "deposit_required", "0.00") or "0.00")
        )
        order_deferred_amount = Decimal(
            str(getattr(invoice, "credit_used", "0.00") or "0.00")
        )
    elif credit_account and credit_account.status == "ACTIVE":
        order_upfront_amount = (
            order_total * credit_contribution_pct / Decimal("100.00")
        ).quantize(Decimal("0.01"))
        order_deferred_amount = (
            order_total - order_upfront_amount
        ).quantize(Decimal("0.01"))
    else:
        order_upfront_amount = order_total.quantize(Decimal("0.01"))
        order_deferred_amount = Decimal("0.00")

    items = order.items.all().order_by("id")
    item_rows = []

    for item in items:
        qty = item.quantity or Decimal("0.00")
        unit_excl = item.unit_price_excl or Decimal("0.00")
        discount_per_unit = item.discount_excl or Decimal("0.00")
        vat_pct = item.vat_percent or Decimal("0.00")

        net_unit_excl = max(
            Decimal("0.00"),
            unit_excl - discount_per_unit,
        )
        discount_total = discount_per_unit * qty
        line_excl = item.line_total_excl or Decimal("0.00")
        vat_amount = item.line_vat_amount or Decimal("0.00")
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
            "net_unit_excl": net_unit_excl,
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

            # Trade Assist display context
            "credit_account": credit_account,
            "credit_account_available": credit_account_available,
            "credit_contribution_pct": credit_contribution_pct,
            "credit_account_active": credit_account_active,
            "credit_payment_available": credit_payment_available,
            "credit_insufficient": credit_insufficient,
            "credit_upfront_amount": credit_upfront_amount,
            "credit_deferred_amount": credit_deferred_amount,
            "credit_can_allocate": credit_can_allocate,
            "order_upfront_amount": order_upfront_amount,
            "order_deferred_amount": order_deferred_amount,
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

            visibility = "⭐ " if product.visible == "NO" else ""

            text = (
                f"{visibility}"
                f"{product.sku} · {product.name} "
                f"({product.uom}) — "
                f"R{best_price_excl:.2f} excl · "
                f"R{best_price_incl:.2f} incl"
            )
        else:
            visibility = "⭐ " if product.visible == "NO" else ""

            text = (
                f"{visibility}"
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

    # ---------------------------------------------------------
    # TradeAssist account data for the selected client.
    # Read-only snapshot for the quotation screen only.
    # No buying power is reserved or changed here.
    # ---------------------------------------------------------
    trade_assist_accounts = {}

    # CreditAccount.client is a OneToOneField. This produces exactly one
    # account record per client and avoids arbitrary account selection.
    for account in (
        CreditAccount.objects
        .only(
            "id",
            "client_id",
            "status",
            "payment_term",
            "credit_deposit_pct",
            "credit_limit",
            "credit_used",
        )
    ):
        available = max(
            Decimal("0.00"),
            Decimal(str(account.credit_available or "0.00"))
        )

        trade_assist_accounts[str(account.client_id)] = {
            "status": account.status,
            "payment_term": account.payment_term or "",
            "contribution_pct": str(
                account.credit_deposit_pct
                if account.credit_deposit_pct is not None
                else Decimal("100.00")
            ),
            "available": str(available),
            "can_allocate": bool(
                account.status == "ACTIVE"
                and account.can_allocate
                and available > Decimal("0.00")
            ),
        }

    return render(
        request,
        "orders/quotation_create.html",
        {
            "form": form,
            "formset": formset,
            "prefix": "items",
            "trade_assist_accounts": trade_assist_accounts,
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

        net_unit_excl = max(
            Decimal("0.00"),
            unit_excl - discount_per_unit,
        )
        discount_total = discount_per_unit * qty
        line_excl = item.line_total_excl or Decimal("0.00")
        vat_amount = item.line_vat_amount or Decimal("0.00")
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
            "net_unit_excl": net_unit_excl,
            "discount_per_unit": discount_per_unit,
            "discount_total": discount_total,
            "discount_pct": discount_pct,
            "vat_pct": vat_pct,
            "line_excl": line_excl,
            "vat_amount": vat_amount,
            "line_inc": line_inc,
        })

    # Read-only Trade Assist snapshot. A quotation never reserves buying power.
    credit_account = get_client_trade_assist_account(quotation.client)
    credit_account_available = Decimal("0.00")
    credit_contribution_pct = Decimal("100.00")
    credit_account_active = False
    credit_payment_available = False
    credit_insufficient = False

    quotation_total = Decimal(str(
        quotation.grand_total_inc or "0.00"
    )).quantize(Decimal("0.01"))

    credit_upfront_amount = quotation_total
    credit_deferred_amount = Decimal("0.00")

    if credit_account:
        credit_account_available = max(
            Decimal("0.00"),
            Decimal(str(credit_account.credit_available or "0.00"))
        ).quantize(Decimal("0.01"))

        credit_contribution_pct = min(
            Decimal("100.00"),
            max(
                Decimal("0.00"),
                Decimal(str(
                    credit_account.credit_deposit_pct
                    if credit_account.credit_deposit_pct is not None
                    else "100.00"
                ))
            )
        )

        credit_account_active = (
            credit_account.status == "ACTIVE"
            and credit_account.can_allocate
        )

        if credit_account_active:
            indicative_upfront = (
                quotation_total * credit_contribution_pct / Decimal("100.00")
            ).quantize(Decimal("0.01"))
            indicative_deferred = (
                quotation_total - indicative_upfront
            ).quantize(Decimal("0.01"))

            if indicative_deferred <= credit_account_available:
                credit_upfront_amount = indicative_upfront
                credit_deferred_amount = indicative_deferred
                credit_payment_available = True
            else:
                credit_insufficient = True

    return render(
        request,
        "orders/quotation_view.html",
        {
            "quotation": quotation,
            "item_rows": item_rows,
            "credit_account": credit_account,
            "credit_account_available": credit_account_available,
            "credit_contribution_pct": credit_contribution_pct,
            "credit_account_active": credit_account_active,
            "credit_payment_available": credit_payment_available,
            "credit_insufficient": credit_insufficient,
            "credit_upfront_amount": credit_upfront_amount,
            "credit_deferred_amount": credit_deferred_amount,
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

                    # Accepting a quotation from the staff edit page also
                    # records the decision and converts it to an order once.
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

    # Recalculate in memory so the indicative estimate uses current item totals.
    quotation.recalc_totals(save=False)

    # ---------------------------------------------------------
    # TradeAssist facility snapshot (read-only)
    # ---------------------------------------------------------
    trade_assist_account = get_client_trade_assist_account(quotation.client)
    trade_assist_available = Decimal("0.00")
    trade_assist_contribution_pct = Decimal("100.00")
    trade_assist_account_active = False
    trade_assist_payment_available = False
    trade_assist_insufficient = False

    quotation_total = Decimal(str(
        quotation.grand_total_inc or "0.00"
    )).quantize(Decimal("0.01"))
    trade_assist_upfront_amount = quotation_total
    trade_assist_deferred_amount = Decimal("0.00")

    if trade_assist_account:
        trade_assist_available = max(
            Decimal("0.00"),
            Decimal(str(trade_assist_account.credit_available or "0.00"))
        ).quantize(Decimal("0.01"))

        trade_assist_contribution_pct = min(
            Decimal("100.00"),
            max(
                Decimal("0.00"),
                Decimal(str(
                    trade_assist_account.credit_deposit_pct
                    if trade_assist_account.credit_deposit_pct is not None
                    else "100.00"
                ))
            )
        )

        trade_assist_account_active = (
            trade_assist_account.status == "ACTIVE"
            and trade_assist_account.can_allocate
        )

        if trade_assist_account_active:
            indicative_upfront = (
                quotation_total
                * trade_assist_contribution_pct
                / Decimal("100.00")
            ).quantize(Decimal("0.01"))
            indicative_deferred = (
                quotation_total - indicative_upfront
            ).quantize(Decimal("0.01"))

            if indicative_deferred <= trade_assist_available:
                trade_assist_upfront_amount = indicative_upfront
                trade_assist_deferred_amount = indicative_deferred
                trade_assist_payment_available = True
            else:
                trade_assist_insufficient = True

    return render(
        request,
        "orders/quotation_edit.html",
        {
            "quotation": quotation,
            "form": form,
            "formset": formset,
            "prefix": "items",
            "trade_assist_account": trade_assist_account,
            "trade_assist_available": trade_assist_available,
            "trade_assist_contribution_pct": trade_assist_contribution_pct,
            "trade_assist_account_active": trade_assist_account_active,
            "trade_assist_payment_available": trade_assist_payment_available,
            "trade_assist_insufficient": trade_assist_insufficient,
            "trade_assist_upfront_amount": trade_assist_upfront_amount,
            "trade_assist_deferred_amount": trade_assist_deferred_amount,
        },
    )


def public_quotation_view(request, token):
    """
    Public, read-only quotation page.

    TradeAssist information is displayed as an indicative payment breakdown
    only. Viewing a quotation never reserves buying power, changes credit_used,
    creates an invoice, or allocates a facility.
    """
    quotation = get_object_or_404(
        Quotation.objects.select_related("client", "prospect").prefetch_related(
            "items",
            "items__product",
        ),
        public_token=token,
    )

    # Recalculate totals in memory so the public breakdown uses the current
    # quotation item values without persisting any changes.
    quotation.recalc_totals(save=False)

    items = list(quotation.items.all())

    for item in items:
        unit_price_excl = item.unit_price_excl or Decimal("0.00")
        discount_excl = item.discount_excl or Decimal("0.00")
        vat_percent = item.vat_percent or Decimal("0.00")
        line_total_excl = item.line_total_excl or Decimal("0.00")
        line_vat_amount = item.line_vat_amount or Decimal("0.00")

        discounted_unit_excl = max(
            Decimal("0.00"),
            unit_price_excl - discount_excl,
        )

        item.display_unit_price_inc = (
            discounted_unit_excl
            + (
                discounted_unit_excl
                * vat_percent
                / Decimal("100.00")
            )
        ).quantize(Decimal("0.01"))

        item.display_line_total_inc = line_total_excl + line_vat_amount

    # ---------------------------------------------------------
    # TradeAssist account snapshot (READ-ONLY / INDICATIVE)
    # ---------------------------------------------------------
    trade_assist_account = None
    trade_assist_available = Decimal("0.00")
    trade_assist_contribution_pct = Decimal("100.00")
    trade_assist_upfront_amount = Decimal(str(
        quotation.grand_total_inc or "0.00"
    )).quantize(Decimal("0.01"))
    trade_assist_deferred_amount = Decimal("0.00")
    trade_assist_payment_available = False
    trade_assist_account_active = False
    trade_assist_insufficient = False
    trade_assist_payment_term = ""

    quotation_total = Decimal(str(
        quotation.grand_total_inc or "0.00"
    )).quantize(Decimal("0.01"))

    # A prospect or quotation without a linked client cannot have an
    # account-specific TradeAssist split displayed.
    if quotation.client_id:
        trade_assist_account = get_client_trade_assist_account(quotation.client)

    if trade_assist_account:
        if hasattr(trade_assist_account, "get_payment_term_display"):
            trade_assist_payment_term = (
                trade_assist_account.get_payment_term_display()
            )
        else:
            trade_assist_payment_term = (
                getattr(trade_assist_account, "payment_term", "") or ""
            )

        available = getattr(trade_assist_account, "credit_available", None)

        if available is None:
            available = (
                (getattr(trade_assist_account, "credit_limit", None) or Decimal("0.00"))
                - (getattr(trade_assist_account, "credit_used", None) or Decimal("0.00"))
            )

        trade_assist_available = max(
            Decimal("0.00"),
            Decimal(str(available or "0.00")),
        ).quantize(Decimal("0.01"))

        try:
            trade_assist_contribution_pct = Decimal(str(
                getattr(
                    trade_assist_account,
                    "credit_deposit_pct",
                    Decimal("100.00"),
                ) or Decimal("100.00")
            ))
        except (TypeError, ValueError, ArithmeticError):
            trade_assist_contribution_pct = Decimal("100.00")

        # Guard against invalid account configuration.
        trade_assist_contribution_pct = min(
            Decimal("100.00"),
            max(Decimal("0.00"), trade_assist_contribution_pct),
        )

        trade_assist_account_active = (
            getattr(trade_assist_account, "status", "") == "ACTIVE"
            and bool(getattr(trade_assist_account, "can_allocate", False))
        )

        if trade_assist_account_active:
            indicative_upfront = (
                quotation_total
                * trade_assist_contribution_pct
                / Decimal("100.00")
            ).quantize(Decimal("0.01"))

            indicative_deferred = (
                quotation_total - indicative_upfront
            ).quantize(Decimal("0.01"))

            # Display the split only if the account has enough available
            # buying power for the deferred portion. This is not a reservation.
            if (
                indicative_deferred > Decimal("0.00")
                and indicative_deferred <= trade_assist_available
            ):
                trade_assist_upfront_amount = indicative_upfront
                trade_assist_deferred_amount = indicative_deferred
                trade_assist_payment_available = True
            elif indicative_deferred == Decimal("0.00"):
                trade_assist_upfront_amount = quotation_total
                trade_assist_deferred_amount = Decimal("0.00")
                trade_assist_payment_available = True
            else:
                trade_assist_insufficient = True

    return render(
        request,
        "orders/public_quotation.html",
        {
            "quotation": quotation,
            "items": items,
            "trade_assist_account": trade_assist_account,
            "trade_assist_available": trade_assist_available,
            "trade_assist_contribution_pct": trade_assist_contribution_pct,
            "trade_assist_upfront_amount": trade_assist_upfront_amount,
            "trade_assist_deferred_amount": trade_assist_deferred_amount,
            "trade_assist_payment_available": trade_assist_payment_available,
            "trade_assist_account_active": trade_assist_account_active,
            "trade_assist_insufficient": trade_assist_insufficient,
            "trade_assist_payment_term": trade_assist_payment_term,
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


@login_required
@staff_required
@require_POST
def send_quotation_sms(request, pk):

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
            "error": "No mobile number found."
        }, status=400)

    client_name = (
        getattr(recipient, "organization", None)
        or getattr(recipient, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/orders/q/"
        f"{quotation.public_token}/"
    )

    message = (
        f"Hi {client_name}, your The Daily Market quotation "
        f"QT-{quotation.id} is ready. "
        f"Total R{quotation.grand_total_inc:.2f}. "
        f"View/accept: {link}"
    )

    result = send_sms(
        to=phone,
        message=message,
    )

    if not result.get("success"):

        CommunicationLog.objects.create(
            channel=CommunicationLog.CHANNEL_SMS,
            status=CommunicationLog.STATUS_FAILED,
            recipient_name=client_name,
            recipient_contact=phone,
            subject=f"Quotation QT-{quotation.id}",
            message=message,
            related_model="Quotation",
            related_object_id=quotation.id,
            provider="SMSPortal",
            provider_response=result,
            error_message=str(result.get("response")),
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "error": "SMS failed to send.",
            "result": result,
        }, status=400)

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_SMS,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Quotation QT-{quotation.id}",
        message=message,
        related_model="Quotation",
        related_object_id=quotation.id,
        provider="SMSPortal",
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "SMS sent successfully.",
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



@login_required
@staff_required
def send_quotation_email_internal(request, pk):

    quotation = get_object_or_404(
        Quotation.objects
        .select_related(
            "client",
            "prospect",
        )
        .prefetch_related(
            "items",
            "items__product",
            "items__category",
        ),
        pk=pk,
    )

    if request.method != "POST":
        return JsonResponse(
            {"success": False, "error": "Invalid request method."},
            status=400
        )

    try:
        data = json.loads(request.body)

    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": "Invalid JSON."},
            status=400
        )

    email_to = (data.get("email") or "").strip()
    recipient_name = (data.get("recipient_name") or "").strip()

    if not email_to:
        return JsonResponse(
            {"success": False, "error": "No email provided."},
            status=400
        )

    recipient = quotation.client or quotation.prospect

    if not recipient:
        return JsonResponse(
            {"success": False, "error": "No client/prospect found."},
            status=400
        )

    if not recipient_name:
        recipient_name = (
            getattr(recipient, "organization", None)
            or getattr(recipient, "name", None)
            or "Valued Customer"
        )

    items = list(quotation.items.all())

    for item in items:
        unit_price_excl = item.unit_price_excl or Decimal("0.00")
        discount_excl = item.discount_excl or Decimal("0.00")
        vat_percent = item.vat_percent or Decimal("0.00")
        line_total_excl = item.line_total_excl or Decimal("0.00")
        line_vat_amount = item.line_vat_amount or Decimal("0.00")

        discounted_unit_excl = max(
            Decimal("0.00"),
            unit_price_excl - discount_excl,
        )

        item.display_unit_price_inc = (
            discounted_unit_excl
            + (
                discounted_unit_excl
                * vat_percent
                / Decimal("100")
            )
        ).quantize(Decimal("0.01"))

        item.display_line_total_inc = (
            line_total_excl
            + line_vat_amount
        )

    ctx = {
        "quotation": quotation,
        "recipient": recipient,
        "items": items,
        "recipient_name": recipient_name,
        "support_email": getattr(
            settings,
            "SUPPORT_EMAIL",
            "support@thedailymarket.co.za"
        ),
        "quotation_url": request.build_absolute_uri(
            reverse(
                "public-quotation-view",
                args=[quotation.public_token]
            )
        ),
    }

    text_body = render_to_string(
        "email/quotation_email.txt",
        ctx
    )

    html_body = render_to_string(
        "email/quotation_email.html",
        ctx
    )

    subject = f"The Daily Market – Quotation QT-{quotation.id}"

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(
            settings,
            "DEFAULT_FROM_EMAIL",
            "accounts@thedailymarket.co.za"
        ),
        to=[email_to],
        headers={
            "Reply-To": getattr(
                settings,
                "SUPPORT_EMAIL",
                "support@thedailymarket.co.za"
            )
        },
    )

    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=recipient_name,
        recipient_contact=email_to,
        subject=subject,
        message=f"Quotation sent via email. Quotation ID: {quotation.id}",
        related_model="Quotation",
        related_object_id=quotation.id,
        provider="Django Email",
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({"success": True})


@login_required
@staff_required
def staff_sales_dashboard(request):
    return render(request, "orders/staff_sales_dashboard.html")


