from django.urls import path
from . import views

urlpatterns = [
    # Warehouse / Picking
    path("", views.warehouse, name="warehouse"),
    path("create-wave/", views.picking_create_wave, name="picking-create-wave"),
    path("<int:pk>/start/", views.picking_start, name="picking-start"),
    path("<int:pk>/complete/", views.picking_complete, name="picking-complete"),
    path("<int:pk>/", views.picking_view, name="picking-view"),
    path("warehouse/batches/<int:batch_id>/", views.warehouse_batch_detail, name="warehouse-batch-detail",), 

    # Deliveries landing -> delegates to runs or warehouse based on ?view=
    path("delivery/", views.delivery, name="delivery"),
    path("monitor/", views.monitor, name="monitor"),
    path("vehicle/<int:vehicle_id>/log/", views.vehicle_log, name="vehicle-log"),
    path("runs/<int:run_id>/log/", views.run_log_view, name="run-log",),  




    # Delivery Runs
    path("runs/", views.runs_list, name="runs-list"),
    path("runs/<int:pk>/", views.run_view, name="run-view"),
    path("runs/<int:pk>/start/", views.run_start, name="run-start"),
    path("runs/<int:pk>/pause/", views.run_pause, name="run-pause"),
    path("runs/<int:pk>/complete/", views.run_complete, name="run-complete"),
    path("runs/<int:pk>/recalc/", views.run_recalc, name="run-recalc"),

    path("warehouse/batches/<int:batch_id>/consolidation/", views.warehouse_batch_consolidation, name="warehouse-batch-consolidation",), 
    path("warehouse/batches/<int:batch_id>/consolidation/supplier/<int:supplier_id>/", views.batch_supplier_consolidation, name="batch-supplier-consolidation",), 
    path("deliveries/run/<int:run_id>/", views.delivery_run_detail, name="delivery-run-detail",), 
    path( "deliveries/run/<int:run_id>/auto-plan/", views.delivery_run_auto_plan, name="delivery-run-auto-plan",), 
    path("dashboard/", views.staff_logistics_dashboard, name="staff-logistics-dashboard"),
]
