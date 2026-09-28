from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal


DAY_OPTIONS = (7, 14, 30)

from deliveries.models import (
    Inventory,
    StockReceipt,
    StockReservation,
    StockMovement,
    StockCount,
    StockCountItem,
    PickingBatch,
    PickingItem,
)
from profiles.models import WarehouseStaff


def warehouse_staff_check(user):
    return (
        user.is_authenticated
        and WarehouseStaff.objects.filter(
            user=user,
            is_active=True,
        ).exists()
    )


warehouse_staff_required = user_passes_test(
    warehouse_staff_check,
    login_url="/portal/staff/login/",
)


@login_required
@warehouse_staff_required
def dashboard(request):
    """
    Warehouse Portal control-centre dashboard.

    Focus:
    - Current stock position
    - Receiving / inbound activity
    - Reservations and stock commitments
    - Picking and fulfilment progress
    - Stock-count control and variances
    - Operational items requiring attention
    - Recent warehouse activity
    """

    today = timezone.localdate()

    inventory_qs = (
        Inventory.objects
        .filter(is_active=True)
        .select_related("product")
    )

    # ---------------------------------------------------------
    # STOCK POSITION
    # ---------------------------------------------------------

    total_stock_items = inventory_qs.count()

    out_of_stock = inventory_qs.filter(
        quantity_on_hand__lte=0
    ).count()

    negative_stock = inventory_qs.filter(
        quantity_on_hand__lt=0
    ).count()

    on_hand_units = (
        inventory_qs.aggregate(
            total=Sum("quantity_on_hand")
        )["total"]
        or 0
    )

    reserved_units = (
        inventory_qs.aggregate(
            total=Sum("quantity_reserved")
        )["total"]
        or 0
    )

    available_units = max(
        0,
        on_hand_units - reserved_units,
    )

    # ---------------------------------------------------------
    # RECEIVING / INBOUND
    # ---------------------------------------------------------

    pending_receipts = StockReceipt.objects.filter(
        status__in=("draft", "receiving")
    ).count()

    receipts_received_today = StockReceipt.objects.filter(
        status="received",
        received_at__date=today,
    ).count()

    receipts_created_today = StockReceipt.objects.filter(
        created_at__date=today,
    ).count()

    receipt_items_received_today = (
        StockReceipt.objects
        .filter(
            status="received",
            received_at__date=today,
        )
        .aggregate(
            total=Sum("items__received_qty")
        )["total"]
        or 0
    )

    # ---------------------------------------------------------
    # RESERVATIONS
    # ---------------------------------------------------------

    active_reservations = StockReservation.objects.filter(
        status="reserved"
    ).count()

    reservations_today = StockReservation.objects.filter(
        reserved_at__date=today
    ).count()

    reserved_orders = (
        StockReservation.objects
        .filter(status="reserved")
        .values("order_id")
        .distinct()
        .count()
    )

    # ---------------------------------------------------------
    # PICKING / FULFILMENT
    # ---------------------------------------------------------

    open_picking_batches = PickingBatch.objects.filter(
        status__in=("draft", "in_progress")
    )

    picking_queue = open_picking_batches.count()

    picking_batches_in_progress = PickingBatch.objects.filter(
        status="in_progress"
    ).count()

    completed_picking_today = PickingBatch.objects.filter(
        status="complete",
        completed_at__date=today,
    ).count()

    open_picking_items = PickingItem.objects.filter(
        batch__status__in=("draft", "in_progress"),
    )

    items_to_pick = (
        open_picking_items
        .filter(is_picked=False)
        .aggregate(total=Sum("expected_qty"))["total"]
        or 0
    )

    picking_items_remaining = open_picking_items.filter(
        is_picked=False
    ).count()

    picked_items_today = PickingItem.objects.filter(
        is_picked=True,
        picked_at__date=today,
    ).aggregate(
        total=Sum("picked_qty")
    )["total"] or 0

    picking_progress_total = open_picking_items.count()
    picking_progress_picked = open_picking_items.filter(
        is_picked=True
    ).count()

    if picking_progress_total:
        picking_progress_pct = round(
            (picking_progress_picked / picking_progress_total) * 100,
            1,
        )
    else:
        picking_progress_pct = 0

    # ---------------------------------------------------------
    # STOCK COUNTS / CONTROL
    # ---------------------------------------------------------

    stock_counts_in_progress = StockCount.objects.filter(
        status="in_progress"
    ).count()

    stock_counts_pending = StockCount.objects.filter(
        status__in=("draft", "in_progress", "submitted")
    ).count()

    count_variance_lines = (
        StockCountItem.objects
        .filter(counted_qty__isnull=False)
        .exclude(counted_qty=F("system_qty"))
        .count()
    )

    # ---------------------------------------------------------
    # STOCK ACTIVITY
    # ---------------------------------------------------------

    movements_today = StockMovement.objects.filter(
        performed_at__date=today
    ).count()

    receipts_movements_today = StockMovement.objects.filter(
        performed_at__date=today,
        movement_type="receipt",
    ).count()

    picking_movements_today = StockMovement.objects.filter(
        performed_at__date=today,
        movement_type="pick",
    ).count()

    recent_movements = (
        StockMovement.objects
        .select_related(
            "product",
            "inventory__product",
            "performed_by",
            "receipt_item__receipt",
            "reservation",
        )
        .order_by(
            "-performed_at",
            "-id",
        )[:10]
    )

    # ---------------------------------------------------------
    # INVENTORY HEALTH / CATEGORY VIEW
    # ---------------------------------------------------------

    category_stock = []

    category_rows = (
        inventory_qs
        .values("product__category__name")
        .annotate(
            units=Sum("quantity_on_hand"),
        )
        .order_by("-units")[:8]
    )

    for row in category_rows:
        category_stock.append({
            "category": row["product__category__name"] or "Uncategorised",
            "units": row["units"] or 0,
        })

    # ---------------------------------------------------------
    # ATTENTION COUNTS
    # ---------------------------------------------------------

    attention_out_of_stock = out_of_stock
    attention_negative_stock = negative_stock
    attention_pending_receipts = pending_receipts
    attention_unpicked_items = picking_items_remaining
    attention_stock_counts = stock_counts_pending

    # ---------------------------------------------------------
    # CONTEXT
    # ---------------------------------------------------------

    context = {
        "current": "warehouse-dashboard",
        "dashboard_today": today,

        # Stock position
        "total_stock_items": total_stock_items,
        "out_of_stock": out_of_stock,
        "negative_stock": negative_stock,
        "on_hand_units": on_hand_units,
        "reserved_units": reserved_units,
        "available_units": available_units,

        # Receiving
        "pending_receipts": pending_receipts,
        "receipts_received_today": receipts_received_today,
        "receipts_created_today": receipts_created_today,
        "receipt_items_received_today": receipt_items_received_today,

        # Reservations
        "active_reservations": active_reservations,
        "reservations_today": reservations_today,
        "reserved_orders": reserved_orders,

        # Picking
        "picking_queue": picking_queue,
        "picking_batches_in_progress": picking_batches_in_progress,
        "completed_picking_today": completed_picking_today,
        "items_to_pick": items_to_pick,
        "picking_items_remaining": picking_items_remaining,
        "picked_items_today": picked_items_today,
        "picking_progress_total": picking_progress_total,
        "picking_progress_picked": picking_progress_picked,
        "picking_progress_pct": picking_progress_pct,

        # Stock counts
        "stock_counts_in_progress": stock_counts_in_progress,
        "stock_counts_pending": stock_counts_pending,
        "count_variance_lines": count_variance_lines,

        # Activity
        "movements_today": movements_today,
        "receipts_movements_today": receipts_movements_today,
        "picking_movements_today": picking_movements_today,
        "recent_movements": recent_movements,

        # Analysis
        "category_stock": category_stock,

        # Attention
        "attention_out_of_stock": attention_out_of_stock,
        "attention_negative_stock": attention_negative_stock,
        "attention_pending_receipts": attention_pending_receipts,
        "attention_unpicked_items": attention_unpicked_items,
        "attention_stock_counts": attention_stock_counts,
    }

    return render(
        request,
        "dashboard_warehouse.html",
        context,
    )


