import uuid
from decimal import Decimal
from django.conf import settings

from online_payments.models import Payment
from online_payments.services.ozow import generate_ozow_hash


class PaymentService:

    @staticmethod
    def create_payment(invoice, request):

        reference = f"PAY-{uuid.uuid4().hex[:10]}"

        payment = Payment.objects.create(
            reference=reference,
            amount=invoice.amount_due or Decimal("0.00"),
            client=invoice.client,
            invoice=invoice,
            created_by=request.user if request.user.is_authenticated else None,
        )

        ozow_data = PaymentService.generate_ozow_data(payment)

        return payment, ozow_data

    @staticmethod
    def generate_ozow_data(payment):

        data = {
            "SiteCode": settings.OZOW_SITE_CODE.strip(),
            "CountryCode": settings.OZOW_COUNTRY_CODE.strip(),
            "CurrencyCode": settings.OZOW_CURRENCY_CODE.strip(),
            "Amount": f"{payment.amount:.2f}",
            "TransactionReference": payment.reference,
            "BankReference": payment.reference,
            "CancelUrl": settings.OZOW_CANCEL_URL.strip(),
            "ErrorUrl": settings.OZOW_ERROR_URL.strip(),
            "SuccessUrl": settings.OZOW_SUCCESS_URL.strip(),
            "NotifyUrl": settings.OZOW_NOTIFY_URL.strip(),
            "IsTest": "True" if settings.OZOW_IS_TEST else "False",
        }

        # 🔐 HASH (STRICT ORDER)
        hash_string = (
            data["SiteCode"]
            + data["CountryCode"]
            + data["CurrencyCode"]
            + data["Amount"]
            + data["TransactionReference"]
            + data["BankReference"]
            + data["CancelUrl"]
            + data["ErrorUrl"]
            + data["SuccessUrl"]
            + data["NotifyUrl"]
            + data["IsTest"]
        )

        data["HashCheck"] = generate_ozow_hash(hash_string)

        return data