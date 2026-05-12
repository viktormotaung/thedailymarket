import json
from datetime import datetime

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import CommunicationLog


def unix_to_aware_datetime(timestamp_value):
    """
    Convert Meta timestamp string to timezone-aware datetime.
    """
    if not timestamp_value:
        return timezone.now()

    try:
        return timezone.make_aware(
            datetime.fromtimestamp(int(timestamp_value))
        )
    except Exception:
        return timezone.now()


def update_communication_log_from_status(
    status_payload,
    metadata=None,
):
    """
    Update CommunicationLog from WhatsApp status webhook.

    Meta sends status payloads like:
    {
        "id": "wamid...",
        "status": "delivered",
        "timestamp": "1778595295",
        "recipient_id": "27723904202",
        "pricing": {...}
    }
    """

    metadata = metadata or {}

    message_id = status_payload.get("id")
    status = status_payload.get("status")
    timestamp_value = status_payload.get("timestamp")

    if not message_id or not status:
        return

    log = CommunicationLog.objects.filter(
        provider_message_id=message_id
    ).first()

    if not log:
        print("No CommunicationLog found for message id:", message_id)
        return

    event_time = unix_to_aware_datetime(timestamp_value)

    log.provider_status_payload = status_payload

    log.whatsapp_phone_number_id = metadata.get("phone_number_id")
    log.whatsapp_display_phone_number = metadata.get("display_phone_number")
    log.whatsapp_recipient_id = status_payload.get("recipient_id")

    pricing = status_payload.get("pricing") or {}
    log.whatsapp_pricing_category = pricing.get("category")
    log.whatsapp_pricing_type = pricing.get("type")
    log.whatsapp_billable = pricing.get("billable")

    conversation = status_payload.get("conversation") or {}
    log.whatsapp_conversation_id = conversation.get("id")

    if status == "sent":
        log.status = CommunicationLog.STATUS_SENT
        if not log.sent_at:
            log.sent_at = event_time

    elif status == "delivered":
        log.status = CommunicationLog.STATUS_DELIVERED
        log.delivered_at = event_time

    elif status == "read":
        log.status = CommunicationLog.STATUS_READ
        log.read_at = event_time

    elif status == "failed":
        log.status = CommunicationLog.STATUS_FAILED
        log.failed_at = event_time

        errors = status_payload.get("errors") or []
        if errors:
            first_error = errors[0]
            log.error_message = (
                first_error.get("title")
                or first_error.get("message")
                or str(first_error)
            )
        else:
            log.error_message = "WhatsApp message failed."

    log.save(
        update_fields=[
            "status",
            "provider_status_payload",
            "whatsapp_phone_number_id",
            "whatsapp_display_phone_number",
            "whatsapp_recipient_id",
            "whatsapp_conversation_id",
            "whatsapp_pricing_category",
            "whatsapp_pricing_type",
            "whatsapp_billable",
            "sent_at",
            "delivered_at",
            "read_at",
            "failed_at",
            "error_message",
            "updated_at",
        ]
    )

    print(
        "Updated CommunicationLog:",
        log.id,
        message_id,
        status,
    )


def handle_incoming_whatsapp_message(
    message_payload,
    metadata=None,
    contacts=None,
):
    """
    Store incoming WhatsApp replies/messages.
    This creates a CommunicationLog entry for inbound messages.

    Meta sends message payloads like:
    {
        "from": "27723904202",
        "id": "wamid...",
        "timestamp": "...",
        "type": "text",
        "text": {"body": "Hi"}
    }
    """

    metadata = metadata or {}
    contacts = contacts or []

    message_id = message_payload.get("id")
    from_number = message_payload.get("from")
    timestamp_value = message_payload.get("timestamp")
    message_type = message_payload.get("type")

    if not message_id or not from_number:
        return

    existing = CommunicationLog.objects.filter(
        provider_message_id=message_id
    ).first()

    if existing:
        return

    message_text = ""

    if message_type == "text":
        message_text = (
            message_payload.get("text", {})
            .get("body", "")
        )

    elif message_type == "button":
        message_text = (
            message_payload.get("button", {})
            .get("text", "")
        )

    elif message_type == "interactive":
        interactive = message_payload.get("interactive") or {}
        message_text = json.dumps(interactive)

    else:
        message_text = f"Incoming WhatsApp message type: {message_type}"

    contact_name = None

    if contacts:
        profile = contacts[0].get("profile") or {}
        contact_name = profile.get("name")

    event_time = unix_to_aware_datetime(timestamp_value)

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_WHATSAPP,
        status=CommunicationLog.STATUS_READ,
        recipient_name=contact_name,
        recipient_contact=from_number,
        subject="Incoming WhatsApp Message",
        message=message_text,
        related_model=None,
        related_object_id=None,
        provider="Meta WhatsApp Cloud API",
        provider_message_id=message_id,
        provider_response=message_payload,
        provider_status_payload=message_payload,
        whatsapp_phone_number_id=metadata.get("phone_number_id"),
        whatsapp_display_phone_number=metadata.get("display_phone_number"),
        whatsapp_recipient_id=from_number,
        sent_at=event_time,
        delivered_at=event_time,
        read_at=event_time,
    )

    print(
        "Created inbound CommunicationLog:",
        from_number,
        message_type,
    )


@csrf_exempt
def whatsapp_webhook(request):

    # ==========================================
    # META WEBHOOK VERIFICATION
    # ==========================================

    if request.method == "GET":

        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if (
            mode == "subscribe"
            and token == settings.WHATSAPP_VERIFY_TOKEN
        ):
            return HttpResponse(challenge)

        return HttpResponse("Verification failed", status=403)

    # ==========================================
    # RECEIVE EVENTS
    # ==========================================

    if request.method == "POST":

        try:
            data = json.loads(request.body)

            print("========== WHATSAPP WEBHOOK ==========")
            print(json.dumps(data, indent=2))
            print("======================================")

            entries = data.get("entry", [])

            for entry in entries:
                changes = entry.get("changes", [])

                for change in changes:
                    value = change.get("value", {})
                    metadata = value.get("metadata", {})
                    contacts = value.get("contacts", [])

                    statuses = value.get("statuses", [])
                    messages = value.get("messages", [])

                    # ------------------------------------------
                    # OUTGOING MESSAGE STATUS UPDATES
                    # sent / delivered / read / failed
                    # ------------------------------------------
                    for status_payload in statuses:
                        update_communication_log_from_status(
                            status_payload=status_payload,
                            metadata=metadata,
                        )

                    # ------------------------------------------
                    # INCOMING CUSTOMER MESSAGES
                    # ------------------------------------------
                    for message_payload in messages:
                        handle_incoming_whatsapp_message(
                            message_payload=message_payload,
                            metadata=metadata,
                            contacts=contacts,
                        )

            return JsonResponse(
                {"status": "received"},
                status=200
            )

        except Exception as e:

            print("WEBHOOK ERROR:", str(e))

            return JsonResponse(
                {"error": str(e)},
                status=400
            )

    return HttpResponse(status=405)