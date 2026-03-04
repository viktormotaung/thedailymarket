import hashlib
from django.conf import settings


def generate_ozow_hash(
    site_code,
    country_code,
    currency_code,
    amount,
    transaction_reference,
    bank_reference,
    customer_email,
    success_url,
    cancel_url,
    error_url,
    notify_url,
    private_key
):
    hash_string = (
        f"{site_code}"
        f"{country_code}"
        f"{currency_code}"
        f"{amount}"
        f"{transaction_reference}"
        f"{bank_reference}"
        f"{customer_email}"
        f"{success_url}"
        f"{cancel_url}"
        f"{error_url}"
        f"{notify_url}"
        f"{private_key}"
    )

    return hashlib.sha512(hash_string.encode("utf-8")).hexdigest()