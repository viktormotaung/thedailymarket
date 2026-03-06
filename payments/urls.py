from django.urls import path
from .views import pay_invoice_yoco, yoco_webhook

urlpatterns = [
    path(
        "yoco/pay/<int:invoice_id>/",
        pay_invoice_yoco,
        name="pay_invoice_yoco",
    ),
    
   
    path("yoco/webhook/", yoco_webhook, name="yoco-webhook"),

]