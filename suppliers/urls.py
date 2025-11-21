from django.urls import path
from . import views

urlpatterns = [
    path("", views.supplier_list, name="staff-suppliers"),
    path("new/", views.supplier_create, name="supplier-create"),
    path("<int:pk>/edit/", views.supplier_edit, name="supplier-edit"),
    path("<int:pk>/view/", views.supplier_view, name="supplier-view"),
]
