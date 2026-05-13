import requests

from django.conf import settings

from communications.models import WhatsAppMessage


WHATSAPP_API_VERSION = "v23.0"


def send_whatsapp_template(
    *,
    to,
    template_name,
    language_code="en",
    body_parameters=None,
    message_type=None,
    quotation=None,
    invoice=None,
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

    # ==========================================
    # CREATE WHATSAPP LOG
    # ==========================================

    whatsapp_message_id = None

    messages = data.get("messages") or []

    if messages:
        whatsapp_message_id = messages[0].get("id")

    status = (
        "sent"
        if response.status_code == 200
        else "failed"
    )

    WhatsAppMessage.objects.create(
        recipient=to,
        template_name=template_name,
        message_type=message_type or "invoice",
        status=status,
        whatsapp_message_id=whatsapp_message_id,
        response_payload=data,
        quotation=quotation,
        invoice=invoice,
    )

    return data