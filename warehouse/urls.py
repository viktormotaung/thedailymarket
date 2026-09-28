from django.urls import path

from . import views


app_name = "warehouse"


urlpatterns = [
    path(
        "",
        views.dashboard,
        name="warehouse-dashboard",
    ),

    path(
        "inventory/",
        views.inventory,
        name="warehouse-inventory",
    ),

    path(
        "inventory/<int:pk>/",
        views.inventory_detail,
        name="warehouse-inventory-detail",
    ),

    path(
        "receiving/",
        views.receiving,
        name="warehouse-receiving",
    ),

    path(
        "fulfilment/",
        views.fulfilment,
        name="warehouse-fulfilment",
    ),

    path(
        "inventory/<int:pk>/edit/",
        views.inventory_edit,
        name="warehouse-inventory-edit",
    ),
]