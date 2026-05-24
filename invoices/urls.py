from django.urls import path
from . import views

urlpatterns = [
    path("", views.invoice_list, name="staff-invoices"),
    path("new/", views.invoice_create, name="invoice-create"),
    path("<int:pk>/edit/", views.invoice_edit, name="invoice-edit"),
    path("<int:pk>/view/", views.invoice_view, name="invoice-view"),
    path("<int:pk>/download/", views.invoice_download, name="invoice-download"),
    # NEW:
    path(
        "staff/invoices/<int:pk>/send-request/",
        views.invoice_send_payment_request,
        name="invoice-send-request",
    ),
    path(
        "staff/invoices/<int:pk>/confirm-payment/",
        views.invoice_confirm_payment,
        name="invoice-confirm-payment",
    ),

    path("<int:pk>/send-request/", views.send_invoice_payment_request, name="invoice-send-request",),


    path("<int:pk>/send-email/", views.send_invoice_email_internal, name="send-invoice-email-internal",),

    path("<int:pk>/send-whatsapp/", views.send_invoice_whatsapp_view, name="send-invoice-whatsapp",),
    path("public/<uuid:token>/", views.public_invoice_view, name="public-invoice-view",),
    path("<int:pk>/send-sms/", views.send_invoice_sms_view, name="invoice-send-sms",),
    path("<int:pk>/payment-request/sms/", views.send_invoice_payment_request_sms, name="invoice-payment-request-sms",),

    path("<int:pk>/payment-request/email/", views.send_invoice_payment_request_email, name="invoice-payment-request-email",),
]
