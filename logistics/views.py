# logistics/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.timezone import now
from datetime import timedelta
from django.db.models import Sum, Count, Q
from deliveries.models import PickingBatch, PickingItem, DeliveryRun
from suppliers.models import Supplier




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
    - Allow picking (confirming quantities)
    - Prevent editing if batch is complete
    """

    batch = get_object_or_404(PickingBatch, id=batch_id)
    supplier = get_object_or_404(Supplier, id=supplier_id)

    items = (
        PickingItem.objects
        .filter(batch=batch, supplier=supplier)
        .select_related("order", "order_item")
        .order_by("order_id", "id")
    )

    # ----------------------------
    # POST: Confirm picked quantity
    # ----------------------------
    if request.method == "POST" and batch.status != "complete":
        item_id = request.POST.get("item_id")
        picked_qty = request.POST.get("picked_qty")

        item = get_object_or_404(items, id=item_id)

        try:
            picked_qty = Decimal(picked_qty)
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

        with transaction.atomic():
            item.picked_qty = picked_qty
            item.is_picked = picked_qty > 0
            item.save(update_fields=[
                "picked_qty",
                "is_picked",
                "updated_at",
            ])

            # Move batch to in_progress if still draft
            if batch.status == "draft":
                batch.status = "in_progress"
                batch.save(update_fields=["status", "updated_at"])

        return redirect(
            "logistics:batch-supplier-consolidation",
            batch_id=batch.id,
            supplier_id=supplier.id,
        )

    # ----------------------------
    # Context
    # ----------------------------
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

    return render(
        request,
        "logistics/delivery/run_detail.html",
        {
            "run": run,
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


# ----------------------
# Driver
# ----------------------

@login_required
def driver_dashboard(request):
    """
    Driver-facing route view (runs & stops)
    """
    return render(request, "logistics/driver/dashboard.html")
