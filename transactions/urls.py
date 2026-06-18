from django.urls import path
from . import views
from transactions import views as txviews

urlpatterns = [
    path("", views.transaction_list, name="staff-transactions"),
    path("new/", views.transaction_create, name="transaction-create"),
    path("<int:pk>/edit/", views.transaction_edit, name="transaction-edit"),
    path("<int:pk>/view/", views.transaction_view, name="transaction-view"),
    path("<int:pk>/delete/", views.transaction_delete, name="transaction-delete"),
    path("transactions/ajax/invoices-by-client/", txviews.ajax_invoices_by_client, name="ajax-invoices-by-client"),
    path("dashboard", views.staff_finance_dashboard, name="staff-finance-dashboard"),
]
