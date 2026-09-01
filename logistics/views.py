# logistics/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect, reverse
from django.http import HttpResponseForbidden, JsonResponse
from django.urls import reverse
from django.db.models import Prefetch
from django.utils.timezone import now
from datetime import timedelta
from django.db.models import Sum, Count, Q
from deliveries.models import PickingBatch, PickingItem, DeliveryRun, DriverLocation, DeliveryStop, Vehicle
from suppliers.models import Supplier
from django.contrib import messages
from decimal import Decimal, InvalidOperation
from django.db.models import F
from django.db import models
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
import json
from django.db.models.functions import Concat
from django.db.models import OuterRef, Subquery, Exists, Value
from deliveries.forms import DeliveryRunAssignmentForm
from deliveries.models import RunEvent
from orders.models import Order
from django.db.models import OuterRef, Subquery, Exists
from django.contrib.auth import get_user_model
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q
from django.shortcuts import render
from django.utils.timezone import now

from deliveries.models import (
    PickingBatch,
    PickingItem,
    DeliveryRun,
    DeliveryStop,
    
)

User = get_user_model()






@login_required
def logistics_dashboard(request):
    # -----------------------------
    # 1) Range handling
    # -----------------------------
    range_key = request.GET.get("range", "today")
    now_dt = now()

    if range_key == "7d":
        start_dt = now_dt - timedelta(days=7)
    elif range_key == "month":
        start_dt = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # today
        start_dt = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    # -----------------------------
    # 2) Warehouse metrics
    # -----------------------------
    batches = PickingBatch.objects.filter(
        created_at__gte=start_dt
    )

    picking_items = PickingItem.objects.filter(
        batch__created_at__gte=start_dt
    )

    warehouse_metrics = {
        "batches_total": batches.count(),
        "batches_in_progress": batches.filter(status="in_progress").count(),
        "batches_complete": batches.filter(status="complete").count(),

        "items_total": picking_items.count(),
        "items_picked": picking_items.filter(is_picked=True).count(),
        "items_pending": picking_items.filter(is_picked=False).count(),
    }

    # -----------------------------
    # 3) Delivery / Fleet metrics
    # -----------------------------
    runs = DeliveryRun.objects.filter(
        service_date__gte=start_dt.date()
    )

    stops = DeliveryStop.objects.filter(
        run__service_date__gte=start_dt.date()
    )

    delivery_metrics = {
        "runs_total": runs.count(),
        "runs_active": runs.exclude(status__in=["complete", "cancelled"]).count(),
        "runs_complete": runs.filter(status="complete").count(),

        "stops_total": stops.count(),
        "stops_delivered": stops.filter(status="delivered").count(),
        "stops_failed": stops.filter(status="failed").count(),
        "stops_pending": stops.exclude(status__in=["delivered", "failed"]).count(),
    }

    # -----------------------------
    # 4) Distance & cost aggregates
    # -----------------------------
    cost_agg = runs.aggregate(
        total_distance=Sum("total_distance_km"),
        total_cost=Sum("overall_total_cost"),
        total_stops=Sum("stop_count"),
    )

    total_stops = cost_agg["total_stops"] or 0
    avg_cost_per_stop = (
        (cost_agg["total_cost"] or 0) / total_stops
        if total_stops else 0
    )

    cost_metrics = {
        "total_distance": cost_agg["total_distance"] or 0,
        "total_cost": cost_agg["total_cost"] or 0,
        "avg_cost_per_stop": avg_cost_per_stop,
    }

    # -----------------------------
    # 5) Recent operational lists
    # -----------------------------
    recent_batches = batches.select_related("created_by")[:5]
    active_runs = runs.exclude(status__in=["complete", "cancelled"]).select_related("driver", "vehicle")[:5]

    # -----------------------------
    # 6) Render
    # -----------------------------
    return render(request, "logistics/dashboard.html", {
        "range": range_key,

        # Warehouse
        "warehouse": warehouse_metrics,
        "recent_batches": recent_batches,

        # Fleet
        "delivery": delivery_metrics,
        "active_runs": active_runs,

        # Cost
        "costs": cost_metrics,
    })





@login_required
def warehouse_batches(request):
    """
    PickingBatch list & management
    """
    range_param = request.GET.get("range", "today")
    today = now().date()

    if range_param == "7d":
        start_date = today - timedelta(days=7)
        batches = PickingBatch.objects.filter(service_date__gte=start_date)

    elif range_param == "month":
        start_date = today.replace(day=1)
        batches = PickingBatch.objects.filter(service_date__gte=start_date)

    else:  # today (default)
        batches = PickingBatch.objects.filter(service_date=today)

    batches = batches.order_by("-service_date", "-created_at")

    context = {
        "batches": batches,
        "range": range_param,
    }

    return render(request, "logistics/warehouse/batches.html", context)


