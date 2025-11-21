from django.urls import path
from . import views

urlpatterns = [
    path("", views.invoice_list, name="staff-invoices"),
    path("new/", views.invoice_create, name="invoice-create"),
    path("<int:pk>/edit/", views.invoice_edit, name="invoice-edit"),
    path("<int:pk>/view/", views.invoice_view, name="invoice-view"),
    path("<int:pk>/download/", views.invoice_download, name="invoice-download"),
]
