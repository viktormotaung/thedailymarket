import requests
from django.conf import settings
from django.shortcuts import redirect, get_object_or_404
from django.http import HttpResponse

from invoices.models import Invoice
from .yoco_service import create_yoco_checkout


def pay_invoice_yoco(request, invoice_id):
    """
    Redirects the user to the Yoco checkout page
    """

    invoice = get_object_or_404(Invoice, id=invoice_id)

    print("=================================")
    print("CREATING YOCO CHECKOUT")
    print("Invoice:", invoice.id)
    print("Client:", invoice.client)
    print("Amount:", invoice.deposit_required)
    print("=================================")

    checkout = create_yoco_checkout(invoice)

    print("YOCO CHECKOUT CREATED")
    print(checkout)

    checkout_url = checkout.get("redirectUrl")

    if not checkout_url:
        print("❌ No redirect URL returned from Yoco")
        return HttpResponse("Failed to create checkout", status=500)

    return redirect(checkout_url)


def payment_success(request):
    """
    Customer returned from Yoco after successful payment
    NOTE: Invoice status is NOT updated here.
    Webhook handles the real payment confirmation.
    """

    print("=================================")
    print("YOCO SUCCESS REDIRECT")
    print("Customer returned from payment page")
    print("=================================")

    return HttpResponse("Payment successful. Your payment is being processed.")


def payment_cancel(request):
    """
    Customer cancelled payment
    """

    print("=================================")
    print("YOCO PAYMENT CANCELLED")
    print("Customer cancelled payment")
    print("=================================")

    return HttpResponse("Payment cancelled.")


def payment_error(request):
    """
    Payment error page
    """

    print("=================================")
    print("YOCO PAYMENT ERROR")
    print("Something went wrong during payment")
    print("=================================")

    return HttpResponse("Payment error occurred.")

