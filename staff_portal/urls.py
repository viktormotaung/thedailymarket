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
]
