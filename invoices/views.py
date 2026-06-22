from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.timezone import now, localdate
from django.http import JsonResponse
from invoices.models import Invoice
from credit.models import CreditEntry  # 👈 for credit repayments
import json
import hashlib
import urllib.parse
from django.core.mail import EmailMultiAlternatives
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from django.utils.timezone import now, make_aware
from datetime import datetime, timedelta, time, date
from clients.models import Client
import logging
import uuid
from online_payments.models import Payment
from communications.models import CommunicationLog
from communications.services.whatsapp import send_invoice_whatsapp
from django.utils import timezone
from communications.services.whatsapp import (
    send_invoice_whatsapp,
    send_invoice_payment_request_whatsapp,
)
from communications.services.smsportal import send_sms
from django.template.loader import render_to_string
from decimal import Decimal
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.template.loader import get_template
from xhtml2pdf import pisa


logger = logging.getLogger(__name__)

DAY_OPTIONS = [7, 14, 30, 60]


def staff_check(user):
    return user.is_authenticated and user.is_staff


staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")

def resolve_client_for_user(user, request=None):
    """
    Canonical path for your setup:
    User -> user.customer_profile -> effective_client (business Client or None).
    Staff can optionally preview another client via ?client_id=...
    """
    # Optional staff preview: /wholesale_assist/?client_id=123
    if request and (user.is_staff or user.is_superuser):
        cid = request.GET.get("client_id")
        if cid:
            return Client.objects.filter(pk=cid).first()

    prof = getattr(user, "customer_profile", None)
    if prof:
        return prof.effective_client  # returns client if BUSINESS, else None

    return None

