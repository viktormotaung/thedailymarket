from django.urls import path
from . import views

urlpatterns = [
    path("", views.client_list, name="staff-clients"),
    path("new/", views.client_create, name="client-create"),
    path("<int:pk>/edit/", views.client_edit, name="client-edit"),
    # ✅ Client Compliance Edit
    path(
        "<int:pk>/compliance/edit/",
        views.client_compliance_edit,
        name="client-compliance-edit", 
    ),
    path("<int:pk>/view/", views.client_view, name="client-view"),
]
