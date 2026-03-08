import json
from decimal import Decimal

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from invoices.models import Invoice


@csrf_exempt
def yoco_webhook(request):

    print("\n🔥 NEW YOCO WEBHOOK VERSION 🔥")
    print("==============================")

    if request.method != "POST":
        print("❌ Invalid request method:", request.method)
        return HttpResponse(status=405)

    try:

        # -----------------------------
        # 1️⃣ Parse request body
        # -----------------------------
        data = json.loads(request.body)
        print("1️⃣ RAW DATA:", data)

        # -----------------------------
        # 2️⃣ Validate event type
        # -----------------------------
        event_type = data.get("type")
        print("2️⃣ EVENT TYPE:", event_type)

        if event_type != "payment.succeeded":
            print("⚠ Ignoring event:", event_type)
            return HttpResponse(status=200)

        # -----------------------------
        # 3️⃣ Extract payload
        # -----------------------------
        payload = data.get("payload", {})
        print("3️⃣ PAYLOAD:", payload)

        metadata = payload.get("metadata", {})
        print("4️⃣ METADATA:", metadata)

        # -----------------------------
        # 4️⃣ Extract invoice ID
        # -----------------------------
        invoice_id = metadata.get("invoice_id")
        print("5️⃣ INVOICE ID:", invoice_id)

        if not invoice_id:
            print("❌ No invoice_id in metadata")
            return HttpResponse(status=200)

        # -----------------------------
        # 5️⃣ Fetch invoice
        # -----------------------------
        invoice = Invoice.objects.filter(id=int(invoice_id)).first()
        print("6️⃣ INVOICE OBJECT:", invoice)

        if not invoice:
            print("❌ Invoice not found:", invoice_id)
            return HttpResponse(status=200)

        # -----------------------------
        # 6️⃣ Convert amount
        # Yoco sends cents
        # -----------------------------
        raw_amount = payload.get("amount")
        print("7️⃣ RAW AMOUNT:", raw_amount)

        amount = Decimal(raw_amount) / Decimal("100")
        print("8️⃣ CONVERTED AMOUNT:", amount)

        payment_id = payload.get("id")
        print("9️⃣ PAYMENT ID:", payment_id)

        # -----------------------------
        # 🔒 Prevent duplicate payments
        # -----------------------------
        if invoice.transactions.filter(reference=payment_id).exists():
            print("⚠ Payment already recorded")
            return HttpResponse(status=200)

        # -----------------------------
        # 🔟 Record payment
        # -----------------------------
        print("🔟 CALLING record_payment()")

        invoice.record_payment(
            amount=amount,
            reference=payment_id,
            note="Yoco payment"
        )

        print("✅ PAYMENT RECORDED SUCCESSFULLY")

        # Refresh to inspect outcome
        invoice.refresh_from_db()

        print("📊 NEW STATUS:", invoice.status)
        print("💰 DEPOSIT PAID:", invoice.deposit_paid)
        print("📅 PAID DATE:", invoice.paid_date)
        print("📦 ORDER STATUS:", invoice.order.status)

        print("==============================")

        return HttpResponse(status=200)

    except Exception as e:
        print("❌ WEBHOOK ERROR:", str(e))
        return HttpResponse(status=400)