@login_required
@staff_required
def invoice_list(request):

    # --- days param (validated) ---
    raw = request.GET.get("days", "7")
    try:
        days = int(raw)
    except ValueError:
        days = 7

    if days not in DAY_OPTIONS:
        days = 7

    # --- filters ---
    search = request.GET.get("q", "").strip()
    filter_status = request.GET.get("status", "").strip()
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")

    # --- base date range ---
    end_date = localdate()
    start_date = end_date - timedelta(days=days)

    if date_from:
        try:
            start_date = date.fromisoformat(date_from)
        except ValueError:
            pass

    if date_to:
        try:
            end_date = date.fromisoformat(date_to)
        except ValueError:
            pass

    # --------------------------------------------------
    # BASE QUERYSET
    # --------------------------------------------------

    invoices_qs = (
        Invoice.objects
        .select_related("client", "order")
        .filter(invoice_date__gte=start_date, invoice_date__lte=end_date)
        .annotate(
            balance=ExpressionWrapper(
                F("amount_due") - F("deposit_paid"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )

    # --------------------------------------------------
    # SEARCH FILTER
    # --------------------------------------------------

    if search:
        invoices_qs = invoices_qs.filter(
            Q(client__name__icontains=search) |
            Q(client__client_number__icontains=search) |
            Q(order__id__icontains=search)
        )

    # --------------------------------------------------
    # STATUS FILTER
    # --------------------------------------------------

    if filter_status:
        invoices_qs = invoices_qs.filter(status=filter_status)

    # --------------------------------------------------
    # KPI CALCULATIONS
    # --------------------------------------------------

    recent_unpaid_qs = invoices_qs.exclude(status="paid")

    recent_unpaid_total = recent_unpaid_qs.aggregate(
        total_unpaid=Coalesce(Sum("balance"), Decimal("0.00"))
    )["total_unpaid"]

    # FIX: use full invoice value instead of deposit
    recent_paid_total = invoices_qs.filter(status="paid").aggregate(
        total_paid=Coalesce(Sum("order_total_inc"), Decimal("0.00"))
    )["total_paid"]

    recent_paid_count = invoices_qs.filter(status="paid").count()

    # --------------------------------------------------
    # CONTEXT
    # --------------------------------------------------

    context = {
        "DAY_OPTIONS": DAY_OPTIONS,
        "days": days,

        "recent_paid_start": start_date,
        "recent_unpaid_start": start_date,

        "recent_unpaid_total": recent_unpaid_total,
        "recent_unpaid_count": recent_unpaid_qs.count(),

        "recent_paid_total": recent_paid_total,
        "recent_paid_count": recent_paid_count,

        "invoices": invoices_qs.order_by("-created_at"),

        "search": search,
        "filter_status": filter_status,
        "date_from": start_date,
        "date_to": end_date,

        "status_choices": Invoice.STATUS_CHOICES,
    }

    return render(request, "invoices/invoice_list.html", context)


@login_required
@staff_required
def invoice_view(request, pk):
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
    items = list(order.items.all())

    for item in items:
        item.display_line_total_inc = (
            (item.line_total_excl or Decimal("0.00"))
            + (item.line_vat_amount or Decimal("0.00"))
        )

    today = localdate()
    is_overdue = (
        invoice.status != "paid"
        and invoice.due_date is not None
        and invoice.due_date < today
    )

    # deposit balance
    deposit_outstanding = max(invoice.amount_due - (invoice.deposit_paid or 0), 0)

    # CREDIT BALANCE
    from credit.models import CreditEntry
    from django.db.models import Sum

    credit_repaid = (
        CreditEntry.objects.filter(
            invoice=invoice,
            kind=CreditEntry.REPAYMENT,
            credit_account__client=client,
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    credit_outstanding = (invoice.credit_used or Decimal("0.00")) - credit_repaid

    return render(
        request,
        "invoices/invoice_view.html",
        {
            "invoice": invoice,
            "order": order,
            "client": client,
            "items": items,
            "is_overdue": is_overdue,
            "deposit_outstanding": deposit_outstanding,
            "credit_outstanding": credit_outstanding,
            "merchant_id": client.id,          # use client ID as merchant ID
            "merchant_name": client.name,      # use client name as merchant name
        },
    )


@login_required
@staff_required
@require_POST
def invoice_confirm_payment(request, pk):

    print("========== PAYMENT START ==========")

    invoice = get_object_or_404(Invoice, pk=pk)

    print(f"Invoice ID: {invoice.id}")
    print(f"Current deposit_paid: {invoice.deposit_paid}")
    print(f"Deposit required: {invoice.deposit_required}")
    print(f"Current status: {invoice.status}")

    kind = (request.POST.get("kind") or "deposit").lower()
    raw_amount = (request.POST.get("amount") or "").replace(",", "").strip()
    reference = request.POST.get("reference") or f"INV-{invoice.id}: {kind}"

    print(f"Payment kind: {kind}")
    print(f"Raw amount: {raw_amount}")

    # --------------------------------------------------
    # Validate amount
    # --------------------------------------------------
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, TypeError) as e:
        print("❌ Invalid amount:", e)
        messages.error(request, "Invalid amount entered.")
        return redirect("invoice-view", pk=invoice.pk)

    if amount <= 0:
        print("❌ Amount <= 0")
        messages.error(request, "Amount must be greater than zero.")
        return redirect("invoice-view", pk=invoice.pk)

    note = f"Manual {kind} payment captured on invoice screen."

    # ==================================================
    # CREDIT REPAYMENT
    # ==================================================
    if kind == "credit":
        try:
            result = invoice.record_credit_repayment(
                amount=amount,
                reference=reference,
                note=note,
            )
            print("Credit repayment result:", result)

        except Exception as e:
            print("❌ Payment error:", e)
            logger.exception("Payment failed")

            # Try to reload invoice safely
            try:
                invoice.refresh_from_db()
                messages.error(request, f"Payment failed: {str(e)}")
                return redirect("invoice-view", pk=invoice.pk)
            except Invoice.DoesNotExist:
                # Invoice was deleted (credit blocked scenario)
                order = invoice.order  # safe because already loaded
                messages.error(
                    request,
                    "Insufficient credit. Invoice deleted and order blocked."
                )
                return redirect("order-view", pk=order.pk)

        print("========== PAYMENT END ==========")
        messages.success(
            request,
            f"Credit repayment of R{amount:.2f} recorded."
        )
        return redirect("invoice-view", pk=invoice.pk)

    # ==================================================
    # DEPOSIT PAYMENT
    # ==================================================
    try:
        


        provider = (request.POST.get("provider") or "").strip()

        if provider not in ["eft", "cash_deposit"]:
            messages.error(request, "Please select a valid payment provider.")
            return redirect("invoice-view", pk=invoice.pk)

        result = invoice.record_payment(
            amount=amount,
            reference=reference,
            note=note,
        )

        payment_reference = reference

        if Payment.objects.filter(reference=payment_reference).exists():
            payment_reference = f"{reference}-PAY-{uuid.uuid4().hex[:6]}"

        payment = Payment.objects.create(
            reference=payment_reference,
            amount=amount,
            client=invoice.client,
            invoice=invoice,
            created_by=request.user if request.user.is_authenticated else None,
            provider=provider,
            status="pending",
        )

        Payment.objects.filter(pk=payment.pk).update(
            status="success",
            paid_at=now(),
        )

        print("record_payment() returned:", result)

        # Reload invoice from DB to check new values
        invoice.refresh_from_db()

        print("After payment:")
        print("Deposit paid:", invoice.deposit_paid)
        print("Status:", invoice.status)
        print("Paid date:", invoice.paid_date)

    except Exception as e:
        print("❌ Payment error:", e)
        logger.exception("Payment failed")
        messages.error(request, f"Payment failed: {str(e)}")
        return redirect("invoice-view", pk=invoice.pk)

    # --------------------------------------------------
    # CREDIT BLOCKED
    # --------------------------------------------------
    if result is False:
        print("⚠ Credit blocked scenario")

        order = invoice.order
        order.status = "credit_blocked"
        order.save(update_fields=["status"])

        messages.error(
            request,
            "Insufficient credit balance. Order blocked."
        )

        print("========== PAYMENT END ==========")
        return redirect("order-detail", pk=order.pk)

    # --------------------------------------------------
    # SUCCESS
    # --------------------------------------------------
    print("✅ Payment successful")
    print("========== PAYMENT END ==========")

    messages.success(request, "Payment recorded successfully.")
    return redirect("invoice-view", pk=invoice.pk)



@login_required
def generate_payfast_request(request, invoice_id):
    invoice = get_object_or_404(
        Invoice.objects.select_related("order", "order__client"),
        pk=invoice_id
    )

    data = [
        ("merchant_id", settings.PAYFAST_MERCHANT_ID),
        ("merchant_key", settings.PAYFAST_MERCHANT_KEY),
        ("return_url", "https://yourdomain.co.za/payfast/return/"),
        ("cancel_url", "https://yourdomain.co.za/payfast/cancel/"),
        ("notify_url", "https://yourdomain.co.za/payfast/itn/"),

        ("name_first", invoice.order.client.contact_person.split()[0]),
        ("name_last", invoice.order.client.contact_person.split()[-1]),
        ("email_address", invoice.order.client.email),

        ("m_payment_id", f"INV-{invoice.id}"),
        ("amount", f"{invoice.amount_due:.2f}"),
        ("item_name", f"Invoice #{invoice.id}"),
    ]

    signature = generate_payfast_signature(
        data=data,
        passphrase=settings.PAYFAST_PASSPHRASE
    )

    payfast_data = dict(data)
    payfast_data["signature"] = signature

    # Build the full PayFast URL
    from urllib.parse import urlencode
    payfast_link = f"{settings.PAYFAST_PROCESS_URL}?{urlencode(payfast_data)}"

    return JsonResponse({"payment_url": payfast_link})



def generate_payfast_signature(data, passphrase):
    parts = []

    for key, value in data:
        if value != "":
            parts.append(f"{key}={urllib.parse.quote_plus(str(value))}")

    param_string = "&".join(parts)

    if passphrase:
        param_string += "&passphrase=" + urllib.parse.quote_plus(passphrase)

    print("\nPAYFAST PARAM STRING (FINAL):")
    print(param_string)

    signature = hashlib.md5(param_string.encode("utf-8")).hexdigest()

    print("PAYFAST SIGNATURE:")
    print(signature)

    return signature



@login_required
@staff_required
@require_POST
def send_invoice_payment_request(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "order"),
        pk=pk,
    )

    client = invoice.client

    if invoice.status == "paid":
        return JsonResponse({
            "success": False,
            "message": "Invoice is already paid.",
        }, status=400)

    phone = (
        request.POST.get("phone")
        or getattr(client, "whatsapp", "")
        or getattr(client, "phone", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "message": "Client has no WhatsApp number.",
        }, status=400)

    phone = (
        phone
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )

    client_name = (
        getattr(client, "organization", None)
        or getattr(client, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/invoices/public/"
        f"{invoice.public_token}/"
    )

    result = send_invoice_payment_request_whatsapp(
        to=phone,
        client_name=client_name,
        invoice_number=f"INV-{invoice.id}",
        amount=invoice.amount_due,
        link=link,
        invoice=invoice,
    )

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
            subject=f"Payment Request INV-{invoice.id}",
            message=f"Failed payment request for Invoice {invoice.id}. Link: {link}",
            related_model="Invoice",
            related_object_id=invoice.id,
            provider="Meta WhatsApp Cloud API",
            provider_response=result,
            error_message=error_message,
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "message": error_message,
            "result": result,
        }, status=400)

    message_id = result["messages"][0].get("id")

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_WHATSAPP,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Payment Request INV-{invoice.id}",
        message=f"Payment request sent for Invoice {invoice.id}. Link: {link}",
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="Meta WhatsApp Cloud API",
        provider_message_id=message_id,
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Payment request sent via WhatsApp.",
        "whatsapp_message_id": message_id,
    })