from django.db import transaction

@login_required
def warehouse_batch_detail(request, batch_id):
    """
    View and manage a PickingBatch.

    Actions supported:
    - pick_item       → confirm supplier commitment (auto-assigned)
    - complete_batch  → handoff to deliveries
    - reopen_batch    → unlock batch (admin/ops only)
    """
    batch = get_object_or_404(PickingBatch, id=batch_id)

    if request.method == "POST":
        action = request.POST.get("action")

        # ----------------------------
        # MARK ITEM PICKED
        # ----------------------------
        if action == "pick_item":
            item_id = request.POST.get("item_id")
            item = get_object_or_404(batch.items, id=item_id)

            if batch.status != "complete":
                with transaction.atomic():
                    item.mark_picked()

                    # Move batch from draft → in_progress automatically
                    if batch.status == "draft":
                        batch.status = "in_progress"
                        batch.save(update_fields=["status", "updated_at"])

        # ----------------------------
        # COMPLETE BATCH
        # ----------------------------
        elif action == "complete_batch":
            if batch.status != "complete":
                batch.mark_complete(user=request.user)

        # ----------------------------
        # REOPEN BATCH
        # ----------------------------
        elif action == "reopen_batch":
            if batch.status == "complete":
                batch.status = "in_progress"
                batch.completed_at = None
                batch.save(update_fields=[
                    "status",
                    "completed_at",
                    "updated_at",
                ])

        return redirect(
            "logistics:warehouse-batch-detail",
            batch_id=batch.id,
        )

    # ----------------------------
    # GET: DISPLAY PAGE
    # ----------------------------
    items = batch.items.select_related(
        "order",
        "order_item",
    ).order_by("order_id", "id")

    context = {
        "batch": batch,
        "items": items,
    }

    return render(
        request,
        "logistics/warehouse/batch_detail.html",
        context,
    )


@login_required
def warehouse_batch_consolidation(request, batch_id):
    """
    Batch-level consolidation view.

    Purpose:
    - Show all suppliers involved in this batch
    - Aggregate expected vs received quantities per supplier
    - Provide drill-down entry point per supplier

    This is a READ-ONLY overview.
    """

    batch = get_object_or_404(PickingBatch, id=batch_id)

    # -----------------------------------------
    # Aggregate suppliers for this batch
    # -----------------------------------------
    suppliers = (
        batch.items
        .select_related("supplier")
        .values(
            "supplier_id",
            "supplier__name",
        )
        .annotate(
            item_count=Count("id"),
            expected_total=Sum("expected_qty"),
            received_total=Sum("picked_qty"),
            consolidated_count=Count(
                "id",
                filter=Q(is_picked=True)
            ),
        )
        .order_by("supplier__name")
    )

    context = {
        "batch": batch,
        "suppliers": suppliers,
    }

    return render(
        request,
        "logistics/warehouse/consolidation.html",
        context,
    )




