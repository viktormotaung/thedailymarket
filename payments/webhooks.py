from django.http import HttpResponse
from invoices.models import Invoice


def ozow_notify(request):

    transaction_reference = request.POST.get("transactionReference")
    status = request.POST.get("status")

    if not transaction_reference:
        return HttpResponse(status=400)

    invoice_id = transaction_reference.replace("INV-", "")
    invoice = Invoice.objects.filter(id=invoice_id).first()

    if not invoice:
        return HttpResponse(status=404)

    if status == "Complete":

        invoice.record_payment(
            amount=Decimal(payment_data.get("amount")) / Decimal("100"),
            reference=payment_data.get("id"),
            note="Yoco payment",
        )

    return HttpResponse("OK")