# home/urls.py
from django.urls import path
from . import views
from django.conf.urls.static import static

urlpatterns = [
    path("", views.home, name="home"),

    # Static pages
    path("about/", views.about, name="about"),

    # Auth
    path("portal/staff/login/", views.staff_login, name="staff-login"),
    path("portal/client/login/", views.ClientLoginView.as_view(), name="client-login"),
    path("register_profile/", views.register_profile, name="register-profile"),
    path("logout/", views.logout_view, name="logout"),
    path("portal/consumer/login/", views.consumer_login, name="consumer-login"),

    # Dashboards
    path("portal/client/", views.client_dashboard, name="client-dashboard"),

    # Client tabs
    path("products/", views.products, name="products"),
    path("products/<slug:slug>/", views.product_detail, name="product-detail"),
    path("orders/", views.orders, name="orders"),
    path("cart/", views.cart, name="cart"),
    path("wholesale_assist/", views.wholesale_assist, name="wholesale_assist"),
    path("grill/", views.grill, name="grill"),
    path("retail/", views.retail, name="retail"),
    path("wholesale/", views.wholesale, name="wholesale"),
    path("contact/", views.contact, name="contact"),
    path("trade_application/", views.trade_application, name="trade_application"),
    path("become_supplier/", views.become_supplier, name="become_supplier"),

    path("checkout/", views.checkout, name="checkout"),
    path("orders/<int:pk>/", views.order_view, name="view-order"),
    path("orders/<int:pk>/", views.order_view, name="order-detail"),

    # PayFast endpoints
    path("payments/return/", views.payfast_return, name="payfast_return"),
    path("payments/cancel/", views.payfast_cancel, name="payfast_cancel"),
    path("payments/payfast/ipn/", views.payfast_ipn, name="payfast_ipn"),

    # ---------- Password reset (OTP) ----------
    path("password-reset/", views.OtpResetPageView.as_view(), name="password-reset-otp"),
    path("api/pwreset/start", views.pwreset_start, name="api_pwreset_start"),
    path("api/pwreset/verify", views.pwreset_verify, name="api_pwreset_verify"),
    path("api/pwreset/complete", views.pwreset_complete, name="api_pwreset_complete"),

    path("payfast/start/", views.payfast_start, name="payfast_start"),
]

