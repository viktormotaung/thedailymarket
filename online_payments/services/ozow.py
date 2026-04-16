import hashlib
from django.conf import settings


def generate_ozow_hash(hash_string):
    final_string = hash_string + settings.OZOW_PRIVATE_KEY.strip()

    return hashlib.sha512(final_string.encode("utf-8")).hexdigest().lower()


def verify_ozow_hash(post_data: dict) -> bool:
    """
    Validate Ozow callback hash
    """

    received_hash = post_data.get("HashCheck")

    # IMPORTANT: order matters (Ozow requirement)
    fields = [
        post_data.get("SiteCode", ""),
        post_data.get("TransactionId", ""),
        post_data.get("TransactionReference", ""),
        post_data.get("BankReference", ""),
        post_data.get("Amount", ""),
        post_data.get("Status", ""),
    ]

    hash_string = "".join(fields)
    calculated_hash = generate_ozow_hash(hash_string)

    return calculated_hash == received_hash