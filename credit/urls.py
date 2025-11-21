from django.urls import path
from .views import credit_list, credit_edit, credit_client_view

urlpatterns = [
    path("", credit_list, name="staff-credit"),
    path("client/<int:client_id>/edit/", credit_edit, name="credit-edit"),
    path("client/<int:client_id>/", credit_client_view, name="credit-view"),
]
