from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from invoices.models import Invoice
from .ozow_service import create_payment_request


@login_required
def pay_invoice(request, pk):

    invoice = get_object_or_404(Invoice, id=pk)

    if invoice.amount_due <= 0:
        return redirect("view-invoice", pk=invoice.id)

    data = create_payment_request(invoice, request.user)

    if data.get("url"):
        return redirect(data["url"])

    return redirect("view-invoice", pk=invoice.id)

def ozow_success(request):
    return render(request, "payments/success.html")

def ozow_cancel(request):
    return render(request, "payments/cancel.html")
