from django.urls import path
from .views import (
    credit_list,
    credit_edit,
    credit_client_view,
    credit_record_repayment, credit_confirm_payment, credit_send_request, funders_list, funder_view,
)


urlpatterns = [
    path("", credit_list, name="staff-credit"),
    path("client/<int:client_id>/edit/", credit_edit, name="credit-edit"),
    path("client/<int:client_id>/", credit_client_view, name="credit-view"),

    path("client/<int:client_id>/repay/", credit_record_repayment, name="credit-record-repayment",),

    path("credit/<int:client_id>/send-request/", credit_send_request, name="credit-send-request"),
    path("credit/<int:client_id>/confirm-payment/", credit_confirm_payment, name="credit-confirm-payment"),

    path("funders/", funders_list, name="funder-list",),  

    path("funders/<int:funder_id>/", funder_view, name="funder-view",),


]
