from django.urls import path
from . import views

urlpatterns = [
    path("", views.membership_dashboard, name="membership_dashboard"),

    path("shop/", views.membership_shop, name="membership_shop"),

    path("orders/", views.membership_orders, name="membership_orders"),

    path("membership/", views.membership_membership, name="membership_membership"),

    path("account/", views.membership_account, name="membership_account"),

    path("support/", views.membership_support, name="membership_support"),
]