@login_required
def batch_supplier_consolidation(request, batch_id, supplier_id):
    """
    Supplier-level consolidation view.

    Responsibilities:
    - Show ONLY items for this batch + supplier
    - Allow picking (confirming quantities & prices)
    - Prevent editing if batch is complete
    - Auto-complete batch once all items are picked
    """

    batch = get_object_or_404(PickingBatch, id=batch_id)
    supplier = get_object_or_404(Supplier, id=supplier_id)

    items = (
        PickingItem.objects
        .filter(batch=batch, supplier=supplier)
        .select_related("order", "order_item")
        .order_by("order_id", "id")
    )

    # -------------------------------------------------
    # POST: Confirm picked quantity + actual price
    # -------------------------------------------------
    if request.method == "POST" and batch.status != "complete":
        item_id = request.POST.get("item_id")
        picked_qty_raw = request.POST.get("picked_qty")
        actual_price_raw = request.POST.get("actual_supplier_price")

        item = get_object_or_404(items, id=item_id)

        # Parse picked qty
        try:
            picked_qty = Decimal(picked_qty_raw)
        except Exception:
            return redirect(
                "logistics:batch-supplier-consolidation",
                batch_id=batch.id,
                supplier_id=supplier.id,
            )

        # Guardrails
        if picked_qty < 0 or picked_qty > item.expected_qty:
            return redirect(
                "logistics:batch-supplier-consolidation",
                batch_id=batch.id,
                supplier_id=supplier.id,
            )

        # Parse actual price (optional)
        try:
            actual_price = (
                Decimal(actual_price_raw)
                if actual_price_raw
                else None
            )
        except Exception:
            actual_price = None

        with transaction.atomic():

            item.picked_qty = picked_qty
            item.is_picked = picked_qty > 0

            if actual_price is not None:
                item.actual_supplier_price = actual_price

            item.save(update_fields=[
                "picked_qty",
                "is_picked",
                "actual_supplier_price",
                "updated_at",
            ])

            # Draft → In Progress
            if batch.status == "draft":
                batch.status = "in_progress"
                batch.save(update_fields=[
                    "status",
                    "updated_at",
                ])

            # Auto-complete batch
            remaining = (
                PickingItem.objects
                .filter(
                    batch=batch,
                    is_picked=False,
                )
                .exists()
            )

            if not remaining:
                batch.status = "complete"
                batch.save(update_fields=[
                    "status",
                    "updated_at",
                ])

        return redirect(
            "logistics:batch-supplier-consolidation",
            batch_id=batch.id,
            supplier_id=supplier.id,
        )

    # -------------------------------------------------
    # DISPLAY DEFAULTS (DO NOT SAVE)
    # -------------------------------------------------
    total_expected_qty = Decimal("0.00")
    total_picked_qty = Decimal("0.00")

    total_expected_value = Decimal("0.00")
    total_actual_value = Decimal("0.00")

    for item in items:

        # -----------------------------
        # Display values
        # -----------------------------
        item.display_picked_qty = (
            item.picked_qty
            if item.is_picked
            else item.expected_qty
        )

        item.display_actual_price = (
            item.actual_supplier_price
            if item.actual_supplier_price is not None
            else item.expected_supplier_price
        )

        # -----------------------------
        # Totals per line
        # -----------------------------
        expected_price = (
            item.expected_supplier_price
            or Decimal("0.00")
        )

        actual_price = (
            item.display_actual_price
            or Decimal("0.00")
        )

        item.expected_total = (
            item.expected_qty *
            expected_price
        )

        item.actual_total = (
            item.display_picked_qty *
            actual_price
        )

        item.variance = (
            item.actual_total -
            item.expected_total
        )

        # -----------------------------
        # Running totals
        # -----------------------------
        total_expected_qty += item.expected_qty
        total_picked_qty += item.picked_qty

        total_expected_value += item.expected_total
        total_actual_value += item.actual_total

    # -------------------------------------------------
    # Context
    # -------------------------------------------------
    context = {
        "batch": batch,
        "supplier": supplier,
        "items": items,

        "total_expected": total_expected_qty,
        "total_picked": total_picked_qty,

        "total_expected_value": total_expected_value,
        "total_actual_value": total_actual_value,

        "total_variance": (
            total_actual_value -
            total_expected_value
        ),

        "all_picked": not items.filter(
            is_picked=False
        ).exists(),
    }

    return render(
        request,
        "logistics/warehouse/supplier_detail.html",
        context,
    )



@login_required
def warehouse_consolidation(request):
    """
    Aggregated supplier ordering view
    """
    return render(request, "logistics/warehouse/consolidation.html")


# ----------------------
# Deliveries
# ----------------------

@login_required
def deliveries(request):
    """
    DeliveryRun list & planning dashboard
    """

    # -----------------------------
    # Filters (GET params)
    # -----------------------------
    status = request.GET.get("status")
    service_date = request.GET.get("date")

    qs = (
        DeliveryRun.objects
        .select_related("driver")
        .prefetch_related("stops")
        .order_by("-service_date", "-id")
    )

    if status:
        qs = qs.filter(status=status)

    if service_date:
        qs = qs.filter(service_date=service_date)

    context = {
        "runs": qs,
        "today": now().date(),
        "status_filter": status,
        "date_filter": service_date,
        "STATUS_CHOICES": DeliveryRun.STATUS,
    }

    return render(request, "logistics/delivery/list.html", context)



