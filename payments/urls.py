from django.urls import path
from . import views

urlpatterns = [
    path("invoice/<int:invoice_id>/pay/", views.pay_invoice, name="pay_invoice"),
    path("payments/ozow/notify/", views.ozow_notify, name="ozow_notify"),
]