# ---------------------------------------------------------
# Inventory
# ---------------------------------------------------------

@login_required
@warehouse_staff_required
def inventory(request):
    """
    Current warehouse inventory.
    """

    qs = (
        Inventory.objects
        .select_related("product")
        .order_by("product__product_no")
    )

    status = (request.GET.get("status") or "").lower()

    if status == "out":
        qs = qs.filter(
            quantity_on_hand__lte=0
        )

    elif status == "reserved":
        qs = qs.filter(
            quantity_reserved__gt=0
        )

    elif status == "available":
        qs = qs.filter(
            quantity_on_hand__gt=0
        )

    # Overall inventory control figures.
    inventory_all = Inventory.objects.filter(
        is_active=True
    )

    total_items = inventory_all.count()

    out_of_stock = inventory_all.filter(
        quantity_on_hand__lte=0
    ).count()

    reserved_items = inventory_all.filter(
        quantity_reserved__gt=0
    ).count()

    available_items = inventory_all.filter(
        quantity_on_hand__gt=0
    ).count()

    on_hand_units = (
        inventory_all.aggregate(
            total=Sum("quantity_on_hand")
        )["total"]
        or 0
    )

    reserved_units = (
        inventory_all.aggregate(
            total=Sum("quantity_reserved")
        )["total"]
        or 0
    )

    available_units = max(
        0,
        on_hand_units - reserved_units,
    )

    context = {
        "current": "warehouse-inventory",

        # Inventory records
        "inventory": qs,

        # Active filter
        "filter_status": status,

        # Inventory control
        "total_items": total_items,
        "out_of_stock": out_of_stock,
        "reserved_items": reserved_items,
        "available_items": available_items,

        # Quantities
        "on_hand_units": on_hand_units,
        "reserved_units": reserved_units,
        "available_units": available_units,
    }

    return render(
        request,
        "inventory.html",
        context,
    )




