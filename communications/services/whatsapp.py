import requests

from django.conf import settings


WHATSAPP_API_VERSION = "v23.0"


def send_whatsapp_message(to, message):
    """
    Send a simple WhatsApp text message using Meta Cloud API.

    IMPORTANT:
    This free-form text message only works when the customer has already
    opened the 24-hour chat window by messaging your WhatsApp business number.
    """

    url = (
        f"https://graph.facebook.com/"
        f"{WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": message,
        },
    }

    try:
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
                "success": False,
                "status_code": response.status_code,
                "raw_response": response.text,
            }

        print("========== WHATSAPP RESPONSE ==========")
        print("Status:", response.status_code)
        print("Response:", data)
        print("=======================================")

        return data

    except requests.RequestException as e:
        print("========== WHATSAPP ERROR ==========")
        print(str(e))
        print("====================================")

        return {
            "success": False,
            "error": str(e),
        }


def send_quotation_whatsapp(*, to, client_name, quotation_number, amount, link):
    """
    Send quotation link via WhatsApp.
    """

    message = (
        f"Good Day {client_name},\n\n"
        f"Your quotation from The Daily Market is ready.\n\n"
        f"Quotation: {quotation_number}\n"
        f"Amount: R{amount}\n\n"
        f"View/download here:\n"
        f"{link}\n\n"
        f"Thank you,\n"
        f"The Daily Market"
    )

    return send_whatsapp_message(
        to=to,
        message=message,
    )


def send_invoice_whatsapp(*, to, client_name, invoice_number, amount, link):
    """
    Send invoice link via WhatsApp.
    """

    message = (
        f"Good Day {client_name},\n\n"
        f"Your invoice from The Daily Market is ready.\n\n"
        f"Invoice: {invoice_number}\n"
        f"Amount Due: R{amount}\n\n"
        f"View/download here:\n"
        f"{link}\n\n"
        f"Thank you,\n"
        f"The Daily Market"
    )

    return send_whatsapp_message(
        to=to,
        message=message,
    )


def send_delivery_note_whatsapp(*, to, client_name, delivery_note_number, link):
    """
    Send delivery note link via WhatsApp.
    """

    message = (
        f"Good Day {client_name},\n\n"
        f"Your delivery note from The Daily Market is ready.\n\n"
        f"Delivery Note: {delivery_note_number}\n\n"
        f"View/download here:\n"
        f"{link}\n\n"
        f"Thank you,\n"
        f"The Daily Market"
    )

    return send_whatsapp_message(
        to=to,
        message=message,
    )


def send_invoice_payment_request_whatsapp(
    to,
    client_name,
    invoice_number,
    amount,
    link,
):
    message = (
        f"Hi {client_name},\n\n"
        f"This is a payment request/reminder for {invoice_number}.\n\n"
        f"Amount due: R{amount}\n\n"
        f"Please use the link below to view the invoice and make payment via Ozow:\n"
        f"{link}\n\n"
        f"If payment has already been made, please ignore this message.\n\n"
        f"Thank you,\n"
        f"The Daily Market"
    )

    return send_whatsapp_message(
        to=to,
        message=message,
    )


