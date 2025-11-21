from django.urls import path
from . import views


urlpatterns = [
    path("", views.order_list, name="staff-orders"),
    path("new/", views.order_create, name="order-create"),
    path("<int:pk>/edit/", views.order_edit, name="order-edit"),
    path("<int:pk>/view/", views.order_view, name="order-view"),
    path("orders/<int:pk>/delete/", views.order_delete, name="order-delete"),
    path("ajax/products-by-category/", views.ajax_products_by_category, name="ajax-products-by-category"),
]