@login_required
@warehouse_staff_required
def inventory_detail(request, pk):
    """
    View a single warehouse inventory record.
    """

    inventory_item = get_object_or_404(
        Inventory.objects.select_related("product"),
        pk=pk,
    )

    recent_movements = (
        StockMovement.objects
        .filter(inventory=inventory_item)
        .select_related(
            "product",
            "performed_by",
            "receipt_item__receipt",
            "reservation",
        )
        .order_by("-performed_at", "-id")[:25]
    )

    active_reservations = (
        StockReservation.objects
        .filter(
            inventory=inventory_item,
            status="reserved",
        )
        .select_related(
            "order",
            "order_item",
            "reserved_by",
        )
        .order_by("-reserved_at")
    )

    context = {
        "current": "warehouse-inventory",
        "inventory_item": inventory_item,
        "recent_movements": recent_movements,
        "active_reservations": active_reservations,
    }

    return render(
        request,
        "inventory_detail.html",
        context,
    )


@login_required
@warehouse_staff_required
def inventory_edit(request, pk):
    """
    Edit the warehouse inventory record.

    Stock quantities are not edited directly here.
    Quantity on hand and quantity reserved are controlled by
    warehouse stock movements, reservations, receiving, picking,
    returns, adjustments and stock counts.

    This screen is for inventory record control only.
    """

    inventory_item = get_object_or_404(
        Inventory.objects.select_related(
            "product",
            "last_supplier",
            "last_stock_receipt",
        ),
        pk=pk,
    )

    if request.method == "POST":

        is_active = request.POST.get("is_active")

        try:
            minimum_units = Decimal(
                (request.POST.get("minimum_units") or "").strip()
            )
            maximum_units = Decimal(
                (request.POST.get("maximum_units") or "").strip()
            )
        except Exception:
            return render(
                request,
                "inventory_edit.html",
                {
                    "current": "warehouse-inventory",
                    "inventory_item": inventory_item,
                    "error": "Minimum units and maximum units must be valid numbers.",
                },
            )

        if minimum_units < Decimal("0.01"):
            error = "Minimum units must be at least 0.01."
        elif maximum_units < Decimal("0.01"):
            error = "Maximum units must be at least 0.01."
        elif maximum_units < minimum_units:
            error = "Maximum units cannot be less than minimum units."
        else:
            inventory_item.is_active = is_active == "1"
            inventory_item.minimum_units = minimum_units
            inventory_item.maximum_units = maximum_units
            inventory_item.save(
                update_fields=[
                    "is_active",
                    "minimum_units",
                    "maximum_units",
                    "updated_at",
                ]
            )

            return redirect(
                "warehouse:warehouse-inventory-detail",
                pk=inventory_item.pk,
            )

        return render(
            request,
            "inventory_edit.html",
            {
                "current": "warehouse-inventory",
                "inventory_item": inventory_item,
                "error": error,
            },
        )

    context = {
        "current": "warehouse-inventory",
        "inventory_item": inventory_item,
    }

    return render(
        request,
        "inventory_edit.html",
        context,
    )


