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

    print("=================================")
    print("YOCO WEBHOOK RECEIVED")
    print(data)
    print("=================================")

    payload = data.get("payload", {})
    metadata = payload.get("metadata", {})

    invoice_id = metadata.get("invoice_id")

    print("Invoice ID:", invoice_id)

    if not invoice_id:
        print("No invoice_id in metadata")
        return HttpResponse(status=200)

    invoice = Invoice.objects.filter(id=int(invoice_id)).first()

    if not invoice:
        print("Invoice not found")
        return HttpResponse(status=200)

    amount = Decimal(payload.get("amount")) / Decimal("100")

    print("Recording payment:", amount)

    invoice.record_payment(
        amount=amount,
        reference=payload.get("id"),
        note="Yoco payment"
    )

    print("Payment recorded")

    return HttpResponse(status=200)




