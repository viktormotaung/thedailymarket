from django.urls import path
from . import views

urlpatterns = [
    path("", views.product_list, name="staff-products"),
    path("new/", views.product_create, name="product-create"),
    path("<int:pk>/edit/", views.product_edit, name="product-edit"),
    path("<int:pk>/view/", views.product_view, name="product-view"),

    path("<int:product_id>/pricing/", views.product_pricing_list, name="product-pricing-list"),
    path("<int:product_id>/pricing/new/", views.product_pricing_create, name="product-pricing-create"),
    path("pricing/<int:pk>/edit/", views.product_pricing_edit, name="product-pricing-edit"),

    # ✅ NEW: variant routes
    path("<int:product_id>/variants/new/", views.variant_create, name="variant-create"),
    path("variants/<int:pk>/edit/", views.variant_edit, name="variant-edit"),  # optional
]
