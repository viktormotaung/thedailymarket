import base64
import requests
from django.conf import settings


SMSPORTAL_SEND_URL = "https://rest.smsportal.com/v1/bulkmessages"


def normalize_sa_mobile(number):
    number = (number or "").strip()
    number = number.replace("+", "").replace(" ", "").replace("-", "")

    if number.startswith("0"):
        number = "27" + number[1:]

    return number


def send_sms(to, message):
    client_id = settings.SMSPORTAL_CLIENT_ID
    api_secret = settings.SMSPORTAL_API_SECRET

    to = normalize_sa_mobile(to)

    credentials = f"{client_id}:{api_secret}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    payload = {
        "messages": [
            {
                "content": message,
                "destination": to,
            }
        ]
    }

    response = requests.post(
        SMSPORTAL_SEND_URL,
        json=payload,
        headers={
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    return {
        "success": response.status_code in [200, 201],
        "status_code": response.status_code,
        "response": data,
        "to": to,
        "message": message,
    }