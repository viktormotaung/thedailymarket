from django.urls import path
from . import views

urlpatterns = [
    path("", views.membership_dashboard, name="membership_dashboard"),

    path("shop/", views.membership_shop, name="membership_shop"),

    path("orders/", views.membership_orders, name="membership_orders"),

    path("membership/", views.membership_membership, name="membership_membership"),

    path("account/", views.membership_account, name="membership_account"),

    path("shop/specials/", views.membership_shop_specials, name="membership_shop_specials",),

    path("support/", views.membership_support, name="membership_support"),

    path("shop/<slug:slug>/", views.membership_shop_category, name="membership_shop_category",),

    path("download-price-list/", views.membership_download_price_list, name="membership_download_price_list",),

    path("orders/<int:order_id>/", views.membership_view_order, name="membership_view_order",),

    path("invoice/<int:invoice_id>/", views.membership_view_invoice, name="membership_view_invoice",),

    
]