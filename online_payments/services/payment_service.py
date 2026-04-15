import uuid
from django.conf import settings
from django.urls import reverse
from online_payments.models import Payment


class PaymentService:

    @staticmethod
    def create_payment(invoice, request):

        reference = f"PAY-{uuid.uuid4().hex[:10]}"

        payment = Payment.objects.create(
            reference=reference,
            amount=invoice.amount_due,
            client=invoice.client,
            invoice=invoice,
            created_by=request.user,
        )

        payment_url = PaymentService.generate_ozow_link(payment, request)

        return payment, payment_url

    @staticmethod
    def generate_ozow_link(payment, request):

        base_url = settings.OZOW_PAYMENT_URL

        data = {
            "SiteCode": settings.OZOW_SITE_CODE,
            "CountryCode": settings.OZOW_COUNTRY_CODE,
            "CurrencyCode": settings.OZOW_CURRENCY_CODE,
            "Amount": str(payment.amount),
            "TransactionReference": payment.reference,
            "BankReference": payment.reference,
            "CancelUrl": settings.OZOW_CANCEL_URL,
            "ErrorUrl": settings.OZOW_ERROR_URL,
            "SuccessUrl": settings.OZOW_SUCCESS_URL,
            "NotifyUrl": settings.OZOW_NOTIFY_URL,
            "IsTest": "true" if settings.OZOW_IS_TEST else "false",
        }

        # Build hash string (order matters!)
        hash_string = (
            data["SiteCode"] +
            data["CountryCode"] +
            data["CurrencyCode"] +
            data["Amount"] +
            data["TransactionReference"] +
            data["BankReference"] +
            data["CancelUrl"] +
            data["ErrorUrl"] +
            data["SuccessUrl"] +
            data["NotifyUrl"] +
            data["IsTest"]
        )
        from .ozow import generate_ozow_hash
        data["HashCheck"] = generate_ozow_hash(hash_string)

        # Build URL
        query = "&".join([f"{k}={v}" for k, v in data.items()])
        return f"{base_url}?{query}"