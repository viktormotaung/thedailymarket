import hashlib
from django.conf import settings
from django.shortcuts import redirect, get_object_or_404, render
from django.http import HttpResponse
from invoices.models import Invoice
from urllib.parse import urlencode
from django.http import JsonResponse
from decimal import Decimal




def generate_hash(data_string):
    combined = data_string + settings.OZOW_PRIVATE_KEY
    return hashlib.sha512(combined.encode()).hexdigest()


def pay_invoice(request, invoice_id):

    invoice = get_object_or_404(Invoice, id=invoice_id)

    print("\n==============================")
    print("OZOW PAYMENT DEBUG")
    print("==============================")

    # Invoice information
    print("Invoice ID:", invoice.id)
    print("Client:", invoice.client)
    print("Deposit Required:", invoice.amount_due)
    print("Deposit Paid:", invoice.deposit_paid)

    amount = "{:.2f}".format(invoice.amount_due)

    transaction_reference = f"INV{invoice.id}"
    bank_reference = f"DailyMarket{invoice.id}"

    success_url = request.build_absolute_uri("/payment-success/")
    cancel_url = request.build_absolute_uri("/payment-cancel/")
    notify_url = request.build_absolute_uri("/payments/ozow/notify/")

    print("\n--- URLs ---")
    print("Success URL:", success_url)
    print("Cancel URL:", cancel_url)
    print("Notify URL:", notify_url)

    hash_string = (
        settings.OZOW_SITE_CODE +
        settings.OZOW_COUNTRY_CODE +
        settings.OZOW_CURRENCY_CODE +
        amount +
        transaction_reference +
        bank_reference +
        invoice.client.email +
        success_url +
        cancel_url +
        notify_url
    )

    print("\nHash String:")
    print(hash_string)

    hash_check = generate_hash(hash_string)

    print("\nGenerated Hash:")
    print(hash_check)

    payment_data = {
        "SiteCode": settings.OZOW_SITE_CODE,
        "CountryCode": settings.OZOW_COUNTRY_CODE,
        "CurrencyCode": settings.OZOW_CURRENCY_CODE,
        "Amount": amount,
        "TransactionReference": transaction_reference,
        "BankReference": bank_reference,
        "CustomerEmail": invoice.client.email,
        "SuccessUrl": success_url,
        "CancelUrl": cancel_url,
        "NotifyUrl": notify_url,
        "HashCheck": hash_check,
    }

    print("\nPayment Data:")
    for k, v in payment_data.items():
        print(f"{k}: {v}")

    redirect_url = settings.OZOW_PAYMENT_URL + "?" + urlencode(payment_data)

    print("\nRedirect URL:")
    print(redirect_url)

    print("==============================\n")

    return JsonResponse({
        "invoice_id": invoice.id,
        "amount": amount,
        "payment_data": payment_data,
        "redirect_url": redirect_url
    })






def ozow_notify(request):

    print("\n==============================")
    print("OZOW NOTIFY RECEIVED")
    print("==============================")

    data = request.POST.dict()

    print("RAW DATA:", data)

    transaction_reference = data.get("TransactionReference")
    bank_reference = data.get("BankReference")
    amount = data.get("Amount")
    status = data.get("TransactionStatus")
    hash_check = data.get("HashCheck")

    if not transaction_reference:
        print("No transaction reference")
        return HttpResponse("Missing reference", status=400)

    invoice_id = transaction_reference.replace("INV", "")

    try:
        invoice = Invoice.objects.get(id=invoice_id)
    except Invoice.DoesNotExist:
        print("Invoice not found:", invoice_id)
        return HttpResponse("Invoice not found", status=404)

    # -------------------------------------------------
    # Save raw log (for debugging and audit)
    # -------------------------------------------------

    log = PaymentLog.objects.create(
        provider="ozow",
        invoice=invoice,
        transaction_reference=transaction_reference,
        amount=Decimal(amount or "0"),
        raw_request=data,
        status=status,
    )

    print("PaymentLog created:", log.id)

    # -------------------------------------------------
    # Verify Ozow hash (security check)
    # -------------------------------------------------

    hash_string = (
        settings.OZOW_SITE_CODE +
        settings.OZOW_COUNTRY_CODE +
        settings.OZOW_CURRENCY_CODE +
        amount +
        transaction_reference +
        bank_reference +
        data.get("CustomerEmail", "") +
        data.get("SuccessUrl", "") +
        data.get("CancelUrl", "") +
        data.get("NotifyUrl", "")
    )

    calculated_hash = generate_hash(hash_string)

    print("Received Hash:", hash_check)
    print("Calculated Hash:", calculated_hash)

    if hash_check != calculated_hash:
        print("HASH VERIFICATION FAILED")
        log.status = "hash_failed"
        log.save(update_fields=["status"])
        return HttpResponse("Invalid hash", status=400)

    print("HASH VERIFIED")

    # -------------------------------------------------
    # Prevent duplicate payments
    # -------------------------------------------------

    if invoice.is_fully_paid():
        print("Invoice already paid")
        log.status = "duplicate"
        log.save(update_fields=["status"])
        return HttpResponse("Already processed")

    # -------------------------------------------------
    # Process successful payment
    # -------------------------------------------------

    if status == "Complete":

        print("Processing payment")

        invoice.record_payment(
            Decimal(amount),
            reference=transaction_reference,
            note="Ozow payment"
        )

        log.status = "processed"
        log.save(update_fields=["status"])

        print("Invoice payment recorded")

    else:

        print("Payment status:", status)
        log.status = status
        log.save(update_fields=["status"])

    print("==============================\n")

    return HttpResponse("OK")

def payment_success(request):
    return render(request, "payments/success.html")


def payment_cancel(request):
    return render(request, "payments/cancel.html")