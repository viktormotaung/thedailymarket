import requests
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt


def create_yoco_checkout(invoice):
    """
    Creates a Yoco checkout session for an invoice
    and returns the checkout response.
    """

    # Dynamic redirect URLs (return customer to the invoice page)
    success_url = f"https://www.thedailymarket.co.za/invoice/{invoice.id}/"
    cancel_url = f"https://www.thedailymarket.co.za/invoice/{invoice.id}/"

    # Request headers
    headers = {
        "Authorization": f"Bearer {settings.YOCO_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    # Yoco expects amount in cents
    amount_in_cents = int(invoice.deposit_required * 100)

    payload = {
        "amount": amount_in_cents,
        "currency": "ZAR",
        "successUrl": success_url,
        "cancelUrl": cancel_url,
        "metadata": {
            "invoice_id": invoice.id,
            "invoice_number": f"INV{invoice.id}",
            "client": str(invoice.client),
        }
    }

    try:
        response = requests.post(
            settings.YOCO_API_URL,
            json=payload,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        # Debugging (can remove later)
        print("YOCO CHECKOUT CREATED")
        print(data)

        return data

    except requests.exceptions.RequestException as e:
        print("YOCO CHECKOUT ERROR")
        print(e)

        return {
            "error": "Failed to create Yoco checkout",
            "details": str(e)
        }
    



@csrf_exempt
def yoco_webhook(request):

    data = json.loads(request.body)

    print("YOCO WEBHOOK RECEIVED")
    print(data)

    # Example webhook event
    if data.get("type") == "payment.succeeded":

        metadata = data["data"]["metadata"]

        invoice_id = metadata.get("invoice_id")

        try:
            invoice = Invoice.objects.get(id=invoice_id)

            invoice.status = "paid"
            invoice.save()

            print(f"Invoice {invoice_id} marked as PAID")

        except Invoice.DoesNotExist:
            print("Invoice not found")

    return HttpResponse(status=200)