@login_required
@staff_required
def invoice_create(request):
    return render(request, "invoices/invoice_create.html")


@login_required
@staff_required
def invoice_edit(request, pk):
    return render(request, "invoices/invoice_edit.html")


@login_required
@staff_required
def invoice_download(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "client",
            "order",
            "order__client",
        ).prefetch_related(
            "order__items",
            "order__items__product",
        ),
        pk=pk,
    )

    items = list(invoice.order.items.all())

    for item in items:
        unit_price_excl = item.unit_price_excl or Decimal("0.00")
        vat_percent = item.vat_percent or Decimal("0.00")
        line_total_excl = item.line_total_excl or Decimal("0.00")
        line_vat_amount = item.line_vat_amount or Decimal("0.00")

        item.display_unit_price_inc = (
            unit_price_excl
            + (unit_price_excl * vat_percent / Decimal("100"))
        )

        item.display_line_total_inc = (
            line_total_excl
            + line_vat_amount
        )

    return render(
        request,
        "invoices/invoice_pdf.html",
        {
            "invoice": invoice,
            "order": invoice.order,
            "client": invoice.client,
            "items": items,
        },
    )

# ============= NEW: payment actions from the modal =============

@login_required
@staff_required
def invoice_send_payment_request(request, pk):
    """
    'Send Request Payment' from the modal.
    For now, just sets a message – you can later plug in WhatsApp / email logic.
    """
    invoice = get_object_or_404(Invoice, pk=pk)
    kind = (request.GET.get("kind") or "deposit").lower()

    if kind == "credit":
        label = "credit repayment"
    else:
        label = "deposit"

    # TODO: integrate with your actual "send payment link" logic.
    messages.success(
        request,
        f"Payment request for {label} on Invoice #{invoice.id} has been queued (placeholder).",
    )
    return redirect("invoice-view", pk=pk)




