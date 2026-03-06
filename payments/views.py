import requests
from django.conf import settings
from django.shortcuts import redirect, get_object_or_404
from invoices.models import Invoice
from .yoco_service import create_yoco_checkout
from django.http import HttpResponse
import json
from django.views.decorators.csrf import csrf_exempt




def pay_invoice_yoco(request, invoice_id):

    invoice = get_object_or_404(Invoice, id=invoice_id)

    checkout = create_yoco_checkout(invoice)

    checkout_url = checkout["redirectUrl"]

    return redirect(checkout_url)

def payment_success(request):
    return HttpResponse("Payment successful")



@csrf_exempt
def yoco_webhook(request):
    """
    Receives webhook notifications from Yoco
    """

    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        data = json.loads(request.body)

        print("=================================")
        print("YOCO WEBHOOK RECEIVED")
        print(data)
        print("=================================")

        event_type = data.get("type")

        # We only care about successful payments
        if event_type == "payment.succeeded":

            payment_data = data.get("data", {})
            metadata = payment_data.get("metadata", {})

            invoice_id = metadata.get("invoice_id")

            if not invoice_id:
                print("No invoice_id in metadata")
                return HttpResponse(status=200)

            try:
                invoice = Invoice.objects.get(id=invoice_id)

                # Prevent duplicate webhook updates
                if invoice.status != "PAID":
                    invoice.status = "PAID"
                    invoice.save()

                    print(f"Invoice {invoice_id} marked as PAID")
                else:
                    print(f"Invoice {invoice_id} already paid")

            except Invoice.DoesNotExist:
                print(f"Invoice {invoice_id} not found")

        return HttpResponse(status=200)

    except Exception as e:
        print("Webhook error:", str(e))
        return HttpResponse(status=400)