from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard, name="staff-dashboard"),
  
   

    path('my_profile/', views.my_profile, name='my_profile'),

    path('staff_profile/', views.staff_profile, name='staff_profile'),
    path('staff_profile_edit/', views.staff_profile_edit, name='staff_profile_edit'),
    path('staff_profile_create/', views.staff_profile_create, name='staff_profile_create'),

    path('customer_profile/', views.customer_profile, name='customer_profile'),
    path("staff/<int:pk>/view/", views.staff_profile_view, name="staff_profile_view"),
    path("staff/<int:pk>/edit/", views.staff_profile_edit, name="staff_profile_edit"),
    path("customers/<int:pk>/edit/", views.customer_profile_edit, name="customer_profile_edit"),
    path("customers/<int:pk>/view/", views.customer_profile_view, name="customer_profile_view"),
    path("staff/<int:pk>/email/", views.staff_profile_email, name="staff_profile_email",), 
    path("notifications/<int:pk>/open/", views.open_notification, name="notification-open"),

    path("staff-profile/<int:pk>/send-password-sms/", views.staff_profile_send_password_sms, name="staff_profile_send_password_sms",),

    path("staff-profile/<int:pk>/send-password-email/", views.staff_profile_send_password_email, name="staff_profile_send_password_email",),
    path("sales-staff-profile/<int:staff_pk>/", views.sales_staff_profile_view, name="sales_staff_profile_view",),
    path("sales-staff-profile/<int:staff_pk>/edit/", views.sales_staff_profile_edit, name="sales_staff_profile_edit",), 
    path("sales-staff-profile/create/", views.sales_staff_profile_create, name="sales_staff_profile_create",),
    path("driver-profile/create/", views.driver_profile_create, name="driver_profile_create",),
    path("driver-profile/<int:staff_pk>/", views.driver_profile_view, name="driver_profile_view",), 
] 
