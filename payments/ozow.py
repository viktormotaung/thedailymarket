import hashlib

def generate_ozow_hash(
    site_code,
    country_code,
    currency_code,
    amount,
    transaction_reference,
    bank_reference,
    optional1,
    customer_email,
    cancel_url,
    error_url,
    success_url,
    notify_url,
    private_key,
):

    hash_string = (
        site_code
        + country_code
        + currency_code
        + amount
        + transaction_reference
        + bank_reference
        + optional1
        + customer_email
        + cancel_url
        + error_url
        + success_url
        + notify_url
        + private_key
    )

    print("OZOW HASH STRING:", hash_string)

    hash_value = hashlib.sha512(hash_string.encode("utf-8")).hexdigest()

    print("OZOW HASH:", hash_value)

    return hash_value