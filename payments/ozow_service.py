import requests
from django.conf import settings
from .ozow_hash import generate_ozow_hash


def create_payment_request(invoice, user):

    amount = f"{invoice.amount_due:.2f}"

    transaction_reference = f"INV-{invoice.id}"
    bank_reference = f"INV-{invoice.id}"

    customer_email = user.email

    hash_value = generate_ozow_hash(
        settings.OZOW_SITE_CODE,
        settings.OZOW_COUNTRY_CODE,
        settings.OZOW_CURRENCY_CODE,
        amount,
        transaction_reference,
        bank_reference,
        customer_email,
        settings.OZOW_SUCCESS_URL,
        settings.OZOW_CANCEL_URL,
        settings.OZOW_ERROR_URL,
        settings.OZOW_NOTIFY_URL,
        settings.OZOW_PRIVATE_KEY,
    )

    payload = {
        "siteCode": settings.OZOW_SITE_CODE,
        "countryCode": settings.OZOW_COUNTRY_CODE,
        "currencyCode": settings.OZOW_CURRENCY_CODE,
        "amount": amount,
        "transactionReference": transaction_reference,
        "bankReference": bank_reference,
        "customerEmail": customer_email,
        "successUrl": settings.OZOW_SUCCESS_URL,
        "cancelUrl": settings.OZOW_CANCEL_URL,
        "errorUrl": settings.OZOW_ERROR_URL,
        "notifyUrl": settings.OZOW_NOTIFY_URL,
        "optional1": str(invoice.id),
        "hashCheck": hash_value,
    }

    headers = {
        "Content-Type": "application/json",
        "ApiKey": settings.OZOW_API_KEY
    }

    response = requests.post(
        settings.OZOW_API_URL,
        json=payload,
        headers=headers,
        timeout=30
    )

    return response.json()