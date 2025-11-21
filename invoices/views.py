from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models.functions import Coalesce
from decimal import Decimal
from datetime import timedelta
from django.utils.timezone import now
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.timezone import localdate
from django.contrib import messages



from invoices.models import Invoice
from django.contrib.auth.decorators import user_passes_test

DAY_OPTIONS = [7, 14, 30, 60]

def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url='/portal/client/login/')

@login_required
@staff_required
def invoice_list(request):
    raw = request.GET.get("days", "7")
    try:
        days = int(raw)
    except ValueError:
        days = 7
    if days not in DAY_OPTIONS:
        days = 7

    # NEW: pull filters safely for the template
    search = request.GET.get("q", "").strip()
    filter_status = request.GET.get("status", "").strip()
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")

    recent_start = now().date() - timedelta(days=days)

    recent_qs = (
        Invoice.objects
        .filter(created_at__date__gte=recent_start)
        .annotate(balance=ExpressionWrapper(
            F("amount_due") - F("deposit_paid"),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        ))
    )

    recent_unpaid_qs = recent_qs.exclude(status="paid")
    recent_unpaid_total = recent_unpaid_qs.aggregate(
        total_unpaid=Coalesce(Sum("balance"), Decimal("0.00"))
    )["total_unpaid"]

    recent_paid_total = recent_qs.filter(status="paid").aggregate(
        total_paid=Coalesce(Sum("deposit_paid"), Decimal("0.00"))
    )["total_paid"]

    context = {
        "DAY_OPTIONS": DAY_OPTIONS,
        "days": days,
        "recent_paid_start": recent_start,
        "recent_unpaid_start": recent_start,
        "recent_unpaid_total": recent_unpaid_total,
        "recent_unpaid_count": recent_unpaid_qs.count(),
        "recent_paid_total": recent_paid_total,
        "recent_paid_count": recent_qs.filter(status="paid").count(),
        "invoices": recent_qs.select_related("client", "order").order_by("-created_at"),

        # NEW: template inputs
        "search": search,
        "filter_status": filter_status,
        "date_from": date_from,
        "date_to": date_to,
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
    deposit_outstanding = max(invoice.amount_due - (invoice.deposit_paid or 0), 0)

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
        },
    )
    
@login_required
@staff_required
def invoice_create(request):
    return render(request, 'invoices/invoice_create.html')


@login_required
@staff_required
def invoice_edit(request, pk):
    return render(request, 'invoices/invoice_edit.html')


@login_required
@staff_required
def invoice_download(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("order", "client"),
        pk=pk
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
    p.drawString(20 * mm, y, "Seshibo Daily Market")
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
    if client.address_line1:
        p.drawString(20 * mm, y, client.address_line1)
        y -= 5 * mm
    addr_line = ", ".join(filter(None, [client.suburb, client.city, client.province, client.postal_code]))
    if addr_line:
        p.drawString(20 * mm, y, addr_line)
        y -= 5 * mm
    if client.country:
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

        p.drawString(20 * mm, y, it.sku or (it.product.sku if it.product_id else ""))
        p.drawString(45 * mm, y, (it.product_name or (it.product.name if it.product_id else ""))[:50])
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
