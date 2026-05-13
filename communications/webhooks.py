import json

from django.conf import settings
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from communications.models import WhatsAppMessage


@csrf_exempt
def whatsapp_webhook(request):

    # ==================================================
    # VERIFY WEBHOOK
    # ==================================================

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

    # ==================================================
    # RECEIVE EVENTS
    # ==================================================

    if request.method == "POST":

        try:
            body = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse(
                {"success": False, "error": "Invalid JSON"},
                status=400,
            )

        try:
            entries = body.get("entry", [])

            for entry in entries:

                changes = entry.get("changes", [])

                for change in changes:

                    value = change.get("value", {})

                    statuses = value.get("statuses", [])

                    for status_data in statuses:

                        whatsapp_message_id = status_data.get("id")

                        status = status_data.get("status")

                        if not whatsapp_message_id:
                            continue

                        try:
                            message = WhatsAppMessage.objects.get(
                                whatsapp_message_id=whatsapp_message_id
                            )

                            # ==================================
                            # UPDATE STATUS
                            # ==================================

                            if status == "sent":
                                message.status = "sent"

                            elif status == "delivered":
                                message.status = "delivered"

                            elif status == "read":
                                message.status = "read"

                            elif status == "failed":
                                message.status = "failed"

                            message.response_payload = body

                            message.save(
                                update_fields=[
                                    "status",
                                    "response_payload",
                                    "updated_at",
                                ]
                            )

                        except WhatsAppMessage.DoesNotExist:
                            pass

        except Exception as e:
            print("WHATSAPP WEBHOOK ERROR:", str(e))

        return JsonResponse({"success": True})

    return JsonResponse(
        {"success": False},
        status=405,
    )