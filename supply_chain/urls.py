from django.urls import path

from . import views


app_name = "supply_chain"


urlpatterns = [
    # ========================================================
    # DASHBOARD
    # ========================================================

    path(
        "",
        views.dashboard,
        name="supply-chain-dashboard",
    ),

    # ========================================================
    # SUPPLIERS
    # ========================================================

    path(
        "suppliers/",
        views.suppliers_list,
        name="supply-chain-suppliers",
    ),

    # ========================================================
    # PRODUCTS
    # ========================================================

    path(
        "products/",
        views.products_list,
        name="supply-chain-products",
    ),

    path(
        "products/<int:pk>/",
        views.product_detail,
        name="supply-chain-product-detail",
    ),

    path(
        "products/<int:pk>/edit/",
        views.product_edit,
        name="product-edit",
    ),

    path(
        "products/<int:pk>/knowledge/",
        views.product_knowledge,
        name="product-knowledge-view",
    ),

    path(
        "products/<int:pk>/knowledge/edit/",
        views.product_knowledge_edit,
        name="edit-product-knowledge",
    ),

    path(
        "products/import/",
        views.products_import,
        name="supply-chain-products-import",
    ),

    path(
        "products/price-list/",
        views.products_download_price_list,
        name="supply-chain-products-price-list",
    ),

    # ========================================================
    # PROCUREMENT
    # ========================================================

    path(
        "procurement/",
        views.procurement_list,
        name="supply-chain-procurement",
    ),

    # ========================================================
    # PURCHASE ORDERS
    # ========================================================

    path(
        "purchase-orders/",
        views.purchase_orders_list,
        name="supply-chain-purchase-orders",
    ),
]



