from django.urls import path
from . import views

app_name = "online_payments"

urlpatterns = [
    path("pay/<int:invoice_id>/", views.start_payment, name="start-payment"),
    path("ozow/notify/", views.ozow_notify, name="ozow-notify"),


    path("success/", views.payment_success, name="payment-success"),
    path("cancel/", views.payment_cancel, name="payment-cancel"),
    path("error/", views.payment_error, name="payment-error"),
    path("oneapi/test-token/", views.test_ozow_oneapi_token, name="test_ozow_oneapi_token"),
    path("oneapi/test-payment-methods/", views.test_ozow_oneapi_payment_methods, name="test_ozow_oneapi_payment_methods",),

    path("oneapi/checkout/<int:invoice_id>/", views.oneapi_checkout_options, name="oneapi_checkout_options"),
    path("oneapi/start/<int:invoice_id>/", views.oneapi_start_payment, name="oneapi_start_payment"),
    path("oneapi/return/", views.oneapi_return, name="oneapi_return"),
    path("oneapi/webhook/", views.oneapi_webhook, name="oneapi_webhook"),
]