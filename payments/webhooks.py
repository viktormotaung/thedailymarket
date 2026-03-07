import json
from decimal import Decimal

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from invoices.models import Invoice, PaymentLog


@csrf_exempt
def yoco_webhook(request):

    import json
    from decimal import Decimal

    data = json.loads(request.body)

    print("\n=================================")
    print("YOCO WEBHOOK RECEIVED")
    print(data)
    print("=================================")

    try:

        event_type = data.get("type")
        print("Event type:", event_type)

        if event_type != "payment.succeeded":
            print("Event ignored")
            return HttpResponse(status=200)

        payload = data.get("payload", {})
        metadata = payload.get("metadata", {})

        invoice_id = metadata.get("invoice_id")

        print("Invoice ID:", invoice_id)

        if not invoice_id:
            print("No invoice id")
            return HttpResponse(status=200)

        invoice = Invoice.objects.get(id=int(invoice_id))

        amount = Decimal(payload["amount"]) / Decimal("100")
        payment_id = payload["id"]

        print("Amount:", amount)
        print("Payment ID:", payment_id)

        invoice.record_payment(
            amount=amount,
            reference=payment_id,
            note="Yoco payment"
        )

        print("Payment recorded successfully")

        return HttpResponse(status=200)

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return HttpResponse(status=400)




