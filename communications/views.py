from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

from django.conf import settings


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

            # later:
            # - save delivery status
            # - save read status
            # - save inbound messages
            # - update CommunicationLog

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