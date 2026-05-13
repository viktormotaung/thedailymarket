import requests

from django.conf import settings


WHATSAPP_API_VERSION = "v23.0"


def send_whatsapp_template(
    to,
    template_name,
    language_code="en",
    body_parameters=None,
):
    """
    Send WhatsApp template message using Meta Cloud API.
    """

    body_parameters = body_parameters or []

    url = (
        f"https://graph.facebook.com/"
        f"{WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    parameters = [
        {
            "type": "text",
            "text": str(value),
        }
        for value in body_parameters
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code,
            },
            "components": [
                {
                    "type": "body",
                    "parameters": parameters,
                }
            ],
        },
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30,
    )

    try:
        data = response.json()
    except ValueError:
        data = {
            "error": {
                "message": response.text,
            }
        }

    print("========== WHATSAPP TEMPLATE RESPONSE ==========")
    print("Status:", response.status_code)
    print("Response:", data)
    print("================================================")

    return data