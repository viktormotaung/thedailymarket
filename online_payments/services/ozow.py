import hashlib
from django.conf import settings


def generate_ozow_hash(hash_string):
    final_string = (hash_string + settings.OZOW_PRIVATE_KEY.strip()).lower()
    return hashlib.sha512(final_string.encode("utf-8")).hexdigest()

def verify_ozow_hash(post_data):
    received_hash = (post_data.get("Hash") or "").lower()

    # Helper to safely get values
    def get(key):
        return (post_data.get(key) or [""])[0]

    hash_string = (
        get("SiteCode")
        + get("TransactionId")
        + get("TransactionReference")
        + get("Amount")
        + get("Status")
        + get("Optional1")
        + get("Optional2")
        + get("Optional3")
        + get("Optional4")
        + get("Optional5")
        + get("CurrencyCode")
        + get("IsTest")
    )

    calculated_hash = generate_ozow_hash(hash_string)

    print("=== OZOW CALLBACK FINAL DEBUG ===")
    print("HASH STRING:", hash_string)
    print("CALCULATED:", calculated_hash)
    print("RECEIVED:", received_hash)
    print("================================")

    return calculated_hash == received_hash