@login_required
@staff_required
def send_invoice_email_internal(request, pk):

    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "client",
            "order",
        ).prefetch_related(
            "order__items",
            "order__items__product",
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

    client = invoice.client

    # --------------------------------------------------
    # Prepare invoice items for email display
    # --------------------------------------------------

    items = list(invoice.order.items.all())

    for item in items:
        unit_price_excl = item.unit_price_excl or Decimal("0.00")
        vat_percent = item.vat_percent or Decimal("0.00")
        line_total_excl = item.line_total_excl or Decimal("0.00")
        line_vat_amount = item.line_vat_amount or Decimal("0.00")

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

    # --------------------------------------------------
    # Resolve recipient name safely
    # --------------------------------------------------

    if not recipient_name:
        profile = client.customer_profiles.select_related("user").first()

        if profile and profile.user:
            recipient_name = (
                profile.user.get_full_name()
                or profile.user.username
            )
        else:
            recipient_name = client.name or "Valued Customer"

    # --------------------------------------------------
    # Build context
    # --------------------------------------------------

    ctx = {
        "invoice": invoice,
        "client": client,
        "items": items,
        "recipient_name": recipient_name,
        "support_email": getattr(
            settings,
            "SUPPORT_EMAIL",
            "support@thedailymarket.co.za"
        ),
        "invoice_url": request.build_absolute_uri(
            reverse(
                "public-invoice-view",
                args=[invoice.public_token]
            )
        ),
    }

    # --------------------------------------------------
    # Render templates
    # --------------------------------------------------

    text_body = render_to_string(
        "email/invoice_email.txt",
        ctx
    )

    html_body = render_to_string(
        "email/invoice_email.html",
        ctx
    )

    # --------------------------------------------------
    # Send email
    # --------------------------------------------------

    subject = f"The Daily Market – Invoice INV-{invoice.id}"

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

    return JsonResponse({"success": True})

@login_required
@staff_required
@require_POST
def send_invoice_whatsapp_view(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "order"),
        pk=pk,
    )

    client = invoice.client

    phone = (
        request.POST.get("phone")
        or getattr(client, "whatsapp", "")
        or getattr(client, "phone", "")
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
        getattr(client, "organization", None)
        or getattr(client, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/invoices/public/"
        f"{invoice.public_token}/"
    )

    result = send_invoice_whatsapp(
        to=phone,
        client_name=client_name,
        invoice_number=f"INV-{invoice.id}",
        amount=invoice.amount_due,
        link=link,
        invoice=invoice,
    )

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
            subject=f"Invoice INV-{invoice.id}",
            message=(
                f"Failed WhatsApp invoice send.\n"
                f"Invoice ID: {invoice.id}\n"
                f"Link: {link}"
            ),
            related_model="Invoice",
            related_object_id=invoice.id,
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

    message_id = result["messages"][0].get("id")

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_WHATSAPP,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Invoice INV-{invoice.id}",
        message=(
            f"Invoice sent via WhatsApp.\n"
            f"Invoice ID: {invoice.id}\n"
            f"Link: {link}"
        ),
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="Meta WhatsApp Cloud API",
        provider_message_id=message_id,
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Invoice sent successfully.",
        "whatsapp_message_id": message_id,
        "result": result,
    })


