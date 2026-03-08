from django.urls import path
from . import views
from .webhooks import yoco_webhook

urlpatterns = [

    # Start payment
    path(
        "yoco/pay/<int:invoice_id>/",
        views.pay_invoice_yoco,
        name="pay_invoice_yoco",
    ),

    # Customer return pages
    path(
        "payment-success/",
        views.payment_success,
        name="payment_success",
    ),

    path(
        "payment-cancel/",
        views.payment_cancel,
        name="payment_cancel",
    ),

    path(
        "payment-error/",
        views.payment_error,
        name="payment_error",
    ),

    # Yoco webhook (MOST IMPORTANT)
    path(
        "yoco/webhook/",
        yoco_webhook,
        name="yoco_webhook",
    ),
]