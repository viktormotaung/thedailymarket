from django.urls import path
from . import views

app_name = "online_payments"

urlpatterns = [
    path("pay/<int:invoice_id>/", views.start_payment, name="start-payment"),
    path("ozow/notify/", views.ozow_notify, name="ozow-notify"),


    path("success/", views.payment_success, name="payment-success"),
    path("cancel/", views.payment_cancel, name="payment-cancel"),
    path("error/", views.payment_error, name="payment-error"),
]