def public_invoice_view(request, token):

    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "client",
            "order",
            "order__client",
        ).prefetch_related(
            "order__items",
            "order__items__product",
        ),
        public_token=token,
    )

    items = list(invoice.order.items.all())

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
        "invoices/public_invoice.html",
        {
            "invoice": invoice,
            "order": invoice.order,
            "client": invoice.client,
            "items": items,
        },
    )

@login_required
@staff_required
@require_POST
def invoice_send_payment_request(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "order"),
        pk=pk,
    )

    client = invoice.client

    if invoice.status == "paid":
        return JsonResponse({
            "success": False,
            "message": "Invoice is already paid.",
        }, status=400)

    phone = (
        getattr(client, "whatsapp", "")
        or getattr(client, "phone", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "message": "Client has no WhatsApp number.",
        }, status=400)

    phone = (
        phone
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )

    client_name = (
        getattr(client, "organization", None)
        or getattr(client, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/invoices/public/"
        f"{invoice.public_token}/"
    )

    result = send_invoice_payment_request_whatsapp(
        to=phone,
        client_name=client_name,
        invoice_number=f"INV-{invoice.id}",
        amount=invoice.amount_due,
        link=link,
        invoice=invoice,
    )

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
            subject=f"Payment Request INV-{invoice.id}",
            message=f"Failed payment request for Invoice {invoice.id}. Link: {link}",
            related_model="Invoice",
            related_object_id=invoice.id,
            provider="Meta WhatsApp Cloud API",
            provider_response=result,
            error_message=error_message,
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "message": error_message,
            "result": result,
        }, status=400)

    message_id = result["messages"][0].get("id")

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_WHATSAPP,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Payment Request INV-{invoice.id}",
        message=f"Payment request sent for Invoice {invoice.id}. Link: {link}",
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="Meta WhatsApp Cloud API",
        provider_message_id=message_id,
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Payment request sent via WhatsApp.",
        "whatsapp_message_id": message_id,
    })


