# lender/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.funder_dashboard, name="funder-dashboard"),
    path("top-up/", views.top_up, name="top-up"),
    path("withdraw/", views.withdraw, name="withdraw"),

    # PayFast return/cancel/notify endpoints
    path("payfast/return/", views.payfast_return, name="payfast-return"),
    path("payfast/cancel/", views.payfast_cancel, name="payfast-cancel"),
    path("payfast/notify/", views.payfast_notify, name="payfast-notify"),
]
