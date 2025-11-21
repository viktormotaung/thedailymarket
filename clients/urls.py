from django.urls import path
from . import views

urlpatterns = [
    path("", views.client_list, name="staff-clients"),
    path("new/", views.client_create, name="client-create"),
    path("<int:pk>/edit/", views.client_edit, name="client-edit"),
    path("<int:pk>/view/", views.client_view, name="client-view"),
]
