import logging
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.utils.timezone import now

from invoices.models import Invoice
from .models import Payment
from online_payments.services.payment_service import PaymentService
from online_payments.services.ozow import verify_ozow_hash

from online_payments.services.ozow_api import get_ozow_transaction


logger = logging.getLogger(__name__)


def start_payment(request, invoice_id):

    invoice = get_object_or_404(Invoice, id=invoice_id)

    # 🔴 Prevent duplicate / invalid payments
    if invoice.amount_due <= 0:
        return HttpResponse("Invoice already paid", status=400)

    payment, ozow_data = PaymentService.create_payment(invoice, request)

    return render(
        request,
        "online_payments/payment_modal.html",
        {
            "ozow_data": ozow_data,
            "payment": payment,
        },
    )


@csrf_exempt
def ozow_notify(request):

    if request.method != "POST":
        return HttpResponse("Invalid", status=400)

    logger.info(f"Ozow notify received: {request.POST}")

    print("Skipping notify hash validation for now")

    reference = request.POST.get("TransactionReference")
    status = request.POST.get("Status")
    transaction_id = request.POST.get("TransactionId")

    try:
        payment = Payment.objects.get(reference=reference)

        # Duplicate protection
        if payment.status == "success":
            return HttpResponse("Already processed")

        if status and status.lower() == "complete":

            payment.status = "success"
            payment.ozow_transaction_id = transaction_id
            payment.paid_at = now()
            payment.save()

            logger.info(f"Payment {payment.reference} marked successful.")

            if payment.invoice:
                payment.invoice.mark_paid()
                logger.info(f"Invoice {payment.invoice.id} marked paid.")

        else:
            payment.status = "failed"
            payment.save()

            logger.info(f"Payment {payment.reference} failed with status {status}")

    except Payment.DoesNotExist:
        logger.warning(f"Payment not found for reference {reference}")
        return HttpResponse("Payment not found", status=404)

    return HttpResponse("OK")


def payment_success(request):
    transaction_id = request.GET.get("TransactionId")
    transaction_reference = request.GET.get("TransactionReference")

    if transaction_id and transaction_reference:
        result = get_ozow_transaction(transaction_id)

        if result:
            status = result.get("status")

            try:
                payment = Payment.objects.get(reference=transaction_reference)

                if status == "Complete" and payment.status != "success":
                    payment.status = "success"
                    payment.ozow_transaction_id = transaction_id
                    payment.paid_at = now()
                    payment.save()

                    if payment.invoice:
                        payment.invoice.mark_paid()

            except Payment.DoesNotExist:
                print("Payment not found:", transaction_reference)

    return render(request, "online_payments/success.html")


def payment_cancel(request):
    return render(request, "online_payments/cancel.html")


def payment_error(request):
    return render(request, "online_payments/error.html")