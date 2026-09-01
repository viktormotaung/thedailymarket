import requests


from communications.services.whatsapp_templates import send_whatsapp_template

from django.conf import settings
from twilio.rest import Client


def send_whatsapp_message(to, message):
    """
    Send a WhatsApp text message through Twilio.

    Accepts South African numbers in either:
        0723904202
        +27723904202
        whatsapp:+27723904202
    """

    if not to:
        return {
            "success": False,
            "message": "No WhatsApp number supplied.",
        }

    to = str(to).strip()

    # Remove whatsapp: prefix if already supplied
    if to.lower().startswith("whatsapp:"):
        to = to[9:]

    # Remove spaces, brackets and hyphens
    to = (
        to.replace(" ", "")
          .replace("-", "")
          .replace("(", "")
          .replace(")", "")
    )

    # Convert South African local format:
    # 0723904202 → +27723904202
    if to.startswith("0") and len(to) == 10:
        to = "+27" + to[1:]

    # Add WhatsApp prefix
    to = f"whatsapp:{to}"

    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
    )

    result = client.messages.create(
        from_=settings.TWILIO_WHATSAPP_FROM,
        to=to,
        body=message,
    )

    return {
        "success": True,
        "sid": result.sid,
        "status": result.status,
        "to": to,
    }


WHATSAPP_API_VERSION = "v23.0"


def send_client_activation_whatsapp(client):
    """
    Send the welcome WhatsApp message when a Client becomes ACTIVE.
    """

    if not client.whatsapp:
        return {
            "success": False,
            "message": "Client has no WhatsApp number.",
        }

    customer_name = (
        client.contact_person.strip()
        if client.contact_person
        else client.name.strip()
    )

    message = (
        f"Welcome to The Daily Market! 👋\n\n"
        f"Dear {customer_name},\n\n"
        f"Your customer profile is now active.\n\n"
        f"Customer Code: {client.client_number}\n\n"
        f"You can now trade with The Daily Market.\n\n"
        f"Please contact your Area Representative to place orders "
        f"or enquire about products.\n\n"
        f"Thank you for choosing The Daily Market."
    )

    return send_whatsapp_message(
        client.whatsapp,
        message,
    )

def send_quotation_whatsapp(
    to,
    client_name,
    quotation_number,
    amount,
    link,
    quotation=None,
):
    return send_whatsapp_template(
        to=to,
        template_name="quotation_delivery",
        body_parameters=[
            client_name,
            str(quotation_number).replace("QT-", ""),
            f"{amount}",
            link,
        ],
        message_type="quotation",
        quotation=quotation,
    )



def send_invoice_whatsapp(
    to,
    client_name,
    invoice_number,
    amount,
    link,
    invoice=None,
):
    return send_whatsapp_template(
        to=to,
        template_name="invoice_delivery",
        body_parameters=[
            client_name,
            str(invoice_number).replace("INV-", ""),
            f"{amount}",
            link,
        ],
        message_type="invoice",
        invoice=invoice,
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
    invoice=None,
):
    return send_whatsapp_template(
        to=to,
        template_name="payment_reminder",
        body_parameters=[
            client_name,
            str(invoice_number).replace("INV-", ""),
            f"{amount}",
            link,
        ],
        message_type="payment_reminder",
        invoice=invoice,
    )


