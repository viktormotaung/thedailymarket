from django.urls import path
from . import views

urlpatterns = [
    path(
        "yoco/pay/<int:invoice_id>/",
        views.pay_invoice_yoco,
        name="pay_invoice_yoco",
    ),
    
   
    path("yoco/webhook/", views.yoco_webhook, name="yoco-webhook"),
   


]