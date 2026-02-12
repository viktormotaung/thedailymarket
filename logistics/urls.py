# logistics/urls.py
from django.urls import path
from . import views

app_name = "logistics"

urlpatterns = [
    # Dashboard
    path("", views.logistics_dashboard, name="logistics-dashboard"),

    # Warehouse
    path("warehouse/batches/", views.warehouse_batches, name="warehouse-batches"),
    path(
        "warehouse/batches/<int:batch_id>/",
        views.warehouse_batch_detail,
        name="warehouse-batch-detail",
    ),
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
    path(
        "warehouse/consolidation/",
        views.warehouse_consolidation,
        name="warehouse-consolidation",
    ),

    # Deliveries
    path("deliveries/", views.deliveries, name="deliveries"),

    path(
        "deliveries/run/<int:run_id>/",
        views.delivery_run_detail,
        name="delivery-run-detail",
    ),
    path(
        "deliveries/run/<int:run_id>/plan/",
        views.delivery_run_plan,
        name="delivery-run-plan",
    ),
    path(
        "deliveries/run/<int:run_id>/auto-plan/",
        views.delivery_run_auto_plan,
        name="delivery-run-auto-plan",
    ),

    # Driver
    path("driver/", views.driver_view, name="driver-dashboard"),
    path(
        "driver/location/update/",
        views.update_driver_location,
        name="driver-location-ping",
    ),

    # ======================
    # DELIVERY STOPS
    # ======================
    path(
        "stops/<int:stop_id>/start/",
        views.start_stop,
        name="start-stop",
    ),
    path(
        "stops/<int:stop_id>/end/",
        views.end_stop,
        name="end-stop",
    ),
    path(
        "stops/<int:stop_id>/completion/",
        views.stop_completion,
        name="stop-completion",
    ),

    path(
        "driver/next-stop/<int:stop_id>/",
        views.next_stop,
        name="next-stop",
    ),

    # Logs
    path(
        "vehicle/<int:vehicle_id>/log/",
        views.vehicle_log,
        name="vehicle-log",
    ),
    path(
        "vehicles/<int:vehicle_id>/logs/",
        views.vehicle_log_view,
        name="vehicle-log",
    ),
    path(
        "runs/<int:run_id>/log/",
        views.run_log_view,
        name="run-log",
    ),

    # Monitor
    path("monitor/", views.monitor_view, name="monitor-view"),

    path(
        "driver/stops/<int:stop_id>/supplier/",
        views.supplier_stop_completion,
        name="supplier-stop-completion",
    ),

]