# ---------------------------------------------------------
# Receiving
# ---------------------------------------------------------

@login_required
@warehouse_staff_required
def receiving(request):
    """
    Warehouse receiving queue and recent receiving activity.
    """

    pending = (
        StockReceipt.objects
        .filter(
            status__in=("draft", "receiving")
        )
        .select_related(
            "supplier",
            "created_by",
            "received_by",
        )
        .order_by("-created_at")
    )

    recent = (
        StockReceipt.objects
        .select_related(
            "supplier",
            "created_by",
            "received_by",
        )
        .order_by(
            "-received_at",
            "-created_at",
        )[:25]
    )

    context = {
        "current": "warehouse-receiving",
        "pending_receipts": pending,
        "recent_receipts": recent,
    }

    return render(
        request,
        "receiving.html",
        context,
    )


# ---------------------------------------------------------
# Fulfilment
# ---------------------------------------------------------

@login_required
@warehouse_staff_required
def fulfilment(request):
    """
    Warehouse fulfilment / picking queue.
    """

    try:
        days = int(
            request.GET.get("days") or 7
        )
    except (TypeError, ValueError):
        days = 7

    if days not in DAY_OPTIONS:
        days = 7

    status = request.GET.get("status") or ""
    date_from = request.GET.get("from") or ""
    date_to = request.GET.get("to") or ""

    batches = (
        PickingBatch.objects
        .annotate(
            items_total=Count("items"),
            orders_total=Count(
                "items__order",
                distinct=True,
            ),
        )
        .order_by(
            "-service_date",
            "-id",
        )
    )

    if date_from and date_to:
        batches = batches.filter(
            service_date__range=[
                date_from,
                date_to,
            ]
        )
    else:
        batches = batches.filter(
            service_date__gte=(
                date.today()
                - timedelta(days=days)
            )
        )

    if status:
        batches = batches.filter(
            status=status
        )

    context = {
        "current": "warehouse-fulfilment",

        "DAY_OPTIONS": DAY_OPTIONS,
        "days": days,

        "filter_status": status,
        "date_from": date_from,
        "date_to": date_to,

        "batches": batches.select_related(
            "created_by"
        ),

        "status_choices": PickingBatch.STATUS,
    }

    return render(
        request,
        "fulfilment.html",
        context,
    )