@login_required
def delivery_run_detail(request, run_id):
    """
    View a delivery run, including supplier pickups and customer deliveries.

    Allows assigning:
    - Driver
    - Vehicle
    - Starting Supplier

    ROUTE LOGIC:

        Driver Address
              ↓
        Starting Supplier
              ↓
        Other Suppliers
              ↓
        Customers
              ↓
        Driver Address
    """

    run = get_object_or_404(
        DeliveryRun.objects.prefetch_related(
            Prefetch(
                "stops",
                queryset=DeliveryStop.objects
                .select_related("supplier", "order")
                .order_by("sequence", "id"),
            )
        ),
        id=run_id,
    )

    # -----------------------------------
    # Dropdown data
    # -----------------------------------

    vehicles = Vehicle.objects.filter(
        status="active"
    ).order_by("label")

    suppliers = Supplier.objects.filter(
        is_active=True
    ).order_by("name")

    # -----------------------------------
    # Save assignment
    # -----------------------------------

    if request.method == "POST":

        form = DeliveryRunAssignmentForm(
            request.POST,
            instance=run,
            vehicles_qs=vehicles,
        )

        if form.is_valid():

            run = form.save(commit=False)

            # =====================================================
            # 1. SELECTED STARTING SUPPLIER
            #
            # The supplier remains the FIRST PHYSICAL STOP.
            #
            # BUT:
            #
            # The supplier is NOT the route origin.
            #
            # The route origin is the selected driver's address.
            # =====================================================

            supplier_id = request.POST.get(
                "start_supplier"
            )

            if supplier_id:

                try:

                    supplier = suppliers.get(
                        pk=supplier_id
                    )

                    # Keep the selected supplier attached
                    # to the DeliveryRun.
                    run.start_supplier = supplier

                except Supplier.DoesNotExist:

                    run.start_supplier = None

            else:

                run.start_supplier = None

            # =====================================================
            # 2. DRIVER = ROUTE ORIGIN + ROUTE DESTINATION
            # =====================================================

            if run.driver:

                try:

                    driver_profile = (
                        run.driver.driver_profile
                    )

                except Exception:

                    driver_profile = None

                if driver_profile:

                    # -------------------------------------------------
                    # Build a readable driver address.
                    # -------------------------------------------------

                    address_parts = [
                        driver_profile.address_line_1,
                        driver_profile.address_line_2,
                        driver_profile.suburb,
                        driver_profile.city,
                        driver_profile.province,
                        driver_profile.postal_code,
                    ]

                    address_parts = [
                        str(part).strip()
                        for part in address_parts
                        if part
                        and str(part).strip()
                    ]

                    driver_address = ", ".join(
                        address_parts
                    )

                    # -------------------------------------------------
                    # Driver name
                    # -------------------------------------------------

                    driver_name = (
                        run.driver.get_full_name()
                        or run.driver.get_username()
                    )

                    # -------------------------------------------------
                    # Store DRIVER as the run start location.
                    #
                    # This is intentionally NOT the supplier.
                    # -------------------------------------------------

                    if driver_address:

                        run.start_location_label = (
                            f"{driver_name} - "
                            f"{driver_address}"
                        )

                    else:

                        run.start_location_label = (
                            driver_name
                        )

                    run.start_lat = (
                        driver_profile.latitude
                    )

                    run.start_lng = (
                        driver_profile.longitude
                    )

                else:

                    # Driver exists but has no DriverProfile.
                    run.start_location_label = ""
                    run.start_lat = None
                    run.start_lng = None

            else:

                # No driver selected.
                run.start_location_label = ""
                run.start_lat = None
                run.start_lng = None

            # =====================================================
            # 3. SAVE RUN
            # =====================================================

            run.save()

            messages.success(
                request,
                "Delivery run updated successfully."
            )

            return redirect(
                "logistics:delivery-run-detail",
                run.id,
            )

    else:

        form = DeliveryRunAssignmentForm(
            instance=run,
            vehicles_qs=vehicles,
        )

    # -----------------------------------
    # Display
    # -----------------------------------

    return render(
        request,
        "logistics/delivery/run_detail.html",
        {
            "run": run,
            "form": form,
            "suppliers": suppliers,
        },
    )


@login_required
def delivery_run_plan(request, run_id):

    run = get_object_or_404(
        DeliveryRun,
        id=run_id,
    )

    return render(
        request,
        "logistics/delivery/run_plan.html",
        {
            "run": run,
        }
    )


