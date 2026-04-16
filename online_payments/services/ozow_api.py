import requests
from django.conf import settings


def get_ozow_transaction(transaction_id):
    url = f"{settings.OZOW_API_URL}/GetTransaction"

    params = {
        "siteCode": settings.OZOW_SITE_CODE,
        "transactionId": transaction_id,
        "isTest": "true" if settings.OZOW_IS_TEST else "false",
    }

    headers = {
        "ApiKey": settings.OZOW_API_KEY,
    }

    response = requests.get(url, params=params, headers=headers)

    print("=== OZOW API RESPONSE ===")
    print(response.status_code)
    print(response.text)
    print("=========================")

    if response.status_code == 200:
        return response.json()

    return None