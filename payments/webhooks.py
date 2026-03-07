from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal

from invoices.models import Invoice
from invoices.models import PaymentLog


@csrf_exempt
def ozow_notify(request):
    """
    Ozow server-to-server notification endpoint.
    This confirms a payment after Ozow processes it.
    """

    if request.method != "POST":
        return HttpResponse(status=405)

    print("================================")
    print("OZOW NOTIFY RECEIVED")
    print(request.POST)
    print("================================")

    try:

        transaction_reference = request.POST.get("transactionReference")
        status = request.POST.get("status")
        amount = request.POST.get("amount")
        payment_id = request.POST.get("transactionId")

        if not transaction_reference:
            return HttpResponse(status=400)

        # Example reference: INV29
        invoice_id = transaction_reference.replace("INV", "")

        invoice = Invoice.objects.filter(id=invoice_id).first()

        if not invoice:
            return HttpResponse(status=404)

        # Save raw payment log for audit
        PaymentLog.objects.create(
            provider="ozow",
            invoice=invoice,
            transaction_reference=payment_id or transaction_reference,
            amount=Decimal(amount) if amount else Decimal("0.00"),
            raw_request=dict(request.POST),
            status=status,
        )

        # Only process successful payments
        if status == "Complete":

            payment_amount = Decimal(amount)

            invoice.record_payment(
                amount=payment_amount,
                reference=payment_id or transaction_reference,
                note="Ozow payment",
            )

            print(f"Invoice {invoice.id} payment recorded")

        return HttpResponse("OK")

    except Exception as e:
        print("OZOW ERROR:", e)
        return HttpResponse(status=500)