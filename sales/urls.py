from django.urls import path
from . import views

app_name = "sales"

urlpatterns = [
    # Main sales dashboard
    path("", views.sales_dashboard, name="sales-dashboard"),

    # Prospects
    path("prospects/", views.prospects, name="sales-prospects"),
    path("prospects/add/", views.prospect_create, name="sales-prospect-create"),
    path("prospects/<int:pk>/", views.prospect_detail, name="sales-prospect-detail"),
    path(
        "prospects/<int:pk>/add-update/",
        views.prospect_update_create,
        name="sales-prospect-add-update",
    ),

    # Clients (sales view over existing clients)
    path("clients/", views.clients, name="sales-clients"),
    path("clients/<int:pk>/edit/", views.edit_client, name="edit-client"),
    path("clients/<int:pk>/view/", views.view_client, name="client-detail"),

    # Orders (from a sales perspective) - grouped under orders/
    path("orders/", views.orders, name="sales-orders"),
    path("orders/new/", views.create_order, name="create-order"),
    path("orders/<int:pk>/edit/", views.edit_order, name="edit-order"),
    path("orders/<int:pk>/view/", views.view_order, name="view-order"),
    path("orders/<int:pk>/delete/", views.delete_order, name="delete-order"),

    # AJAX endpoints (keep near related resource if you want)
    path("orders/ajax/products-by-category/", views.ajax_products_by_category, name="ajax-products-by-category"),

    # Invoices - grouped under invoices/
    path("invoices/", views.invoices, name="sales-invoices"),
    path("invoices/<int:pk>/view/", views.view_invoice, name="view-invoice"),

    # Commission & tickets
    path("commission/", views.commission, name="sales-commission"),
    path("commission/<int:pk>/", views.commission_view, name="sales-commission-view"),

    path("tickets/", views.tickets, name="sales-tickets"),
    path("tickets/<int:pk>/view/", views.view_ticket, name="view-ticket"),


    # Sales rep profile
    path("profile/", views.profile, name="sales-profile"),

    

]
