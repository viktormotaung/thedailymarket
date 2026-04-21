import logging
import re
import uuid
from datetime import timedelta

import requests
from django.conf import settings
from django.utils.timezone import now

from online_payments.models import Payment
from online_payments.services.ozow_oneapi_auth import (
    generate_correlation_id,
    get_oneapi_auth_headers,
)

logger = logging.getLogger(__name__)


class OzowOneAPIPaymentError(Exception):
    pass


def sanitize_oneapi_reference(value: str, max_length: int = 20) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value)
    return cleaned[:max_length]


def _build_payer_from_invoice(invoice):
    client = invoice.client

    payer_name = (
        getattr(client, "contact_person", None)
        or getattr(client, "organization", None)
        or getattr(client, "name", None)
        or f"Client {client.id}"
    )

    payer = {
        "id": str(getattr(client, "client_number", None) or client.id),
        "name": payer_name,
    }

    cellphone = getattr(client, "phone", None)
    email = getattr(client, "email", None)

    if cellphone:
        payer["cellphone"] = cellphone
    if email:
        payer["email"] = email

    return payer


def _safe_auth_headers(correlation_id: str) -> dict:
    headers = get_oneapi_auth_headers(correlation_id=correlation_id)

    auth_header = headers.get("Authorization")
    if not auth_header or not str(auth_header).startswith("Bearer "):
        raise OzowOneAPIPaymentError(
            "Authorization header is missing or invalid before calling Ozow OneAPI."
        )

    return headers


def create_internal_payment(
    invoice,
    user,
    payment_method,
    institution_id=None,
    institution_name=None,
):
    return Payment.objects.create(
        reference=f"PAY-{uuid.uuid4().hex[:10]}",
        amount=invoice.amount_due,
        client=invoice.client,
        invoice=invoice,
        created_by=user if user and user.is_authenticated else None,
        provider="ozow_oneapi",
        payment_method=payment_method,
        institution_id=institution_id,
        institution_name=institution_name,
        status="pending",
        idempotency_key=str(uuid.uuid4()),
    )


def create_oneapi_payment_request(payment: Payment):
    url = f"{settings.OZOW_ONEAPI_BASE_URL}/v1/payments"
    correlation_id = generate_correlation_id()

    headers = _safe_auth_headers(correlation_id=correlation_id)
    headers["Content-Type"] = "application/json"
    headers["Idempotency-Key"] = payment.idempotency_key

    invoice = payment.invoice
    payer = _build_payer_from_invoice(invoice)
    expire_at = (now() + timedelta(minutes=settings.OZOW_ONEAPI_EXPIRE_MINUTES)).isoformat()

    sanitized_ref = sanitize_oneapi_reference(payment.reference, max_length=20)

    payload = {
        "siteCode": settings.OZOW_ONEAPI_SITE_CODE,
        "region": settings.OZOW_ONEAPI_REGION,
        "amount": {
            "currency": settings.OZOW_ONEAPI_CURRENCY,
            "value": float(payment.amount),
        },
        "merchantReference": payment.reference,
        "beneficiaryReference": sanitized_ref,
        "payerReference": sanitized_ref,
        "payer": payer,
        "returnUrl": settings.OZOW_ONEAPI_RETURN_URL,
        "notifyUrl": settings.OZOW_ONEAPI_NOTIFY_URL,
        "expireAt": expire_at,
    }

    print("=== ONEAPI CREATE PAYMENT DEBUG ===")
    print("URL:", url)
    print("CORRELATION ID:", correlation_id)
    print("HEADERS:", headers)
    print("PAYLOAD:", payload)
    print("===================================")

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30,
    )

    print("=== ONEAPI CREATE PAYMENT RESPONSE ===")
    print("STATUS:", response.status_code)
    print("BODY:", response.text)
    print("======================================")

    logger.info("Ozow OneAPI create payment status: %s", response.status_code)

    if response.status_code not in (200, 201):
        logger.error("Ozow OneAPI create payment error: %s", response.text)
        raise OzowOneAPIPaymentError(
            f"Failed to create payment request. Status {response.status_code}: {response.text}"
        )

    data = response.json()
    payment.oneapi_payment_id = data.get("id")
    payment.save(update_fields=["oneapi_payment_id"])

    return data


def create_oneapi_transaction(payment: Payment):
    if not payment.oneapi_payment_id:
        raise OzowOneAPIPaymentError("Payment has no oneapi_payment_id.")

    url = f"{settings.OZOW_ONEAPI_BASE_URL}/v1/payments/{payment.oneapi_payment_id}/transactions"
    correlation_id = generate_correlation_id()

    headers = _safe_auth_headers(correlation_id=correlation_id)
    headers["Content-Type"] = "application/json"
    headers["Idempotency-Key"] = str(uuid.uuid4())

    if payment.payment_method == "ozowredirect":
        if not payment.institution_id:
            raise OzowOneAPIPaymentError("Institution is required for Pay By Bank.")

        payload = {
            "paymentDetail": {
                "paymentType": "ozowredirect",
                "details": {
                    "institutionId": payment.institution_id,
                },
            }
        }

    elif payment.payment_method == "payshap":
        payload = {
            "paymentDetail": {
                "paymentType": "payshap",
                "details": {}
            }
        }

    else:
        raise OzowOneAPIPaymentError(
            f"Unsupported payment_method: {payment.payment_method}"
        )

    print("=== ONEAPI CREATE TRANSACTION DEBUG ===")
    print("URL:", url)
    print("CORRELATION ID:", correlation_id)
    print("HEADERS:", headers)
    print("PAYLOAD:", payload)
    print("=======================================")

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30,
    )

    print("=== ONEAPI CREATE TRANSACTION RESPONSE ===")
    print("STATUS:", response.status_code)
    print("BODY:", response.text)
    print("==========================================")

    logger.info("Ozow OneAPI create transaction status: %s", response.status_code)

    if response.status_code not in (200, 201):
        logger.error("Ozow OneAPI create transaction error: %s", response.text)
        raise OzowOneAPIPaymentError(
            f"Failed to create transaction. Status {response.status_code}: {response.text}"
        )

    data = response.json()

    transaction = data.get("transaction", {})
    payment.oneapi_transaction_id = transaction.get("id")
    payment.save(update_fields=["oneapi_transaction_id"])

    redirect_url = None
    required_actions = data.get("requiredActionOptions", []) or []

    for action in required_actions:
        if action.get("action") == "redirect" and action.get("uri"):
            redirect_url = action.get("uri")
            break

    if not redirect_url:
        raise OzowOneAPIPaymentError(
            f"Ozow did not return a redirect action. Transaction response: {data}"
        )

    return data, redirect_url


