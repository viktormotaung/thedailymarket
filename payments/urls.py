from django.urls import path
from .views import pay_invoice, ozow_success, ozow_cancel
from .webhooks import ozow_notify


urlpatterns = [
    path("pay-invoice/<int:invoice_id>/", pay_invoice, name="pay-invoice"),

    path("payment/ozow/success/", ozow_success, name="ozow-success"),
    path("payment/ozow/cancel/", ozow_cancel, name="ozow-cancel"),

    path("payment/ozow/notify/", ozow_notify, name="ozow-notify"),

]