@login_required
def delivery_run_auto_plan(request, run_id):

    run = get_object_or_404(
        DeliveryRun,
        id=run_id,
    )

    if request.method == "POST":

        # =========================================================
        # 1. DRIVER MUST BE ASSIGNED
        # =========================================================

        if not run.driver:

            messages.error(
                request,
                "Please assign a driver before generating the route."
            )

            return redirect(
                "logistics:delivery-run-detail",
                run.id,
            )

        # =========================================================
        # 2. DRIVER PROFILE MUST EXIST
        # =========================================================

        try:

            driver_profile = (
                run.driver.driver_profile
            )

        except Exception:

            driver_profile = None

        if not driver_profile:

            messages.error(
                request,
                "The selected driver does not have a driver profile."
            )

            return redirect(
                "logistics:delivery-run-detail",
                run.id,
            )

        # =========================================================
        # 3. DRIVER GPS MUST EXIST
        #
        # The driver's address is the route origin AND destination.
        # =========================================================

        if (
            driver_profile.latitude is None
            or driver_profile.longitude is None
        ):

            messages.error(
                request,
                "The selected driver does not have GPS coordinates on their profile."
            )

            return redirect(
                "logistics:delivery-run-detail",
                run.id,
            )

        # =========================================================
        # 4. STARTING SUPPLIER MUST BE SELECTED
        #
        # This supplier is the FIRST physical stop.
        #
        # It is NOT the route origin.
        # =========================================================

        if not run.start_supplier:

            messages.error(
                request,
                "Please select a starting supplier before generating the route."
            )

            return redirect(
                "logistics:delivery-run-detail",
                run.id,
            )

        # =========================================================
        # 5. ENSURE CUSTOMER GEO EXISTS
        #
        # IMPORTANT:
        #
        # Only CUSTOMER stops need snapshot_from_order().
        #
        # Supplier stops already get their coordinates from
        # the supplier.
        #
        # RETURN stops belong to the driver and must NOT be
        # passed through snapshot_from_order().
        # =========================================================

        customer_stops = (
            run.stops
            .filter(
                stop_type="CUSTOMER"
            )
            .select_related(
                "order__client"
            )
        )

        for stop in customer_stops:

            if not stop.has_geo:

                stop.snapshot_from_order()

                stop.save(
                    update_fields=[
                        "customer_name",
                        "phone",
                        "email",
                        "address_line1",
                        "address_line2",
                        "suburb",
                        "city",
                        "province",
                        "postal_code",
                        "country",
                        "lat",
                        "lng",
                        "updated_at",
                    ]
                )

        # =========================================================
        # 6. SAVE DRIVER AS THE RUN START LOCATION
        #
        # This is important because the DeliveryRun's start fields
        # should now represent the DRIVER, not the supplier.
        # =========================================================

        address_parts = [
            driver_profile.address_line_1,
            driver_profile.address_line_2,
            driver_profile.suburb,
            driver_profile.city,
            driver_profile.province,
            driver_profile.postal_code,
        ]

        address_parts = [
            str(part).strip()
            for part in address_parts
            if part
            and str(part).strip()
        ]

        driver_address = ", ".join(
            address_parts
        )

        driver_name = (
            run.driver.get_full_name()
            or run.driver.get_username()
        )

        if driver_address:

            run.start_location_label = (
                f"{driver_name} - "
                f"{driver_address}"
            )

        else:

            run.start_location_label = (
                driver_name
            )

        run.start_lat = (
            driver_profile.latitude
        )

        run.start_lng = (
            driver_profile.longitude
        )

        run.save(
            update_fields=[
                "start_location_label",
                "start_lat",
                "start_lng",
                "updated_at",
            ]
        )

        # =========================================================
        # 7. RUN ROUTE PLANNER
        # =========================================================

        from deliveries.services import (
            plan_run_sequence
        )

        success, message = (
            plan_run_sequence(run)
        )

        if success:

            messages.success(
                request,
                message
            )

        else:

            messages.error(
                request,
                message
            )

    return redirect(
        "logistics:delivery-run-detail",
        run_id=run.id
    )


# ----------------------
# Driver
# ----------------------
@login_required
def driver_view(request):
    """
    Driver-facing dashboard.
    Shows the assigned run, current stop, progress, and upcoming stops.
    """

    user = request.user

    run = (
        DeliveryRun.objects
        .filter(
            driver=user,
            status__in=["planned", "en_route"]
        )
        .order_by("service_date", "id")
        .first()
    )

    # -------------------------------------------------
    # No active run
    # -------------------------------------------------
    if not run:
        return render(
            request,
            "logistics/driver/driver_view.html",
            {
                "run": None,
                "current_stop": None,
                "upcoming_stops": [],
                "stops": [],
                "all_completed": False,
                "total_stops": 0,
                "completed_stops": 0,
            }
        )

    # -------------------------------------------------
    # Load stops with ordering
    # -------------------------------------------------
    stops = (
        run.stops
        .select_related("supplier", "order")
        .order_by("sequence", "id")
    )

    # -------------------------------------------------
    # Decorate stops with display helpers
    # -------------------------------------------------
    for stop in stops:
        if stop.stop_type == "SUPPLIER":
            stop.display_type = "Pickup"
        elif stop.stop_type == "CUSTOMER":
            stop.display_type = "Delivery"
        elif stop.stop_type == "RETURN":
            stop.display_type = "Return"
        else:
            stop.display_type = "Start"

        stop.display_address = stop.address_one_line() or "—"

    # -------------------------------------------------
    # Actionable stops
    # -------------------------------------------------
    actionable_stops = stops.filter(
        status__in=["assigned", "en_route"]
    )

    current_stop = actionable_stops.first()

    context = {
        "run": run,
        "stops": stops,
        "current_stop": current_stop,
        "upcoming_stops": actionable_stops,
        "all_completed": not actionable_stops.exists(),
        "total_stops": stops.count(),
        "completed_stops": stops.filter(status="delivered").count(),
    }

    return render(
        request,
        "logistics/driver/driver_view.html",
        context,
    )




