import hashlib
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect, get_object_or_404, render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required

from invoices.models import Invoice, PaymentLog


# =========================================================
# HASH GENERATOR
# =========================================================

def generate_hash(data_string):
    combined = data_string + settings.OZOW_PRIVATE_KEY
    return hashlib.sha512(combined.encode()).hexdigest()


# =========================================================
# PAY INVOICE (START OZOW PAYMENT)
# =========================================================

@login_required
def pay_invoice(request, invoice_id):

    invoice = get_object_or_404(Invoice, id=invoice_id)

    print("\n==============================")
    print("OZOW PAYMENT DEBUG")
    print("==============================")

    print("Invoice ID:", invoice.id)
    print("Client:", invoice.client)
    print("Deposit Required:", invoice.amount_due)
    print("Deposit Paid:", invoice.deposit_paid)

    # Remaining deposit to pay
    remaining = invoice.amount_due - invoice.deposit_paid
    amount = "{:.2f}".format(remaining)

    transaction_reference = f"INV{invoice.id}"
    bank_reference = f"DailyMarket{invoice.id}"

    success_url = request.build_absolute_uri("/payment-success/")
    cancel_url = request.build_absolute_uri("/payment-cancel/")
    notify_url = request.build_absolute_uri("/payments/ozow/notify/")
    error_url = request.build_absolute_uri("/payment-error/")

    print("\n--- URLs ---")
    print("Success URL:", success_url)
    print("Cancel URL:", cancel_url)
    print("Notify URL:", notify_url)
    print("Error URL:", error_url)

    # Build hash string
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
        error_url +
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
        "ErrorUrl": error_url,
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

    return redirect(redirect_url)


# =========================================================
# OZOW NOTIFY WEBHOOK
# =========================================================

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

    # =========================================================
    # LOG RAW PAYMENT DATA
    # =========================================================

    log = PaymentLog.objects.create(
        provider="ozow",
        invoice=invoice,
        transaction_reference=transaction_reference,
        amount=Decimal(amount or "0"),
        raw_request=data,
        status=status,
    )

    print("PaymentLog created:", log.id)

    # =========================================================
    # HASH VERIFICATION
    # =========================================================

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

    # =========================================================
    # DUPLICATE PAYMENT PROTECTION
    # =========================================================

    if invoice.is_fully_paid():
        print("Invoice already paid")
        log.status = "duplicate"
        log.save(update_fields=["status"])
        return HttpResponse("Already processed")

    # =========================================================
    # PROCESS PAYMENT
    # =========================================================

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


# =========================================================
# SUCCESS / CANCEL PAGES
# =========================================================

def payment_success(request):
    return render(request, "payments/success.html")


def payment_cancel(request):
    return render(request, "payments/cancel.html")


def ozow_cancel(request):
    return render(request, "payments/cancel.html")