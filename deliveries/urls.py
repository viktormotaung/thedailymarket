from django.urls import path
from . import views

urlpatterns = [
    # Warehouse / Picking
    path("", views.warehouse, name="warehouse"),
    path("create-wave/", views.picking_create_wave, name="picking-create-wave"),
    path("<int:pk>/start/", views.picking_start, name="picking-start"),
    path("<int:pk>/complete/", views.picking_complete, name="picking-complete"),
    path("<int:pk>/", views.picking_view, name="picking-view"),

    # Deliveries landing -> delegates to runs or warehouse based on ?view=
    path("delivery/", views.delivery, name="delivery"),

    # Delivery Runs
    path("runs/", views.runs_list, name="runs-list"),
    path("runs/<int:pk>/", views.run_view, name="run-view"),
    path("runs/<int:pk>/start/", views.run_start, name="run-start"),
    path("runs/<int:pk>/pause/", views.run_pause, name="run-pause"),
    path("runs/<int:pk>/complete/", views.run_complete, name="run-complete"),
    path("runs/<int:pk>/recalc/", views.run_recalc, name="run-recalc"),
]
