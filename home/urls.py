# home/urls.py
from django.urls import path
from . import views
from django.conf.urls.static import static

urlpatterns = [
    path("", views.home, name="home"),

    # Static pages
    path("about/", views.about, name="about"),
    path("trade_assist/", views.trade_assist, name="trade_assist"),

    # Auth
    path("portal/staff/login/", views.staff_login, name="staff-login"),
    path("portal/client/login/", views.ClientLoginView.as_view(), name="client-login"),
    path("register_profile/", views.register_profile, name="register-profile"),
    path("register/success/", views.register_success, name="register-success",),
    path("logout/", views.logout_view, name="logout"),
    path("portal/consumer/login/", views.consumer_login, name="consumer-login"),

    path("reset/<uidb64>/<token>/", views.staff_password_set, name="staff-password-set",), 

    # Dashboards
    path("portal/client/", views.client_dashboard, name="client-dashboard"),

    # Client tabs
    path("products/", views.products, name="products"),
    path("products/<slug:slug>/", views.product_detail, name="product-detail"),
    path("cart/", views.cart, name="cart"),
    path("wholesale_assist/", views.wholesale_assist, name="wholesale_assist"),
    path("grill/", views.grill, name="grill"),
    path("retail/", views.retail, name="retail"),
    path("wholesale/", views.wholesale, name="wholesale"),
    path("contact/", views.contact, name="contact"),
    path("trade_application/", views.trade_application, name="trade_application"),
    path("become_supplier/", views.become_supplier, name="become_supplier"),
    path("profile/", views.profile, name="profile"),

    path("checkout/", views.checkout, name="checkout"),
    path("orders/<int:pk>/", views.view_order, name="view-order"),
    path("orders/", views.orders, name="orders"),
    path("invoice/<int:pk>/", views.view_invoice, name="view-invoice"),
    path("invoice/<int:pk>/pay/", views.pay_invoice, name="pay-invoice"),
    path("invoice/<int:pk>/pay/", views.pay_invoice, name="pay-invoice"),
    
    path("invoices/<int:pk>/send-email/", views.send_invoice_email, name="send-invoice-email"),



    # PayFast endpoints
    path("payfast/return/", views.payfast_return, name="payfast-return"),
    path("payfast/cancel/", views.payfast_cancel, name="payfast-cancel"),
    path("payfast/itn/", views.payfast_itn, name="payfast-itn"),


    # ---------- Password reset (OTP) ----------
    path("password-reset/", views.OtpResetPageView.as_view(), name="password-reset-otp"),
    path("api/pwreset/start", views.pwreset_start, name="api_pwreset_start"),
    path("api/pwreset/verify", views.pwreset_verify, name="api_pwreset_verify"),
    path("api/pwreset/complete", views.pwreset_complete, name="api_pwreset_complete"),

    path("payfast/start/", views.payfast_start, name="payfast_start"),
]

