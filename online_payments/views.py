import json
import logging

import requests
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt

from invoices.models import Invoice
from online_payments.models import Payment
from online_payments.services.ozow import verify_ozow_hash
from online_payments.services.ozow_api import get_ozow_transaction
from online_payments.services.payment_gateway import (
    PaymentGatewayError,
    PaymentGatewayService,
)
from online_payments.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


def start_payment(request, invoice_id):
    """
    Ozow Legacy payment starter.
    Creates internal payment record + builds Ozow form payload.
    """
    invoice = get_object_or_404(Invoice, id=invoice_id)

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
    """
    Ozow server-to-server callback.
    This is the trusted legacy Ozow confirmation point.
    """
    if request.method != "POST":
        return HttpResponse("Invalid", status=400)

    logger.info("Ozow notify received: %s", request.POST)

    if not verify_ozow_hash(request.POST):
        logger.warning("Invalid Ozow hash received")
        return HttpResponse("Invalid hash", status=400)

    reference = request.POST.get("TransactionReference")
    status = request.POST.get("Status")
    transaction_id = request.POST.get("TransactionId")

    try:
        payment = Payment.objects.get(reference=reference)

        if payment.status == "success":
            return HttpResponse("Already processed")

        if status and status.lower() == "complete":
            payment.status = "success"
            payment.ozow_transaction_id = transaction_id
            payment.paid_at = now()
            payment.save()

            logger.info("Ozow payment %s marked successful", payment.reference)
        else:
            payment.status = "failed"
            payment.save(update_fields=["status"])

            logger.info(
                "Ozow payment %s failed with status %s",
                payment.reference,
                status,
            )

    except Payment.DoesNotExist:
        logger.warning("Payment not found for reference %s", reference)
        return HttpResponse("Payment not found", status=404)

    return HttpResponse("OK")


def payment_success(request):
    """
    User-facing success page for Ozow Legacy.
    We still verify with Ozow API before marking success.
    """
    transaction_id = request.GET.get("TransactionId")
    transaction_reference = request.GET.get("TransactionReference")

    if transaction_id and transaction_reference:
        result = get_ozow_transaction(transaction_id)

        if result:
            status = result.get("status")
            payment = Payment.objects.filter(reference=transaction_reference).first()

            if payment and payment.status != "success" and status == "Complete":
                PaymentGatewayService.mark_success(
                    payment=payment,
                    transaction_id=transaction_id,
                )

    return render(request, "online_payments/success.html")


def payment_cancel(request):
    return render(request, "online_payments/cancel.html")


def payment_error(request):
    return render(request, "online_payments/error.html")


def yoco_checkout(request, invoice_id):
    """
    Starts a Yoco card checkout session and redirects user to Yoco.
    """
    invoice = get_object_or_404(Invoice, id=invoice_id)

    try:
        _, redirect_url = PaymentGatewayService.start_yoco_checkout(
            invoice=invoice,
            user=request.user,
        )
        return redirect(redirect_url)

    except PaymentGatewayError as e:
        return HttpResponse(f"Yoco error: {e}", status=500)


@csrf_exempt
def yoco_webhook(request):
    """
    Yoco server-to-server webhook.
    Marks payment successful or failed based on Yoco event.
    """
    if request.method != "POST":
        return HttpResponse("Invalid method", status=405)

    raw_body = request.body.decode("utf-8", errors="ignore")
    logger.info("Yoco webhook raw body: %s", raw_body)
    logger.info("Yoco webhook headers: %s", dict(request.headers))

    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        logger.warning("Invalid JSON received from Yoco webhook")
        return HttpResponse("Invalid JSON", status=400)

    _, message = PaymentGatewayService.handle_yoco_webhook_payload(payload)
    logger.info("Yoco webhook result: %s", message)

    return HttpResponse("OK")


def yoco_success(request):
    """
    User-facing success page after Yoco redirects back.
    Do not treat this as final confirmation; webhook remains authoritative.
    """
    payment_ref = request.GET.get("ref", "")
    payment = Payment.objects.filter(reference=payment_ref).first()

    return render(
        request,
        "online_payments/success.html",
        {"payment": payment},
    )


def yoco_cancel(request):
    """
    User-facing cancel page after Yoco redirects back.
    """
    payment_ref = request.GET.get("ref", "")
    payment = Payment.objects.filter(reference=payment_ref).first()

    return render(
        request,
        "online_payments/cancel.html",
        {"payment": payment},
    )


def test_yoco_connection(request):
    """
    Optional test endpoint to confirm Yoco config is working.
    """
    headers = {
        "Authorization": f"Bearer {settings.YOCO_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "amount": 100,
        "currency": "ZAR",
        "metadata": {"test": True},
        "successUrl": settings.YOCO_SUCCESS_URL,
        "cancelUrl": settings.YOCO_CANCEL_URL,
    }

    try:
        response = requests.post(
            settings.YOCO_API_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}

        return JsonResponse(
            {
                "ok": response.status_code in (200, 201),
                "status_code": response.status_code,
                "response": body,
            },
            status=200 if response.status_code in (200, 201) else 500,
        )

    except Exception as e:
        return JsonResponse(
            {
                "ok": False,
                "error": str(e),
            },
            status=500,
        )


