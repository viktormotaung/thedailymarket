import hashlib
from django.conf import settings


def generate_ozow_hash(hash_string):
    final_string = (hash_string + settings.OZOW_PRIVATE_KEY.strip()).lower()
    return hashlib.sha512(final_string.encode("utf-8")).hexdigest()

def verify_ozow_hash(post_data: dict) -> bool:
    received_hash = (post_data.get("HashCheck") or "").lower()

    required_fields = [
        "SiteCode",
        "TransactionId",
        "TransactionReference",
        "BankReference",
        "Amount",
        "Status",
    ]

    # Ensure all required fields exist
    for field in required_fields:
        if field not in post_data:
            print(f"Missing field in Ozow callback: {field}")
            return False

    hash_string = (
        post_data["SiteCode"]
        + post_data["TransactionId"]
        + post_data["TransactionReference"]
        + post_data["BankReference"]
        + post_data["Amount"]
        + post_data["Status"]
    )

    calculated_hash = generate_ozow_hash(hash_string)

    print("=== OZOW VERIFY DEBUG ===")
    print("HASH STRING:", hash_string)
    print("CALCULATED:", calculated_hash)
    print("RECEIVED:", received_hash)
    print("=========================")

    return calculated_hash == received_hash