import json
from decimal import Decimal

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from invoices.models import Invoice, PaymentLog


@csrf_exempt
def yoco_webhook(request):

    if request.method != "POST":
        return HttpResponse(status=405)

    data = json.loads(request.body)

    print("=================================")
    print("YOCO WEBHOOK RECEIVED")
    print(data)
    print("=================================")

    try:

        event_type = data.get("type")

        if event_type != "payment.succeeded":
            return HttpResponse(status=200)

        payload = data.get("payload", {})
        metadata = payload.get("metadata", {})

        invoice_id = metadata.get("invoice_id")

        if not invoice_id:
            print("No invoice_id in metadata")
            return HttpResponse(status=200)

        invoice = Invoice.objects.filter(id=invoice_id).first()

        if not invoice:
            print("Invoice not found")
            return HttpResponse(status=404)

        payment_id = payload.get("id")
        amount = Decimal(payload.get("amount")) / Decimal("100")

        # Prevent duplicate payments
        if invoice.transactions.filter(reference=payment_id).exists():
            print("Payment already processed")
            return HttpResponse(status=200)

        # Save gateway log
        PaymentLog.objects.create(
            provider="yoco",
            invoice=invoice,
            transaction_reference=payment_id,
            amount=amount,
            raw_request=data,
            status=payload.get("status"),
        )

        # Record payment using invoice logic
        invoice.record_payment(
            amount=amount,
            reference=payment_id,
            note="Yoco payment",
        )

        print(f"Invoice {invoice_id} payment recorded")

        return HttpResponse(status=200)

    except Exception as e:
        print("Webhook error:", e)
        return HttpResponse(status=400)