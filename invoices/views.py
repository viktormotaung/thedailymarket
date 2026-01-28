from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.timezone import now, localdate
from django.http import JsonResponse
from invoices.models import Invoice
from credit.models import CreditEntry  # 👈 for credit repayments
import hashlib
import urllib.parse
from django.core.mail import EmailMultiAlternatives
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from django.utils.timezone import now, make_aware
from datetime import datetime, timedelta, time, date

DAY_OPTIONS = [7, 14, 30, 60]


def staff_check(user):
    return user.is_authenticated and user.is_staff


staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")


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

    # --- filters for template ---
    search = request.GET.get("q", "").strip()
    filter_status = request.GET.get("status", "").strip()
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")

    # --- base date range ---
    end_date = now().date()
    start_date = end_date - timedelta(days=days)

    # optional overrides (YYYY-MM-DD)
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

    # --- timezone-aware datetime range (MySQL safe) ---
    start_dt = make_aware(datetime.combine(start_date, time.min))
    end_dt = make_aware(datetime.combine(end_date, time.max))

    # --- base queryset ---
    recent_qs = (
        Invoice.objects
        .filter(created_at__gte=start_dt, created_at__lte=end_dt)
        .annotate(
            balance=ExpressionWrapper(
                F("amount_due") - F("deposit_paid"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )

    # --- KPIs ---
    recent_unpaid_qs = recent_qs.exclude(status="paid")

    recent_unpaid_total = recent_unpaid_qs.aggregate(
        total_unpaid=Coalesce(Sum("balance"), Decimal("0.00"))
    )["total_unpaid"]

    recent_paid_total = recent_qs.filter(status="paid").aggregate(
        total_paid=Coalesce(Sum("deposit_paid"), Decimal("0.00"))
    )["total_paid"]

    # --- context ---
    context = {
        "DAY_OPTIONS": DAY_OPTIONS,
        "days": days,
        "recent_paid_start": start_date,
        "recent_unpaid_start": start_date,
        "recent_unpaid_total": recent_unpaid_total,
        "recent_unpaid_count": recent_unpaid_qs.count(),
        "recent_paid_total": recent_paid_total,
        "recent_paid_count": recent_qs.filter(status="paid").count(),
        "invoices": (
            recent_qs
            .select_related("client", "order")
            .order_by("-created_at")
        ),
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
    items = order.items.all()

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
def invoice_confirm_payment(request, pk):
    """
    'Confirm Payment' from the modal (manual capture).

    - For deposit: records a cash Transaction using Invoice.record_payment().
    - For credit: records a CreditEntry repayment using Invoice.record_credit_repayment().
    The amount + reference come from the popup form (pre-populated but editable).
    """
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method != "POST":
        return redirect("invoice-view", pk=pk)

    kind = (request.POST.get("kind") or "deposit").lower()  # "deposit" or "credit"
    raw_amount = (request.POST.get("amount") or "").replace(",", "").strip()
    reference = request.POST.get("reference") or f"INV-{invoice.id}: {kind}"

    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, TypeError):
        messages.error(request, "Invalid amount entered.")
        return redirect("invoice-view", pk=pk)

    if amount <= 0:
        messages.error(request, "Amount must be greater than zero.")
        return redirect("invoice-view", pk=pk)

    note = f"Manual {kind} payment captured on invoice screen."

    if kind == "credit":
        # This hits the credit ledger (CreditEntry) only – not deposit.
        invoice.record_credit_repayment(
            amount,
            reference=reference,
            note=note,
        )
        messages.success(
            request,
            f"Credit repayment of R{amount:.2f} recorded for Invoice #{invoice.id}.",
        )
    else:
        # This hits the deposit / cash side.
        invoice.record_payment(
            amount,
            reference=reference,
            note=note,
        )
        messages.success(
            request,
            f"Deposit payment of R{amount:.2f} recorded for Invoice #{invoice.id}.",
        )

    return redirect("invoice-view", pk=pk)


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
@require_POST
def send_invoice_payment_request(request, invoice_id):
    invoice = get_object_or_404(
        Invoice.objects.select_related("order", "order__client"),
        pk=invoice_id
    )
    client = invoice.order.client

    if not client.email:
        return JsonResponse({"success": False, "message": "Client has no email"}, status=400)

    # --- Generate PayFast link ---
    data = [
        ("merchant_id", settings.PAYFAST_MERCHANT_ID),
        ("merchant_key", settings.PAYFAST_MERCHANT_KEY),
        ("return_url", "https://yourdomain.co.za/payfast/return/"),
        ("cancel_url", "https://yourdomain.co.za/payfast/cancel/"),
        ("notify_url", "https://yourdomain.co.za/payfast/itn/"),
        ("name_first", client.contact_person.split()[0]),
        ("name_last", client.contact_person.split()[-1]),
        ("email_address", client.email),
        ("m_payment_id", f"INV-{invoice.id}"),
        ("amount", f"{invoice.amount_due:.2f}"),
        ("item_name", f"Invoice #{invoice.id}"),
    ]

    signature = generate_payfast_signature(data, passphrase=settings.PAYFAST_PASSPHRASE)
    payfast_data = dict(data)
    payfast_data["signature"] = signature
    payfast_link = f"{settings.PAYFAST_PROCESS_URL}?{urllib.parse.urlencode(payfast_data)}"

    # --- Prepare Email ---
    subject = f"The Daily Market – Payment Request for Invoice #{invoice.id}"
    ctx = {
        "client": client,
        "invoice": invoice,
        "payfast_link": payfast_link,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
    }

    text_body = render_to_string("email/payfast_invoice_request.txt", ctx)
    html_body = render_to_string("email/payfast_invoice_request.html", ctx)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[client.email],
        headers={"Reply-To": ctx["support_email"]},
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

    return JsonResponse({"success": True, "message": "Payment request sent successfully."})

@login_required
@staff_required
def invoice_confirm_payment(request, pk):
    """
    'Confirm Payment' from the modal (manual capture).

    - For deposit: records a cash Transaction using Invoice.record_payment().
    - For credit: records a CreditEntry repayment using Invoice.record_credit_repayment().
    The amount + reference come from the popup form (pre-populated but editable).
    """
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method != "POST":
        return redirect("invoice-view", pk=pk)

    kind = (request.POST.get("kind") or "deposit").lower()  # "deposit" or "credit"
    raw_amount = (request.POST.get("amount") or "").replace(",", "").strip()
    reference = request.POST.get("reference") or f"INV-{invoice.id}: {kind}"

    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, TypeError):
        messages.error(request, "Invalid amount entered.")
        return redirect("invoice-view", pk=pk)

    if amount <= 0:
        messages.error(request, "Amount must be greater than zero.")
        return redirect("invoice-view", pk=pk)

    note = f"Manual {kind} payment captured on invoice screen."

    if kind == "credit":
        # This hits the credit ledger (CreditEntry) only – not deposit.
        invoice.record_credit_repayment(
            amount,
            reference=reference,
            note=note,
        )
        messages.success(
            request,
            f"Credit repayment of R{amount:.2f} recorded for Invoice #{invoice.id}.",
        )
    else:
        # This hits the deposit / cash side.
        invoice.record_payment(
            amount,
            reference=reference,
            note=note,
        )
        messages.success(
            request,
            f"Deposit payment of R{amount:.2f} recorded for Invoice #{invoice.id}.",
        )

    return redirect("invoice-view", pk=pk)

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
        Invoice.objects.select_related("order", "client"),
        pk=pk,
    )

    # Try to import ReportLab; fall back gracefully if missing
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
    except ImportError:
        messages.error(request, "PDF generator not installed. Run: pip install reportlab")
        return redirect("invoice-view", pk=pk)

    order = invoice.order
    client = invoice.client

    # Prepare HTTP response
    filename = f"invoice_{invoice.id}.pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Build PDF
    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    y = height - 20 * mm

    # Header
    p.setFont("Helvetica-Bold", 16)
    p.drawString(20 * mm, y, "The Daily Market")
    y -= 8 * mm

    p.setFont("Helvetica", 10)
    p.drawString(20 * mm, y, f"Invoice #{invoice.id}")
    p.drawString(70 * mm, y, f"Date: {invoice.invoice_date}")
    p.drawString(120 * mm, y, f"Due: {invoice.due_date or '-'}")
    y -= 10 * mm

    # Bill To
    p.setFont("Helvetica-Bold", 11)
    p.drawString(20 * mm, y, "Bill To:")
    y -= 6 * mm

    p.setFont("Helvetica", 10)
    p.drawString(20 * mm, y, f"{client}")
    y -= 5 * mm
    if getattr(client, "address_line1", ""):
        p.drawString(20 * mm, y, client.address_line1)
        y -= 5 * mm
    addr_line = ", ".join(
        filter(
            None,
            [
                getattr(client, "suburb", ""),
                getattr(client, "city", ""),
                getattr(client, "province", ""),
                getattr(client, "postal_code", ""),
            ],
        )
    )
    if addr_line:
        p.drawString(20 * mm, y, addr_line)
        y -= 5 * mm
    if getattr(client, "country", ""):
        p.drawString(20 * mm, y, client.country)
        y -= 8 * mm

    # Table header
    p.setFont("Helvetica-Bold", 10)
    p.drawString(20 * mm, y, "SKU")
    p.drawString(45 * mm, y, "Product")
    p.drawRightString(135 * mm, y, "Qty")
    p.drawRightString(160 * mm, y, "Unit Excl")
    p.drawRightString(190 * mm, y, "Line Excl")
    y -= 2 * mm
    p.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    # Items
    p.setFont("Helvetica", 10)
    items = order.items.select_related("product", "category").all()
    for it in items:
        if y < 30 * mm:
            p.showPage()
            y = height - 20 * mm
            p.setFont("Helvetica-Bold", 10)
            p.drawString(20 * mm, y, "SKU")
            p.drawString(45 * mm, y, "Product")
            p.drawRightString(135 * mm, y, "Qty")
            p.drawRightString(160 * mm, y, "Unit Excl")
            p.drawRightString(190 * mm, y, "Line Excl")
            y -= 2 * mm
            p.line(20 * mm, y, 190 * mm, y)
            y -= 6 * mm
            p.setFont("Helvetica", 10)

        sku = it.sku or (it.product.sku if it.product_id else "")
        name = it.product_name or (it.product.name if it.product_id else "")

        p.drawString(20 * mm, y, sku)
        p.drawString(45 * mm, y, name[:50])
        p.drawRightString(135 * mm, y, f"{it.quantity}")
        p.drawRightString(160 * mm, y, f"{it.unit_price_excl:.2f}")
        p.drawRightString(190 * mm, y, f"{it.line_total_excl:.2f}")
        y -= 6 * mm

    # Totals box
    y -= 6 * mm
    p.line(120 * mm, y, 190 * mm, y)
    y -= 6 * mm

    def r(v: Decimal) -> str:
        return f"{(v or Decimal('0.00')):.2f}"

    p.drawRightString(160 * mm, y, "Subtotal (Excl):")
    p.drawRightString(190 * mm, y, f"R{r(order.subtotal_excl)}")
    y -= 6 * mm

    p.drawRightString(160 * mm, y, "Discounts (Excl):")
    p.drawRightString(190 * mm, y, f"- R{r(order.discount_total_excl)}")
    y -= 6 * mm

    p.drawRightString(160 * mm, y, "Delivery (Excl):")
    p.drawRightString(190 * mm, y, f"R{r(order.delivery_fee_excl)}")
    y -= 6 * mm

    p.drawRightString(160 * mm, y, "VAT Total:")
    p.drawRightString(190 * mm, y, f"R{r(order.vat_total)}")
    y -= 6 * mm

    p.setFont("Helvetica-Bold", 11)
    p.drawRightString(160 * mm, y, "Grand Total (Incl):")
    p.drawRightString(190 * mm, y, f"R{r(order.grand_total_inc)}")
    y -= 10 * mm

    # Payment snapshot from invoice
    p.setFont("Helvetica", 10)
    p.drawString(20 * mm, y, f"Deposit required: R{r(invoice.deposit_required)}")
    y -= 5 * mm
    p.drawString(20 * mm, y, f"Deposit paid: R{r(invoice.deposit_paid)}")
    y -= 5 * mm
    p.drawString(20 * mm, y, f"Credit used: R{r(invoice.credit_used)}")
    y -= 5 * mm
    p.drawString(20 * mm, y, f"Amount due now: R{r(invoice.amount_due)}")
    y -= 8 * mm

    p.setFont("Helvetica-Oblique", 9)
    p.drawString(20 * mm, y, f"Status: {invoice.get_status_display()}")
    y -= 5 * mm
    p.drawString(20 * mm, y, "Thank you for your business.")

    p.showPage()
    p.save()
    return response


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


