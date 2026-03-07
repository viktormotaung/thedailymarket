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

    print("\n=================================")
    print("YOCO WEBHOOK RECEIVED")
    print(data)
    print("=================================")

    try:

        event_type = data.get("type")

        if event_type != "payment.succeeded":
            print("Event ignored:", event_type)
            return HttpResponse(status=200)

        payload = data.get("payload", {})
        metadata = payload.get("metadata", {})

        invoice_id = metadata.get("invoice_id")

        if not invoice_id:
            print("❌ No invoice_id in metadata")
            return HttpResponse(status=200)

        invoice = Invoice.objects.filter(id=invoice_id).first()

        if not invoice:
            print("❌ Invoice not found:", invoice_id)
            return HttpResponse(status=404)

        payment_id = payload.get("id")
        amount = Decimal(payload.get("amount")) / Decimal("100")

        print("\n--- BEFORE PAYMENT ---")
        print("Invoice:", invoice.id)
        print("Status:", invoice.status)
        print("Deposit Required:", invoice.deposit_required)
        print("Deposit Paid:", invoice.deposit_paid)
        print("Order Status:", invoice.order.status)

        # Prevent duplicate payments
        if invoice.transactions.filter(reference=payment_id).exists():
            print("⚠ Payment already processed")
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

        print("\n--- RECORDING PAYMENT ---")
        print("Amount:", amount)
        print("Reference:", payment_id)

        # 🔑 Core trigger
        invoice.record_payment(
            amount=amount,
            reference=payment_id,
            note="Yoco payment",
        )

        # Refresh invoice from DB
        invoice.refresh_from_db()

        print("\n--- AFTER PAYMENT ---")
        print("Status:", invoice.status)
        print("Deposit Paid:", invoice.deposit_paid)
        print("Paid Date:", invoice.paid_date)
        print("Order Status:", invoice.order.status)

        # Check transactions
        print("\n--- TRANSACTIONS ---")
        for t in invoice.transactions.all():
            print(t.transaction_type, t.amount, t.reference)

        # Check credit entries
        print("\n--- CREDIT ENTRIES ---")
        for ce in invoice.credit_entries.all():
            print(ce.kind, ce.amount)

        # Check commission
        if hasattr(invoice, "commission_entry"):
            print("\n--- COMMISSION CREATED ---")
            ce = invoice.commission_entry
            print("Rep:", ce.rep)
            print("Rep Commission:", ce.rep_amount)
            print("Supervisor Commission:", ce.supervisor_amount)
        else:
            print("\n--- NO COMMISSION ENTRY ---")

        print("\n=================================")
        print("WEBHOOK PROCESS COMPLETE")
        print("=================================\n")

        return HttpResponse(status=200)

    except Exception as e:
        print("❌ WEBHOOK ERROR:", e)
        return HttpResponse(status=400)