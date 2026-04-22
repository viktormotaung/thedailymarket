from django.urls import path

from . import views

app_name = "online_payments"

urlpatterns = [
    # Ozow Legacy
    path("pay/<int:invoice_id>/", views.start_payment, name="start-payment"),
    path("ozow/notify/", views.ozow_notify, name="ozow-notify"),
    path("success/", views.payment_success, name="payment-success"),
    path("cancel/", views.payment_cancel, name="payment-cancel"),
    path("error/", views.payment_error, name="payment-error"),

    # Yoco
    path("yoco/checkout/<int:invoice_id>/", views.yoco_checkout, name="yoco_checkout"),
    path("yoco/webhook/", views.yoco_webhook, name="yoco_webhook"),
    path("yoco/success/", views.yoco_success, name="yoco_success"),
    path("yoco/cancel/", views.yoco_cancel, name="yoco_cancel"),
    path("yoco/test/", views.test_yoco_connection, name="test_yoco_connection"),
]