import json
from decimal import Decimal

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from invoices.models import Invoice


@csrf_exempt
def yoco_webhook(request):
    print("🔥 NEW YOCO WEBHOOK VERSION 🔥")

    print("\n==============================")
    print("YOCO WEBHOOK HIT")
    print("==============================")

    try:

        # Step 1 — parse body
        data = json.loads(request.body)
        print("1️⃣ RAW DATA:", data)

        # Step 2 — event type
        event_type = data.get("type")
        print("2️⃣ EVENT TYPE:", event_type)

        if event_type != "payment.succeeded":
            print("❌ Not a payment success event")
            return HttpResponse(status=200)

        # Step 3 — extract payload
        payload = data.get("payload", {})
        print("3️⃣ PAYLOAD:", payload)

        # Step 4 — metadata
        metadata = payload.get("metadata", {})
        print("4️⃣ METADATA:", metadata)

        invoice_id = metadata.get("invoice_id")
        print("5️⃣ INVOICE ID:", invoice_id)

        if not invoice_id:
            print("❌ No invoice_id found")
            return HttpResponse(status=200)

        # Step 6 — fetch invoice
        invoice = Invoice.objects.filter(id=int(invoice_id)).first()
        print("6️⃣ INVOICE OBJECT:", invoice)

        if not invoice:
            print("❌ Invoice does not exist")
            return HttpResponse(status=200)

        # Step 7 — amount conversion
        raw_amount = payload.get("amount")
        print("7️⃣ RAW AMOUNT:", raw_amount)

        amount = Decimal(raw_amount) / Decimal("100")
        print("8️⃣ CONVERTED AMOUNT:", amount)

        payment_id = payload.get("id")
        print("9️⃣ PAYMENT ID:", payment_id)

        # Step 8 — call payment logic
        print("🔟 CALLING record_payment()")

        invoice.record_payment(
            amount=amount,
            reference=payment_id,
            note="Yoco payment"
        )

        print("✅ PAYMENT RECORDED")

        return HttpResponse(status=200)

    except Exception as e:
        print("❌ WEBHOOK ERROR:", e)
        return HttpResponse(status=400)


