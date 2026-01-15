# logistics/urls.py
from django.urls import path
from . import views

app_name = "logistics"

urlpatterns = [
    # Dashboard
    path("", views.logistics_dashboard, name="logistics-dashboard"),

    # Warehouse
    path("warehouse/batches/", views.warehouse_batches, name="warehouse-batches"),
    path("warehouse/batches/<int:batch_id>/", views.warehouse_batch_detail, name="warehouse-batch-detail",),

    path(
        "warehouse/batches/<int:batch_id>/consolidation/",
        views.warehouse_batch_consolidation,
        name="warehouse-batch-consolidation",
    ),

    path(
        "warehouse/batches/<int:batch_id>/consolidation/supplier/<int:supplier_id>/",
        views.batch_supplier_consolidation,
        name="batch-supplier-consolidation",
    ),



    path("warehouse/consolidation/", views.warehouse_consolidation, name="warehouse-consolidation"),

    # Deliveries
    path("deliveries/", views.deliveries, name="deliveries"),

    # 👇 ADD THESE
    path("deliveries/run/<int:run_id>/", views.delivery_run_detail, name="delivery-run-detail",),

    path(
        "deliveries/run/<int:run_id>/plan/",
        views.delivery_run_plan,
        name="delivery-run-plan",
    ),

    # Driver
    path("driver/", views.driver_dashboard, name="driver-dashboard"),
]
