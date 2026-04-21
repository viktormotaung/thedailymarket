import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.utils.timezone import now
from django.contrib import messages
from invoices.models import Invoice
from .models import Payment
from online_payments.services.payment_service import PaymentService
from online_payments.services.ozow import verify_ozow_hash

from online_payments.services.ozow_api import get_ozow_transaction

from django.http import JsonResponse
from online_payments.services.ozow_oneapi_auth import get_oneapi_access_token, OzowOneAPIAuthError

from online_payments.services.ozow_oneapi_methods import (
    get_oneapi_payment_methods,
    OzowOneAPIMethodsError,
)


from online_payments.services.ozow_oneapi_payments import (
    OzowOneAPIPaymentError,
    create_internal_payment,
    create_oneapi_payment_request,
    create_oneapi_transaction,
)

logger = logging.getLogger(__name__)







def start_payment(request, invoice_id):

    invoice = get_object_or_404(Invoice, id=invoice_id)

    # Prevent duplicate / invalid payments
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

    if not verify_ozow_hash(request.POST):
        logger.warning("Invalid Ozow hash received")
        return HttpResponse("Invalid hash", status=400)

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


def oneapi_checkout_options(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)

    payload = get_oneapi_payment_methods()
    results = payload.get("results", [])

    pay_by_bank = None
    payshap = None

    for item in results:
        name = (item.get("name") or "").lower()
        if name == "pay by bank":
            pay_by_bank = item
        elif name == "bank api":
            for inst in item.get("institutions", []):
                if (inst.get("name") or "").lower() == "payshap":
                    payshap = {
                        "method": item,
                        "institution": inst,
                    }

    context = {
        "invoice": invoice,
        "pay_by_bank": pay_by_bank,
        "payshap": payshap,
    }
    return render(request, "online_payments/oneapi_checkout_options.html", context)


def oneapi_start_payment(request, invoice_id):
    if request.method != "POST":
        return HttpResponse("Invalid request method", status=405)

    invoice = get_object_or_404(Invoice, id=invoice_id)

    if invoice.amount_due <= 0:
        return HttpResponse("Invoice already paid", status=400)

    payment_method = request.POST.get("payment_method")
    institution_id = request.POST.get("institution_id", "").strip()
    institution_name = request.POST.get("institution_name", "").strip()

    if payment_method not in ("ozowredirect", "payshap"):
        return HttpResponse("Invalid payment method", status=400)

    if payment_method == "ozowredirect" and not institution_id:
        return HttpResponse("Institution is required for Pay By Bank", status=400)

    try:
        payment = create_internal_payment(
            invoice=invoice,
            user=request.user,
            payment_method=payment_method,
            institution_id=institution_id or None,
            institution_name=institution_name or None,
        )

        create_oneapi_payment_request(payment)
        _, redirect_url = create_oneapi_transaction(payment)

        return redirect(redirect_url)

    except OzowOneAPIPaymentError as e:
        return HttpResponse(f"OneAPI error: {e}", status=500)
    


@csrf_exempt
def oneapi_return(request):
    # For now, we do not trust the return page as final payment confirmation.
    # It is only a user-facing landing page.
    payment_ref = request.GET.get("merchantReference") or request.GET.get("reference") or ""
    payment = Payment.objects.filter(reference=payment_ref).first()

    return render(
        request,
        "online_payments/oneapi_return.html",
        {"payment": payment},
    )


@csrf_exempt
def oneapi_webhook(request):
    if request.method != "POST":
        return HttpResponse("Invalid method", status=405)

    raw_body = request.body.decode("utf-8", errors="ignore")
    logger.info("OneAPI webhook raw body: %s", raw_body)
    logger.info("OneAPI webhook headers: %s", dict(request.headers))

    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        payload = {}

    event_type = payload.get("eventType") or payload.get("type") or ""
    data = payload.get("data") or {}

    # Best-effort handling until we confirm exact live webhook payload shape
    transaction_id = (
        data.get("transactionId")
        or data.get("id")
        or payload.get("transactionId")
    )

    merchant_reference = (
        data.get("merchantReference")
        or payload.get("merchantReference")
    )

    status = (
        data.get("status")
        or payload.get("status")
        or ""
    )

    if not merchant_reference:
        return HttpResponse("No merchant reference", status=200)

    payment = Payment.objects.filter(reference=merchant_reference).first()
    if not payment:
        return HttpResponse("Payment not found", status=200)

    normalized_status = str(status).lower()

    if event_type == "transaction.complete" or normalized_status in ("successful", "success", "complete"):
        if payment.status != "success":
            payment.status = "success"
            payment.oneapi_transaction_id = transaction_id or payment.oneapi_transaction_id
            payment.paid_at = now()
            payment.save()

    elif normalized_status in ("error", "failed", "cancelled"):
        if payment.status != "success":
            payment.status = "failed"
            payment.save()

    return HttpResponse("OK")


def test_ozow_oneapi_token(request):
    try:
        token = get_oneapi_access_token()
        return JsonResponse({
            "ok": True,
            "token_preview": f"{token[:20]}..." if token else None,
        })
    except OzowOneAPIAuthError as e:
        return JsonResponse({
            "ok": False,
            "error": str(e),
        }, status=500)
    

def test_ozow_oneapi_payment_methods(request):
    try:
        payload = get_oneapi_payment_methods()

        results = payload.get("results", [])

        simplified = []
        for item in results:
            simplified.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "friendlyName": item.get("friendlyName"),
                "available": item.get("available"),
                "institutions": [
                    {
                        "id": inst.get("id"),
                        "name": inst.get("name"),
                        "friendlyName": inst.get("friendlyName"),
                        "available": inst.get("available"),
                    }
                    for inst in item.get("institutions", [])
                ],
            })

        return JsonResponse({
            "ok": True,
            "count": len(simplified),
            "results": simplified,
        })

    except OzowOneAPIMethodsError as e:
        return JsonResponse({
            "ok": False,
            "error": str(e),
        }, status=500)