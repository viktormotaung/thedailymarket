import base64

import requests
from django.conf import settings
from django.utils import timezone

from communications.models import CommunicationLog


SMSPORTAL_SEND_URL = "https://rest.smsportal.com/v1/bulkmessages"


def normalize_sa_mobile(number):
    number = (number or "").strip()
    number = number.replace("+", "").replace(" ", "").replace("-", "")

    if number.startswith("0"):
        number = "27" + number[1:]

    return number


def send_sms(to, message, client=None, sent_by=None):
    """
    Send an SMS through SMSPortal and log the communication.

    Optional:
        client   - Client instance related to the SMS.
        sent_by  - User who initiated the SMS.

    Returns:
        Dictionary containing the SMSPortal result.
    """

    client_id = settings.SMSPORTAL_CLIENT_ID
    api_secret = settings.SMSPORTAL_API_SECRET

    to = normalize_sa_mobile(to)

    # --------------------------------------------------
    # Determine recipient name
    # --------------------------------------------------

    recipient_name = None

    if client:
        if client.contact_person:
            recipient_name = client.contact_person.strip()
        elif client.name:
            recipient_name = client.name.strip()

    # --------------------------------------------------
    # Create initial communication log
    # --------------------------------------------------

    communication_log = CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_SMS,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=recipient_name,
        recipient_contact=to,
        message=message,

        # Customer-facing SMS communications are linked
        # to the Client that received the message.
        related_model="Client" if client else None,
        related_object_id=client.pk if client else None,

        provider="SMSPortal",
        sent_by=sent_by,
    )

    # --------------------------------------------------
    # Validate mobile number
    # --------------------------------------------------

    if not to:
        error_message = "No mobile number supplied."

        communication_log.status = CommunicationLog.STATUS_FAILED
        communication_log.error_message = error_message
        communication_log.failed_at = timezone.now()

        communication_log.save(
            update_fields=[
                "status",
                "error_message",
                "failed_at",
                "updated_at",
            ]
        )

        return {
            "success": False,
            "status_code": None,
            "response": {
                "error": error_message,
            },
            "to": to,
            "message": message,
            "communication_log_id": communication_log.pk,
        }

    # --------------------------------------------------
    # Build SMSPortal authentication
    # --------------------------------------------------

    credentials = f"{client_id}:{api_secret}"

    encoded_credentials = base64.b64encode(
        credentials.encode()
    ).decode()

    # --------------------------------------------------
    # SMSPortal payload
    # --------------------------------------------------

    payload = {
        "messages": [
            {
                "content": message,
                "destination": to,
            }
        ]
    }

    # --------------------------------------------------
    # Send SMS
    # --------------------------------------------------

    try:
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

    except requests.RequestException as exc:
        error_message = str(exc)

        communication_log.status = CommunicationLog.STATUS_FAILED
        communication_log.error_message = error_message
        communication_log.failed_at = timezone.now()

        communication_log.save(
            update_fields=[
                "status",
                "error_message",
                "failed_at",
                "updated_at",
            ]
        )

        return {
            "success": False,
            "status_code": None,
            "response": {
                "error": error_message,
            },
            "to": to,
            "message": message,
            "communication_log_id": communication_log.pk,
        }

    # --------------------------------------------------
    # Parse SMSPortal response
    # --------------------------------------------------

    try:
        data = response.json()

    except Exception:
        data = {
            "raw": response.text,
        }

    success = response.status_code in [200, 201]

    # --------------------------------------------------
    # Extract provider message ID if available
    # --------------------------------------------------

    provider_message_id = None

    if isinstance(data, dict):

        # Possible direct message ID
        provider_message_id = (
            data.get("messageId")
            or data.get("message_id")
            or data.get("id")
        )

        # SMSPortal may return messages in a list
        if not provider_message_id:

            messages = data.get("messages")

            if isinstance(messages, list) and messages:

                first_message = messages[0]

                if isinstance(first_message, dict):
                    provider_message_id = (
                        first_message.get("messageId")
                        or first_message.get("message_id")
                        or first_message.get("id")
                    )

    # --------------------------------------------------
    # Update communication log
    # --------------------------------------------------

    communication_log.status = (
        CommunicationLog.STATUS_SENT
        if success
        else CommunicationLog.STATUS_FAILED
    )

    communication_log.provider_response = data

    if provider_message_id:
        communication_log.provider_message_id = str(
            provider_message_id
        )

    if success:
        communication_log.sent_at = timezone.now()
        communication_log.error_message = None

    else:
        communication_log.error_message = (
            f"SMSPortal returned HTTP {response.status_code}"
        )
        communication_log.failed_at = timezone.now()

    communication_log.save(
        update_fields=[
            "status",
            "provider_response",
            "provider_message_id",
            "sent_at",
            "error_message",
            "failed_at",
            "updated_at",
        ]
    )

    # --------------------------------------------------
    # Return result
    # --------------------------------------------------

    return {
        "success": success,
        "status_code": response.status_code,
        "response": data,
        "to": to,
        "message": message,
        "communication_log_id": communication_log.pk,
    }
