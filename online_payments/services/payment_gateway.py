import logging
import uuid
from decimal import Decimal

import requests
from django.conf import settings
from django.utils.timezone import now

from online_payments.models import Payment

logger = logging.getLogger(__name__)


class PaymentGatewayError(Exception):
    pass


class PaymentGatewayService:
    """
    Unified gateway layer for:
    - ozow (legacy)
    - yoco
    """

    SUPPORTED_PROVIDERS = ("ozow", "yoco")

    @classmethod
    def create_internal_payment(cls, *, invoice, user, provider):
        if provider not in cls.SUPPORTED_PROVIDERS:
            raise PaymentGatewayError(f"Unsupported provider: {provider}")

        return Payment.objects.create(
            reference=f"PAY-{uuid.uuid4().hex[:10]}",
            amount=invoice.amount_due or Decimal("0.00"),
            client=invoice.client,
            invoice=invoice,
            created_by=user if user and user.is_authenticated else None,
            provider=provider,
            status="pending",
            idempotency_key=str(uuid.uuid4()),
        )

    @classmethod
    def start_yoco_checkout(cls, *, invoice, user):
        if invoice.amount_due <= 0:
            raise PaymentGatewayError("Invoice already paid or has no amount due.")

        payment = cls.create_internal_payment(
            invoice=invoice,
            user=user,
            provider="yoco",
        )

        redirect_url = cls._start_yoco_checkout(payment)
        return payment, redirect_url

    @classmethod
    def _start_yoco_checkout(cls, payment):
        headers = {
            "Authorization": f"Bearer {settings.YOCO_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "amount": int(payment.amount * 100),
            "currency": "ZAR",
            "metadata": {
                "invoice_id": payment.invoice.id,
                "payment_reference": payment.reference,
            },
            "successUrl": f"{settings.YOCO_SUCCESS_URL}?ref={payment.reference}",
            "cancelUrl": f"{settings.YOCO_CANCEL_URL}?ref={payment.reference}",
        }

        logger.info("Creating Yoco checkout for %s", payment.reference)
        logger.debug("Yoco payload: %s", payload)

        response = requests.post(
            settings.YOCO_API_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

        logger.info(
            "Yoco response status for %s: %s",
            payment.reference,
            response.status_code,
        )
        logger.debug("Yoco response body for %s: %s", payment.reference, response.text)

        if response.status_code not in (200, 201):
            raise PaymentGatewayError(
                f"Failed to create Yoco checkout. Status {response.status_code}: {response.text}"
            )

        data = response.json()
        checkout_url = data.get("redirectUrl") or data.get("url")

        if not checkout_url:
            raise PaymentGatewayError("Yoco did not return a checkout URL.")

        return checkout_url

    @classmethod
    def mark_success(cls, *, payment, transaction_id=None):
        if payment.status == "success":
            return payment

        payment.status = "success"
        payment.paid_at = now()

        update_fields = ["status", "paid_at"]

        if payment.provider == "ozow" and transaction_id:
            payment.ozow_transaction_id = transaction_id
            update_fields.append("ozow_transaction_id")

        payment.save(update_fields=update_fields)
        return payment

    @classmethod
    def mark_failed(cls, *, payment):
        if payment.status == "success":
            return payment

        payment.status = "failed"
        payment.save(update_fields=["status"])
        return payment

    @classmethod
    def get_payment_by_reference(cls, reference):
        return Payment.objects.filter(reference=reference).first()

    @classmethod
    def handle_yoco_webhook_payload(cls, payload):
        event_type = payload.get("type", "")
        data = payload.get("data", {}) or {}
        metadata = data.get("metadata", {}) or {}

        payment_reference = metadata.get("payment_reference")

        if not payment_reference:
            return None, "No payment reference"

        payment = cls.get_payment_by_reference(payment_reference)
        if not payment:
            return None, "Payment not found"

        if event_type == "payment.succeeded":
            cls.mark_success(payment=payment)
            return payment, "Payment marked successful"

        if event_type in ("payment.failed", "payment.cancelled"):
            cls.mark_failed(payment=payment)
            return payment, "Payment marked failed"

        return payment, "Webhook received but no state change"