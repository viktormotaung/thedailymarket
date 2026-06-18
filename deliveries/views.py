# deliveries/views.py
from datetime import date, timedelta
from deliveries.forms import DeliveryRunAssignmentForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from .models import PickingBatch, PickingItem, Vehicle, DriverLocation, DeliveryStop, _delivery_date_for, DeliveryRun
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Sum, Count, Q
from suppliers.models import Supplier
from decimal import Decimal
from deliveries.models import RunEvent
from django.db.models import OuterRef, Subquery, Exists, Value
from django.contrib.auth import get_user_model
from django.db.models.functions import Concat

User = get_user_model()

def staff_check(user):
    return user.is_authenticated and user.is_staff


staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")

DAY_OPTIONS = [7, 14, 30, 60, 90]


@login_required
@staff_required
def warehouse(request):
    # --- Filters ---
    try:
        days = int(request.GET.get("days") or 7)
    except ValueError:
        days = 7
    if days not in DAY_OPTIONS:
        days = 7

    status = request.GET.get("status") or ""
    date_from = request.GET.get("from") or ""
    date_to = request.GET.get("to") or ""

    qs = (
        PickingBatch.objects
        .annotate(
            items_total=Count("items"),
            orders_total=Count("items__order", distinct=True),
        )
        .order_by("-service_date", "-id")
    )

    if date_from and date_to:
        qs = qs.filter(service_date__range=[date_from, date_to])
    else:
        qs = qs.filter(service_date__gte=date.today() - timedelta(days=days))

    if status:
        qs = qs.filter(status=status)

    context = {
        "DAY_OPTIONS": DAY_OPTIONS,
        "days": days,
        "filter_status": status,
        "date_from": date_from,
        "date_to": date_to,
        "batches": qs.select_related("created_by"),
        "status_choices": PickingBatch.STATUS,
    }
    return render(request, "deliveries/warehouse.html", context)




@login_required
@staff_required
def delivery(request):
    view = (request.GET.get("view") or "").lower()
    if view == "runs":
        return runs_list(request)   # <-- make sure this name matches the function below
    return warehouse(request)

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
            "warehouse-batch-detail",
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
        "deliveries/picking_view.html",
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
        "deliveries/consolidation.html",
        context,
    )


