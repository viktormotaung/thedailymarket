# deliveries/views.py
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from .models import PickingBatch, _delivery_date_for, DeliveryRun
from django.views.decorators.http import require_POST
from django.utils import timezone


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
        "runs": qs.select_related("driver", "created_by"),
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