@login_required
@require_POST
def record_driver_location(request, run_id):
    run = get_object_or_404(DeliveryRun, id=run_id, driver=request.user)

    lat = request.POST.get("lat")
    lng = request.POST.get("lng")

    if not lat or not lng:
        return JsonResponse({"ok": False}, status=400)

    DriverLocation.objects.create(
        run=run,
        driver=request.user,
        lat=lat,
        lng=lng,
    )

    return JsonResponse({"ok": True})


@login_required
@require_POST
def update_driver_location(request):
    """
    Receives live GPS from driver browser and stores it.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        lat = float(payload.get("lat"))
        lng = float(payload.get("lng"))
        run_id = payload.get("run_id")
    except Exception:
        return JsonResponse({"error": "Invalid payload"}, status=400)

    run = get_object_or_404(
        DeliveryRun,
        id=run_id,
        driver=request.user,
        status__in=["planned", "en_route", "paused"]
    )

    DriverLocation.objects.create(
        run=run,
        driver=request.user,
        lat=lat,
        lng=lng
    )

    return JsonResponse({"status": "ok"})


@login_required
@require_POST
def start_stop(request, stop_id):
    stop = get_object_or_404(
        DeliveryStop.objects.select_related("run", "run__driver"),
        id=stop_id
    )
    run = stop.run

    if run.driver_id != request.user.id:
        return JsonResponse({"error": "You are not assigned to this run"}, status=403)

    if stop.status != "assigned":
        return JsonResponse({"error": "Stop is not ready to start"}, status=400)

    is_first_stop = run.status != "en_route"

    stop.status = "en_route"
    stop.started_at = now()
    stop.updated_at = now()
    stop.save(update_fields=["status", "started_at", "updated_at"])

    if is_first_stop:
        run.status = "en_route"
        run.updated_at = now()
        run.save(update_fields=["status", "updated_at"])

        Order.objects.filter(
            delivery_stops__run=run
        ).distinct().update(
            status="out_for_delivery",
            updated_at=now()
        )

    lat = request.POST.get("lat")
    lng = request.POST.get("lng")
    try:
        if lat and lng:
            DriverLocation.objects.create(
                run=run,
                driver=request.user,
                lat=float(lat),
                lng=float(lng),
            )
    except (TypeError, ValueError):
        pass

    RunEvent.objects.create(
        run=run,
        stop=stop,
        event_type="STOP_ARRIVED",
        notes="Stop started by driver",
    )

    # ✅ THIS IS THE KEY LINE
    return redirect(request.META.get("HTTP_REFERER", "/"))# =====================================================



# END (COMPLETE) DELIVERY STOP
# =====================================================

@login_required
@require_POST
def end_stop(request, stop_id):
    stop = get_object_or_404(
        DeliveryStop.objects.select_related("run"),
        id=stop_id
    )
    run = stop.run

    # -------------------------------------------------
    # Security
    # -------------------------------------------------
    if run.driver_id != request.user.id:
        return HttpResponseForbidden("Not assigned to this run")

    if stop.status != "en_route":
        return HttpResponseForbidden("Stop not in progress")

    # -------------------------------------------------
    # Finish this stop
    # -------------------------------------------------
    stop.ended_at = now()

    if stop.started_at:
        stop.drive_min = int(
            (stop.ended_at - stop.started_at).total_seconds() // 60
        )

    # =================================================
    # RETURN TO DEPOT (FINAL STOP)
    # =================================================
    if stop.stop_type == "RETURN":

        stop.status = "delivered"

        stop.save(update_fields=[
            "status",
            "ended_at",
            "drive_min",
            "updated_at",
        ])

        run.status = "complete"

        if hasattr(run, "completed_at"):
            run.completed_at = now()

        run.save(update_fields=[
            "status",
            "updated_at",
            *(
                ["completed_at"]
                if hasattr(run, "completed_at")
                else []
            ),
        ])

        RunEvent.objects.create(
            run=run,
            stop=stop,
            event_type="DELIVERED",
            notes="Driver returned to depot. Delivery run completed.",
        )

        messages.success(
            request,
            "Delivery run completed successfully."
        )

        return redirect(
            "logistics:delivery-run-detail",
            run.id,
        )
    # =================================================
    # ALL OTHER STOPS
    # =================================================
    stop.status = "awaiting_completion"

    stop.save(update_fields=[
        "status",
        "ended_at",
        "drive_min",
        "updated_at",
    ])

    RunEvent.objects.create(
        run=run,
        stop=stop,
        event_type="STOP_ARRIVED",
        notes="Driver ended stop.",
    )

    if stop.stop_type == "CUSTOMER":
        return redirect(
            "logistics:stop-completion",
            stop_id=stop.id,
        )

    elif stop.stop_type == "SUPPLIER":
        return redirect(
            "logistics:supplier-stop-completion",
            stop_id=stop.id,
        )

    return redirect("logistics:driver-dashboard")



@login_required
def supplier_stop_completion(request, stop_id):
    stop = get_object_or_404(
        DeliveryStop.objects.select_related("run", "supplier"),
        id=stop_id,
    )

    # 🔐 Security
    if stop.run.driver_id != request.user.id:
        return HttpResponseForbidden("Not assigned")

    if stop.stop_type != "SUPPLIER":
        return HttpResponseForbidden("Invalid stop type")

    # 🔗 Identify the picking batch that created this run
    # Assumption (current design): one batch → one run
    picking_batch = (
        PickingBatch.objects
        .filter(name=stop.run.name)
        .order_by("-created_at")
        .first()
    )

    items = []
    if picking_batch:
        items = (
            picking_batch.items
            .filter(supplier=stop.supplier)
            .order_by("product_name")
        )

    return render(
        request,
        "logistics/driver/supplier_stop_completion.html",
        {
            "stop": stop,
            "supplier": stop.supplier,
            "items": items,
            "batch": picking_batch,
        }
    )






@login_required
def stop_completion(request, stop_id):
    stop = get_object_or_404(
        DeliveryStop.objects.select_related(
            "run",
            "order",
        ).prefetch_related(
            "items",
        ),
        id=stop_id,
    )

    run = stop.run
    order = stop.order

    # -------------------------------------------------
    # Security
    # -------------------------------------------------
    if run.driver_id != request.user.id:
        return HttpResponseForbidden("Not assigned")

    # -------------------------------------------------
    # Save
    # -------------------------------------------------
    if request.method == "POST":

        outcome = request.POST.get("outcome")

        with transaction.atomic():

            # -----------------------------------------
            # Proof of Delivery
            # -----------------------------------------

            stop.recipient_name = request.POST.get(
                "recipient_name",
                ""
            )

            stop.recipient_id_no = request.POST.get(
                "recipient_id_no",
                ""
            )

            stop.delivery_notes = request.POST.get(
                "delivery_notes",
                ""
            )

            stop.updated_by = request.user
            stop.updated_at = now()

            if request.FILES.get("signature"):
                stop.signature = request.FILES["signature"]
                stop.signed_at = now()

            # -----------------------------------------
            # Delivery Stop Items
            # -----------------------------------------

            for item in stop.items.all():

                delivered_raw = request.POST.get(
                    f"item_delivered_qty_{item.id}",
                    ""
                )

                notes = request.POST.get(
                    f"item_notes_{item.id}",
                    ""
                )

                shortage_reason = request.POST.get(
                    f"item_shortage_reason_{item.id}",
                    ""
                )

                try:
                    delivered_qty = (
                        Decimal(delivered_raw)
                        if delivered_raw != ""
                        else Decimal("0.00")
                    )

                except InvalidOperation:
                    delivered_qty = Decimal("0.00")

                item.delivered_qty = delivered_qty
                item.notes = notes
                item.shortage_reason = shortage_reason

                item.save(update_fields=[
                    "delivered_qty",
                    "notes",
                    "shortage_reason",
                    "updated_at",
                ])

            # -----------------------------------------
            # Outcome
            # -----------------------------------------

            if outcome == "complete":

                stop.status = "delivered"
                order.status = "complete"

            elif outcome == "returned":

                stop.status = "failed"
                order.status = "returned"

                stop.failed_at = now()

            elif outcome == "cancelled":

                stop.status = "cancelled"
                order.status = "cancelled"

            stop.save(update_fields=[
                "status",
                "recipient_name",
                "recipient_id_no",
                "delivery_notes",
                "signature",
                "signed_at",
                "failed_at",
                "updated_by",
                "updated_at",
            ])

            order.updated_at = now()

            order.save(update_fields=[
                "status",
                "updated_at",
            ])

            # -----------------------------------------
            # Complete run if finished
            # -----------------------------------------

            if not run.stops.filter(
                status__in=[
                    "assigned",
                    "en_route",
                    "awaiting_completion",
                ]
            ).exists():

                run.status = "complete"

                run.save(update_fields=[
                    "status",
                    "updated_at",
                ])

        return redirect(
            "logistics:driver-dashboard"
        )

    # -------------------------------------------------
    # Initial page
    # -------------------------------------------------

    return render(
        request,
        "logistics/driver/stop_completion.html",
        {
            "stop": stop,
            "items": stop.items.all(),
        },
    )



# =====================================================
# NEXT STOP (UI FLOW)
# =====================================================

@login_required
def next_stop(request, stop_id):
    stop = get_object_or_404(
        DeliveryStop.objects.select_related("run", "run__driver"),
        id=stop_id
    )

    # --- AUTH ---
    if stop.run.driver_id != request.user.id:
        return redirect("logistics:driver-dashboard")

    # --- SAFETY ---
    if stop.status != "delivered":
        return redirect("logistics:driver-dashboard")

    return redirect("logistics:driver-dashboard")

@login_required
@require_POST
def driver_location_ping(request):
    """
    Receives periodic GPS pings from driver browser
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    lat = data.get("lat")
    lng = data.get("lng")

    if not lat or not lng:
        return JsonResponse({"error": "Missing coordinates"}, status=400)

    run = (
        DeliveryRun.objects
        .filter(
            driver=request.user,
            status__in=["planned", "en_route"]
        )
        .order_by("-updated_at")
        .first()
    )

    if not run:
        return JsonResponse({"error": "No active run"}, status=400)

    DriverLocation.objects.create(
        run=run,
        driver=request.user,
        lat=float(lat),
        lng=float(lng),
    )

    return JsonResponse({
        "success": True,
        "timestamp": now().isoformat()
    })