@login_required
def batch_supplier_consolidation(request, batch_id, supplier_id):

    print("==== VIEW HIT ====")
    print("Method:", request.method)
    print("POST:", request.POST)

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
        print("---- POST BLOCK ENTERED ----")

        item_id = request.POST.get("item_id")
        picked_qty_raw = request.POST.get("picked_qty")
        actual_price_raw = request.POST.get("actual_supplier_price")

        print("item_id:", item_id)
        print("picked_qty_raw:", picked_qty_raw)
        print("actual_price_raw:", actual_price_raw)

        item = get_object_or_404(items, id=item_id)

        # Parse picked qty
        try:
            picked_qty = Decimal(picked_qty_raw)
            print("PARSED picked_qty:", picked_qty)
        except Exception as e:
            print("❌ picked_qty parse error:", e)
            return redirect("batch-supplier-consolidation", batch.id, supplier.id)

        # Guardrails
        if picked_qty < 0 or picked_qty > item.expected_qty:
            print("❌ Guardrail hit")
            return redirect("batch-supplier-consolidation", batch.id, supplier.id)

        # Parse actual price
        try:
            actual_price = Decimal(actual_price_raw) if actual_price_raw else None
            print("PARSED actual_price:", actual_price)
        except Exception as e:
            print("❌ actual_price parse error:", e)
            actual_price = None

        with transaction.atomic():
            print("---- SAVING ITEM ----")

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

            print("✅ ITEM SAVED")

            if batch.status == "draft":
                batch.status = "in_progress"
                batch.save(update_fields=["status", "updated_at"])

            remaining = (
                PickingItem.objects
                .filter(batch=batch, is_picked=False)
                .exists()
            )

            if not remaining:
                batch.status = "complete"
                batch.save(update_fields=["status", "updated_at"])

        return redirect("batch-supplier-consolidation", batch.id, supplier.id)

    # -------------------------------------------------
    # DISPLAY DEFAULTS (NO SAVE)
    # -------------------------------------------------
    for item in items:
        item.display_picked_qty = (
            item.picked_qty if item.is_picked else item.expected_qty
        )

        item.display_actual_price = (
            item.actual_supplier_price
            if item.actual_supplier_price is not None
            else item.expected_supplier_price
        )

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
        "deliveries/supplier_detail.html",
        context,
    )


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
            return redirect("delivery-run-detail", run.id)
    else:
        form = DeliveryRunAssignmentForm(
            instance=run,
            vehicles_qs=vehicles,
        )

    return render(
        request,
        "deliveries/run_view.html",
        {
            "run": run,
            "form": form,
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




def picking_create_wave(request):
    if request.method != "POST":
        return redirect(f"{reverse('warehouse')}?view=warehouse")  # ✅ fixed
    ...
    if not service_date:
        messages.error(request, "Please choose a service date.")
        return redirect(f"{reverse('warehouse')}?view=warehouse")  # ✅ fixed
    ...
    return redirect(f"{reverse('warehouse')}?view=warehouse")  # ✅ fixed



def picking_start(request, pk: int):
    batch = get_object_or_404(PickingBatch, pk=pk)
    if batch.status == "draft":
        batch.status = "in_progress"
        batch.started_by = request.user
        batch.started_at = timezone.now()  # ✅ works now
        batch.save(update_fields=["status", "started_by", "started_at", "updated_at"])
        messages.success(request, f"Batch {batch.name} started.")
    else:
        messages.info(request, "This batch is not in 'draft' state.")
    return redirect(f"{reverse('warehouse')}?view=warehouse")  # ✅



@login_required
@staff_required
def picking_complete(request, pk: int):
    batch = get_object_or_404(PickingBatch, pk=pk)
    if request.method == "POST":
        batch.mark_complete(user=request.user)
        messages.success(request, f"Batch '{batch.name}' completed and handed off to Delivery Runs.")
    return redirect(reverse("warehouse") + "?view=warehouse")


@login_required
@staff_required
def picking_view(request, pk: int):
    """
    Simple placeholder page (you can flesh out later with lines, add-order, etc.).
    """
    batch = get_object_or_404(PickingBatch, pk=pk)
    items = batch.items.select_related("order", "order_item").all()
    return render(
        request,
        "deliveries/picking_view.html",
        {"batch": batch, "items": items},
    )


@login_required
@staff_required
def runs_list(request):
    """
    Delivery Runs list + filters.
    """
    try:
        days = int(request.GET.get("days") or 7)
    except ValueError:
        days = 7
    if days not in DAY_OPTIONS:
        days = 7

    status = request.GET.get("status") or ""  # '', 'draft', 'planned', 'en_route', 'paused', 'complete', 'cancelled'
    date_from = request.GET.get("from") or ""
    date_to = request.GET.get("to") or ""

    qs = DeliveryRun.objects.order_by("-service_date", "-id")

    if date_from and date_to:
        qs = qs.filter(service_date__range=[date_from, date_to])
    else:
        qs = qs.filter(service_date__gte=date.today() - timedelta(days=days))

    if status:
        qs = qs.filter(status=status)

    context = {
        "DAY_OPTIONS": DAY_OPTIONS,
        "days": days,
        "filter_status": status,
        "date_from": date_from,
        "date_to": date_to,
        "runs": qs.select_related("driver", "vehicle"),

        "status_choices": DeliveryRun.STATUS,
    }
    return render(request, "deliveries/runs.html", context)


# ========== Run detail ==========
@login_required
@staff_required
def run_view(request, pk: int):
    run = get_object_or_404(DeliveryRun.objects.select_related("driver", "created_by"), pk=pk)
    stops = run.stops.select_related("order").order_by("sequence", "id")
    context = {
        "run": run,
        "stops": stops,
    }
    return render(request, "deliveries/run_view.html", context)


# ========== Actions (POST only) ==========
@login_required
@staff_required
@require_POST
def run_start(request, pk: int):
    run = get_object_or_404(DeliveryRun, pk=pk)
    if run.status in ("planned", "paused"):
        run.status = "en_route"
        run.save(update_fields=["status", "updated_at"])
        messages.success(request, "Run started.")
    else:
        messages.warning(request, "Run can only be started when planned or paused.")
    return redirect("run-view", pk=pk)




@login_required
@staff_required
@require_POST
def run_pause(request, pk: int):
    run = get_object_or_404(DeliveryRun, pk=pk)
    if run.status == "en_route":
        run.status = "paused"
        run.save(update_fields=["status", "updated_at"])
        messages.success(request, "Run paused.")
    else:
        messages.warning(request, "Only an active run can be paused.")
    return redirect("run-view", pk=pk)


@login_required
@staff_required
@require_POST
def run_complete(request, pk: int):
    run = get_object_or_404(DeliveryRun, pk=pk)
    if run.status in ("en_route", "planned"):
        run.status = "complete"
        run.save(update_fields=["status", "updated_at"])
        run.recalc_aggregates(save=True)
        messages.success(request, "Run marked complete.")
    else:
        messages.warning(request, "Only a planned or active run can be completed.")
    return redirect("run-view", pk=pk)


@login_required
@staff_required
@require_POST
def run_recalc(request, pk: int):
    run = get_object_or_404(DeliveryRun, pk=pk)
    run.recalc_aggregates(save=True)
    messages.success(request, "Run aggregates recalculated.")
    return redirect("run-view", pk=pk)




@login_required
@staff_required
@require_POST
def run_auto_plan(request, pk: int):
    run = get_object_or_404(DeliveryRun, pk=pk)
    try:
        run.auto_plan()  # calls services.plan_run_sequence(run)
        messages.success(request, "Auto-plan completed.")
    except Exception as e:
        messages.error(request, f"Auto-plan failed: {e}")
    return redirect("run-view", pk=pk)




@login_required
def monitor(request):
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
        "deliveries/monitor_view.html",
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
        "deliveries/vehicle_log.html",
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
        "deliveries/run_log.html",
        context,
    )


@login_required
@staff_required
def staff_logistics_dashboard(request):
    return render(request, "deliveries/staff_logistics_dashboard.html")


