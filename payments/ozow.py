import hashlib

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
    private_key,
):

    hash_string = (
        site_code
        + country_code
        + currency_code
        + amount
        + transaction_reference
        + bank_reference
        + customer_email
        + success_url
        + cancel_url
        + error_url
        + notify_url
        + private_key
    )

    hash_value = hashlib.sha512(hash_string.encode("utf-8")).hexdigest()

    print("OZOW HASH STRING:", hash_string)
    print("OZOW HASH:", hash_value)

    return hash_value