@login_required
def monitor_view(request):
    view_mode = request.GET.get("view", "table")  # table | map

    # Latest run per vehicle
    latest_run_qs = (
        DeliveryRun.objects
        .filter(vehicle=OuterRef("pk"))
        .order_by("-updated_at")
    )

    # Latest location per run
    latest_location_qs = (
        DriverLocation.objects
        .filter(run=OuterRef("latest_run_id"))
        .order_by("-recorded_at")
    )

    vehicles = (
        Vehicle.objects
        .annotate(
            # Latest run id
            latest_run_id=Subquery(
                latest_run_qs.values("id")[:1]
            ),

            # Latest driver
            last_driver_id=Subquery(
                latest_run_qs.values("driver_id")[:1]
            ),

            last_driver_name=Subquery(
                User.objects
                .filter(id=OuterRef("last_driver_id"))
                .annotate(
                    full_name=Concat(
                        "first_name",
                        Value(" "),
                        "last_name",
                    )
                )
                .values("full_name")[:1]
            ),

            # Last operational update
            last_update=Subquery(
                latest_run_qs.values("updated_at")[:1]
            ),

            # Is vehicle currently active
            is_active=Exists(
                DeliveryRun.objects.filter(
                    vehicle=OuterRef("pk"),
                    status="en_route",
                )
            ),

            # 📍 LAST KNOWN LOCATION
            last_lat=Subquery(
                latest_location_qs.values("lat")[:1]
            ),
            last_lng=Subquery(
                latest_location_qs.values("lng")[:1]
            ),
        )
        .order_by("-last_update", "label")
    )

    context = {
        "view": view_mode,
        "vehicles": vehicles,
    }

    return render(
        request,
        "logistics/driver/monitor_view.html",
        context,
    )