@login_required
@staff_required
@require_POST
def send_invoice_sms_view(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "order"),
        pk=pk,
    )

    client = invoice.client

    phone = (
        request.POST.get("phone")
        or getattr(client, "phone", "")
        or getattr(client, "whatsapp", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "error": "No mobile number found."
        }, status=400)

    client_name = (
        getattr(client, "organization", None)
        or getattr(client, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/invoices/public/"
        f"{invoice.public_token}/"
    )

    message = (
        f"Hi {client_name}, your The Daily Market invoice "
        f"INV-{invoice.id} is ready. "
        f"Amount due R{invoice.amount_due:.2f}. "
        f"View/pay: {link}"
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
            subject=f"Invoice INV-{invoice.id}",
            message=message,
            related_model="Invoice",
            related_object_id=invoice.id,
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
        subject=f"Invoice INV-{invoice.id}",
        message=message,
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="SMSPortal",
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Invoice sent successfully via SMS.",
        "result": result,
    })


@login_required
@staff_required
@require_POST
def send_invoice_payment_request_sms(request, pk):

    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "order"),
        pk=pk,
    )

    client = invoice.client

    if invoice.status == "paid":
        return JsonResponse({
            "success": False,
            "error": "Invoice is already paid.",
        }, status=400)

    phone = (
        request.POST.get("phone")
        or getattr(client, "phone", "")
        or getattr(client, "whatsapp", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "error": "No mobile number found.",
        }, status=400)

    client_name = (
        getattr(client, "organization", None)
        or getattr(client, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/invoices/public/"
        f"{invoice.public_token}/"
    )

    message = (
        f"Hi {client_name}, payment request for The Daily Market "
        f"INV-{invoice.id}. Amount due R{invoice.amount_due:.2f}. "
        f"Pay/view: {link}"
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
            subject=f"Payment Request INV-{invoice.id}",
            message=message,
            related_model="Invoice",
            related_object_id=invoice.id,
            provider="SMSPortal",
            provider_response=result,
            error_message=str(result.get("response")),
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "error": "Payment request SMS failed to send.",
            "result": result,
        }, status=400)

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_SMS,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Payment Request INV-{invoice.id}",
        message=message,
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="SMSPortal",
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Payment request sent via SMS.",
        "result": result,
    })

@login_required
@staff_required
@require_POST
def send_invoice_payment_request_email(request, pk):

    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "client",
            "order",
        ).prefetch_related(
            "order__items",
            "order__items__product",
        ),
        pk=pk,
    )

    client = invoice.client

    if invoice.status == "paid":
        return JsonResponse({
            "success": False,
            "error": "Invoice is already paid.",
        }, status=400)

    try:
        data = json.loads(request.body)

    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON.",
        }, status=400)

    email_to = (data.get("email") or "").strip()
    recipient_name = (data.get("recipient_name") or "").strip()

    if not email_to:
        return JsonResponse({
            "success": False,
            "error": "No email provided.",
        }, status=400)

    if not recipient_name:
        recipient_name = (
            getattr(client, "organization", None)
            or getattr(client, "name", None)
            or "Valued Customer"
        )

    items = list(invoice.order.items.all())

    for item in items:
        unit_price_excl = item.unit_price_excl or Decimal("0.00")
        vat_percent = item.vat_percent or Decimal("0.00")
        line_total_excl = item.line_total_excl or Decimal("0.00")
        line_vat_amount = item.line_vat_amount or Decimal("0.00")

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

    link = request.build_absolute_uri(
        reverse(
            "public-invoice-view",
            args=[invoice.public_token],
        )
    )

    ctx = {
        "invoice": invoice,
        "client": client,
        "items": items,
        "recipient_name": recipient_name,
        "support_email": getattr(
            settings,
            "SUPPORT_EMAIL",
            "support@thedailymarket.co.za",
        ),
        "invoice_url": link,
    }

    text_body = render_to_string(
        "email/invoice_payment_request.txt",
        ctx,
    )

    html_body = render_to_string(
        "email/invoice_payment_request.html",
        ctx,
    )

    subject = f"Payment Request – Invoice INV-{invoice.id}"

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(
            settings,
            "DEFAULT_FROM_EMAIL",
            "accounts@thedailymarket.co.za",
        ),
        to=[email_to],
        headers={
            "Reply-To": getattr(
                settings,
                "SUPPORT_EMAIL",
                "support@thedailymarket.co.za",
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
        message=f"Payment request sent for Invoice {invoice.id}. Link: {link}",
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="Django Email",
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Payment request sent via email.",
    })


