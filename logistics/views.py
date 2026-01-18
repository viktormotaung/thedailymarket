# logistics/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
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
from deliveries.forms import DeliveryRunAssignmentForm



@login_required
def logistics_dashboard(request):
    return render(request, "logistics/dashboard.html")


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
            actual_price = Decimal(actual_price_raw) if actual_price_raw else None
        except Exception:
            actual_price = None

        with transaction.atomic():
            # Save item
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
                batch.save(update_fields=["status", "updated_at"])

            # ✅ Auto-complete batch if ALL items are picked
            remaining = (
                PickingItem.objects
                .filter(batch=batch, is_picked=False)
                .exists()
            )

            if not remaining:
                batch.status = "complete"
                batch.save(update_fields=["status", "updated_at"])

        return redirect(
            "logistics:batch-supplier-consolidation",
            batch_id=batch.id,
            supplier_id=supplier.id,
        )

    # -------------------------------------------------
    # DISPLAY DEFAULTS (DO NOT SAVE)
    # -------------------------------------------------
    for item in items:
        # Picked qty display
        item.display_picked_qty = (
            item.picked_qty if item.is_picked else item.expected_qty
        )

        # Actual price display
        item.display_actual_price = (
            item.actual_supplier_price
            if item.actual_supplier_price is not None
            else item.expected_supplier_price
        )

    # -------------------------------------------------
    # Context
    # -------------------------------------------------
    context = {
        "batch": batch,
        "supplier": supplier,
        "items": items,
        "total_expected": sum(i.expected_qty for i in items),
        "total_picked": sum(i.picked_qty for i in items),
        "all_picked": not items.filter(is_picked=False).exists(),
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
    run = get_object_or_404(DeliveryRun, id=run_id)

    # ✅ FIX: use status, not is_active
    vehicles = Vehicle.objects.filter(status="active")

    if request.method == "POST":
        form = DeliveryRunAssignmentForm(
            request.POST,
            instance=run,
            vehicles_qs=vehicles,
        )

        if form.is_valid():
            form.save()
            messages.success(request, "Driver and vehicle updated successfully.")
            return redirect("logistics:delivery-run-detail", run.id)
    else:
        form = DeliveryRunAssignmentForm(
            instance=run,
            vehicles_qs=vehicles,
        )

    return render(
        request,
        "logistics/delivery/run_detail.html",
        {
            "run": run,
            "form": form,
        }
    )


@login_required
def delivery_run_plan(request, run_id):
    run = get_object_or_404(DeliveryRun, id=run_id)

    return render(
        request,
        "logistics/delivery/run_plan.html",
        {
            "run": run,
        }
    )

@login_required
def delivery_run_auto_plan(request, run_id):
    run = get_object_or_404(DeliveryRun, id=run_id)

    if request.method == "POST":

        # 🔑 ENSURE GEO EXISTS BEFORE ROUTING
        for stop in run.stops.select_related("order__client"):
            if not stop.has_geo:
                stop.snapshot_from_order()
                stop.save(update_fields=[
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
                ])

        from deliveries.services import plan_run_sequence
        success, message = plan_run_sequence(run)

        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)

    return redirect("logistics:delivery-run-detail", run_id=run.id)



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

    # --- No active run ---
    if not run:
        return render(
            request,
            "logistics/driver/driver_view.html",
            {
                "run": None,
                "current_stop": None,
                "upcoming_stops": [],
                "stops": [],              # ✅ ADD THIS
                "all_completed": False,
            }
        )

    # --- Stops ---
    stops = run.stops.all().order_by("sequence", "id")

    undelivered = stops.exclude(status="delivered")
    current_stop = undelivered.first()

    context = {
        "run": run,
        "current_stop": current_stop,
        "upcoming_stops": undelivered,
        "stops": stops,               # ✅ THIS IS THE KEY LINE
        "all_completed": not undelivered.exists(),
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
        DeliveryStop.objects.select_related("run"),
        id=stop_id
    )

    run = stop.run

    # --- Safety checks ---
    if stop.status != "assigned":
        return JsonResponse(
            {"error": "Stop not ready to start"},
            status=400
        )

    # --- Start the stop ---
    stop.status = "en_route"
    stop.started_at = now()
    stop.updated_at = now()
    stop.save(update_fields=["status", "started_at", "updated_at"])

    # --- Ensure run is marked as en_route ---
    if run.status != "en_route":
        run.status = "en_route"
        run.updated_at = now()
        run.save(update_fields=["status", "updated_at"])

    return JsonResponse({"success": True})

@login_required
@require_POST
def end_stop(request, stop_id):
    stop = get_object_or_404(DeliveryStop, id=stop_id)

    if stop.status != "en_route":
        return JsonResponse({"error": "Stop not en route"}, status=400)

    stop.status = "arrived"
    stop.ended_at = now()

    if stop.started_at:
        stop.drive_min = int((stop.ended_at - stop.started_at).total_seconds() / 60)

    stop.save(update_fields=[
        "status",
        "ended_at",
        "drive_min",
        "updated_at",
    ])

    return JsonResponse({"success": True})

@login_required
def next_stop(request, stop_id):
    stop = get_object_or_404(DeliveryStop, id=stop_id)

    # safety: only allow if ended
    if not stop.ended_at:
        return redirect("logistics:driver-dashboard")

    return redirect("logistics:driver-dashboard")




@login_required
def monitor_view(request):
    view_mode = request.GET.get("view", "table")  # table | map

    context = {
        "view": view_mode,
        "runs": [],  # later: active runs
    }
    return render(request, "logistics/driver/monitor_view.html", context)