@login_required
def vehicle_log(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id)

    runs = (
        DeliveryRun.objects
        .filter(vehicle=vehicle)
        .select_related("driver")
        .order_by("-service_date", "-updated_at")
    )

    context = {
        "vehicle": vehicle,
        "runs": runs,
    }

    return render(
        request,
        "logistics/driver/vehicle_log.html",
        context,
    )

@login_required
def vehicle_log_view(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id)

    runs = (
        DeliveryRun.objects
        .filter(vehicle=vehicle)
        .select_related("driver")
        .order_by("-service_date", "-created_at")
    )

    context = {
        "vehicle": vehicle,
        "runs": runs,
    }

    return render(
        request,
        "logistics/driver/vehicle_log.html",
        context,
    )

@login_required
def run_log_view(request, run_id):
    run = get_object_or_404(
        DeliveryRun.objects.select_related("vehicle", "driver"),
        id=run_id
    )

    stops = (
        DeliveryStop.objects
        .filter(run=run)
        .order_by("sequence")
    )

    locations = (
        DriverLocation.objects
        .filter(run=run)
        .order_by("-recorded_at")
    )

    context = {
        "run": run,
        "stops": stops,
        "locations": locations,
    }

    return render(
        request,
        "logistics/driver/run_log.html",
        context,
    )
