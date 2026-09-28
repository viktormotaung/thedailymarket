# deliveries/models.py


from __future__ import annotations
from django.core.exceptions import ValidationError
from decimal import Decimal
from typing import Optional
from datetime import date, time, timedelta
from django.db.models import Sum, Count, F
from django.db.models.functions import TruncDate
from django.apps import apps
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils.timezone import now
from django.db import transaction, IntegrityError
from django.db.models import Max
from suppliers.models import Supplier



# -----------------------------
# Delivery schedule & depot config
# -----------------------------

DELIVERY_START_TIME = time(7, 30)
DEPOT_PREFERENCE = [
    ("Muldersdrift", -26.045323, 27.820926),
    ("Deneysville", -26.861696, 28.086663),
    ("Randfontein", -26.204657037155766, 27.601252832720576),
]

# (weekday, wave) -> target weekday; Mon=0 ... Sun=6; targets are Mon(0)/Wed(2)/Fri(4)
_TARGET_WEEKDAY = {
    (0, "AM"): 2, (0, "PM"): 2,   # Monday -> Wednesday
    (1, "AM"): 2, (1, "PM"): 4,   # Tuesday AM -> Wednesday; Tuesday PM -> Friday
    (2, "AM"): 4, (2, "PM"): 4,   # Wednesday -> Friday
    (3, "AM"): 4, (3, "PM"): 4,   # Thursday -> Friday
    (4, "AM"): 0, (4, "PM"): 0,   # Friday -> Monday
    (5, "AM"): 0, (5, "PM"): 0,   # Saturday -> Monday
    (6, "AM"): 0, (6, "PM"): 2,   # Sunday AM -> Monday; Sunday PM -> Wednesday
}


def _delivery_date_for(service_date: date, wave: str) -> date:
    """
    Map service_date + wave ('AM'/'PM') to the next delivery date per policy.
    Targets are Mon/Wed/Fri only.
    """
    w = service_date.weekday()
    tgt = _TARGET_WEEKDAY[(w, wave.upper())]
    # days to add (wrap around)
    days = (tgt - w) % 7
    # If mapping ever targets the same weekday (not expected here), push to next week
    return service_date + timedelta(days=days or 7) if tgt == w else service_date + timedelta(days=days)


# -----------------------------
# 1) WAREHOUSE: Picking
# -----------------------------




# -----------------------------
# 1) INVENTORY: Stock control
# -----------------------------
#
# Product remains the permanent product master in the products app.
# Inventory records stock separately, so weekly product/price-list
# changes do not rewrite historical stock movements or receipts.
#
# IMPORTANT:
# Existing supplier/picking/delivery fields below are intentionally
# retained for legacy data. New workflow uses these inventory models.
#


class Inventory(models.Model):
    """Current stock position for one permanent Product."""

    product = models.OneToOneField(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="inventory",
    )

    quantity_on_hand = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    quantity_reserved = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    minimum_units = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Minimum number of individual units expected from the base quantity.",
    )

    maximum_units = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Maximum number of individual units expected from the base quantity. Use the same value for an exact count.",
    )

    last_received_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="last_received_inventory",
        help_text="Supplier from which the most recent stock receipt for this product came.",
    )
    last_stock_receipt = models.ForeignKey(
        "deliveries.StockReceipt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="last_received_inventory_rows",
    )

    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product_id"]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["last_received_at"]),
        ]

    def __str__(self):
        return f"Inventory · {self.product} · available {self.quantity_available}"

    @property
    def quantity_available(self):
        return max(
            Decimal("0.00"),
            self.quantity_on_hand - self.quantity_reserved,
        )


class StockReceipt(models.Model):
    """A physical receipt/GRN of stock from one supplier."""

    STATUS = [
        ("draft", "Draft"),
        ("receiving", "Receiving"),
        ("received", "Received"),
        ("cancelled", "Cancelled"),
    ]

    receipt_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="stock_receipts",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="draft",
        db_index=True,
    )

    supplier_invoice_number = models.CharField(max_length=100, blank=True)
    received_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_receipts_created",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_receipts_received",
    )
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_receipts_checked",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_receipts_completed",
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        indexes = [
            models.Index(fields=["supplier", "status"]),
            models.Index(fields=["received_at"]),
        ]

    def __str__(self):
        return f"{self.receipt_number} · {self.supplier} · {self.get_status_display()}"


class StockReceiptItem(models.Model):
    """Immutable-ish receipt line preserving what was actually received."""

    receipt = models.ForeignKey(
        "deliveries.StockReceipt",
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_receipt_items",
    )

    expected_qty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    received_qty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    unit_cost_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    unit_cost_incl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    batch_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["receipt_id", "id"]
        indexes = [
            models.Index(fields=["product", "receipt"]),
        ]

    def __str__(self):
        return f"{self.receipt.receipt_number} · {self.product} · {self.received_qty}"

    @property
    def quantity_variance(self):
        return self.received_qty - self.expected_qty


class StockReservation(models.Model):
    """Stock reserved for a specific order item before warehouse picking."""

    STATUS = [
        ("reserved", "Reserved"),
        ("released", "Released"),
        ("picked", "Picked"),
        ("fulfilled", "Fulfilled"),
        ("cancelled", "Cancelled"),
    ]

    inventory = models.ForeignKey(
        "deliveries.Inventory",
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="stock_reservations",
    )
    order_item = models.ForeignKey(
        "orders.OrderItem",
        on_delete=models.PROTECT,
        related_name="stock_reservations",
    )

    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="reserved",
        db_index=True,
    )

    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_reservations_created",
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_reservations_released",
    )
    picked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_reservations_picked",
    )

    reserved_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    picked_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-reserved_at", "-id"]
        indexes = [
            models.Index(fields=["inventory", "status"]),
            models.Index(fields=["order", "status"]),
            models.Index(fields=["order_item", "status"]),
        ]

    def __str__(self):
        return f"Reservation · {self.order_id} · {self.inventory.product_id} · {self.quantity}"


class StockMovement(models.Model):
    """Immutable audit trail of stock quantity changes."""

    MOVEMENT_TYPES = [
        ("receipt", "Receipt"),
        ("reservation", "Reservation"),
        ("release", "Reservation Release"),
        ("pick", "Pick"),
        ("unpick", "Unpick"),
        ("delivery", "Delivery"),
        ("return", "Return"),
        ("adjustment", "Adjustment"),
        ("damage", "Damage"),
        ("count_adjustment", "Count Adjustment"),
    ]

    inventory = models.ForeignKey(
        "deliveries.Inventory",
        on_delete=models.PROTECT,
        related_name="movements",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    movement_type = models.CharField(
        max_length=30,
        choices=MOVEMENT_TYPES,
        db_index=True,
    )

    # Signed quantity: positive adds physical stock; negative removes it.
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    quantity_before = models.DecimalField(max_digits=14, decimal_places=2)
    quantity_after = models.DecimalField(max_digits=14, decimal_places=2)

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements_performed",
    )
    performed_at = models.DateTimeField(default=now, db_index=True)

    receipt_item = models.ForeignKey(
        "deliveries.StockReceiptItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    reservation = models.ForeignKey(
        "deliveries.StockReservation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    picking_item = models.ForeignKey(
        "deliveries.PickingItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    delivery_stop_item = models.ForeignKey(
        "deliveries.DeliveryStopItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    reason = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at", "-id"]
        indexes = [
            models.Index(fields=["inventory", "performed_at"]),
            models.Index(fields=["product", "movement_type"]),
            models.Index(fields=["performed_by", "performed_at"]),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} · {self.product} · {self.quantity}"


class StockCount(models.Model):
    """A controlled physical stock count."""

    STATUS = [
        ("draft", "Draft"),
        ("in_progress", "In Progress"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("cancelled", "Cancelled"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="draft",
        db_index=True,
    )

    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_counts_started",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_counts_completed",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_counts_approved",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.reference} · {self.get_status_display()}"


class StockCountItem(models.Model):
    """One physical count line with its system quantity and variance."""

    count = models.ForeignKey(
        "deliveries.StockCount",
        on_delete=models.CASCADE,
        related_name="items",
    )
    inventory = models.ForeignKey(
        "deliveries.Inventory",
        on_delete=models.PROTECT,
        related_name="count_items",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_count_items",
    )

    system_qty = models.DecimalField(max_digits=14, decimal_places=2)
    counted_qty = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_count_items_counted",
    )
    counted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["count_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["count", "product"],
                name="unique_product_per_stock_count",
            )
        ]
        indexes = [
            models.Index(fields=["inventory", "count"]),
            models.Index(fields=["product", "count"]),
        ]

    def __str__(self):
        return f"{self.count.reference} · {self.product}"

    @property
    def variance(self):
        if self.counted_qty is None:
            return None
        return self.counted_qty - self.system_qty


# -----------------------------
# 2) WAREHOUSE: Picking
# -----------------------------


class PickingBatch(models.Model):
    """
    A warehouse picking batch for a single service date and wave (AM/PM).
    Completing a batch hands orders off to deliveries.
    """

    STATUS = [
        ("draft", "Draft"),
        ("in_progress", "In Progress"),
        ("complete", "Complete"),
        ("cancelled", "Cancelled"),
    ]

    # -------------------------------------------------
    # Core fields
    # -------------------------------------------------
    name = models.CharField(
        max_length=140,
        help_text="Human-friendly label, e.g. '2025-09-20 AM'.",
    )
    service_date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="draft",
        db_index=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picking_batches_created",
    )

    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picking_batches_started",
    )

    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picking_batches_completed",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-service_date", "-id"]
        indexes = [
            models.Index(fields=["service_date", "status"]),
        ]
        unique_together = [("name", "service_date")]

    def __str__(self) -> str:
        return f"{self.name} · {self.service_date} · {self.get_status_display()}"

    # -------------------------------------------------
    # Derived helpers
    # -------------------------------------------------
    @property
    def item_count(self) -> int:
        return self.items.count()

    @property
    def order_count(self) -> int:
        return self.items.values("order_id").distinct().count()

    @property
    def wave(self) -> str:
        """
        Infer AM/PM from the name.
        """
        label = (self.name or "").upper()
        if "PM" in label and "AM" not in label:
            return "PM"
        return "AM"

    # -------------------------------------------------
    # State transitions
    # -------------------------------------------------
    def mark_started(self, user=None):
        self.status = "in_progress"
        self.started_at = now()
        self.started_by = user if getattr(user, "is_authenticated", False) else None
        self.save(update_fields=["status", "started_at", "started_by", "updated_at"])

    def save(self, *args, **kwargs):
        old_status = None
        if self.pk:
            db = self._state.db or "default"

            old_status = (
                type(self)
                .objects.using(db)
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )

        super().save(*args, **kwargs)

        if old_status != "complete" and self.status == "complete":
            self._handoff_to_delivery()

    def mark_complete(self, user=None):
        self.status = "complete"
        if not self.completed_at:
            self.completed_at = now()
        self.completed_by = user if getattr(user, "is_authenticated", False) else None
        self.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])

    # -------------------------------------------------
    # IMPORTANT: used by Transactions
    # -------------------------------------------------
    def add_order(self, order):
        db = self._state.db or "default"

        for oi in order.items.using(db).select_related("product", "category"):
            PickingItem.objects.using(db).get_or_create(
                batch=self,
                order=order,
                order_item=oi,
                defaults={
                    "product_name": oi.product_name or (oi.product.name if oi.product_id else ""),
                    "sku": oi.sku or (oi.product.sku if oi.product_id else ""),
                    "uom": oi.uom or "",
                    "expected_qty": oi.quantity or Decimal("0.00"),
                },
            )

    # -------------------------------------------------
    # DELIVERY HANDOFF (KEY LOGIC)
    # -------------------------------------------------
    def _handoff_to_delivery(self):
        DeliveryRun = apps.get_model("deliveries", "DeliveryRun")
        DeliveryStop = apps.get_model("deliveries", "DeliveryStop")
        DeliveryStopItem = apps.get_model("deliveries", "DeliveryStopItem")
        Order = apps.get_model("orders", "Order")

        db = self._state.db or "default"

        target_date = _delivery_date_for(self.service_date, self.wave)
        depot_label, depot_lat, depot_lng = DEPOT_PREFERENCE[0]

        with transaction.atomic(using=db):

            # =========================================================
            # 1. CREATE / REUSE DELIVERY RUN
            # =========================================================

            run, _ = DeliveryRun.objects.using(db).get_or_create(
                service_date=target_date,
                name=self.name or f"{target_date.isoformat()} Run",
                defaults={
                    "status": "planned",
                    "start_time": DELIVERY_START_TIME,

                    # Kept for existing DeliveryRun data / admin.
                    # The actual route will now start and end at
                    # the selected driver's address.
                    "depot_label": depot_label,
                    "depot_lat": depot_lat,
                    "depot_lng": depot_lng,
                },
            )

            # =========================================================
            # 2. REMOVE RETURN / DEPOT STOP
            #
            # The route no longer ends at the depot.
            #
            # Actual route:
            #
            # DRIVER ADDRESS
            #       ↓
            # SUPPLIER(S)
            #       ↓
            # CUSTOMER(S)
            #       ↓
            # DRIVER ADDRESS
            # =========================================================

            run.stops.using(db).filter(
                stop_type="RETURN"
            ).delete()

            # =========================================================
            # 3. SUPPLIER STOPS — LEGACY ONLY
            #
            # Existing supplier DeliveryStop records are retained for
            # historical data. New delivery runs no longer create or
            # route through supplier stops. Supplier selection now
            # belongs to procurement / StockReceipt.
            # =========================================================

            # =========================================================
            # 3. GET ALL ORDERS IN THIS PICKING BATCH
            # =========================================================

            order_ids = list(
                self.items.using(db)
                .values_list(
                    "order_id",
                    flat=True,
                )
                .distinct()
            )

            # =========================================================
            # 4. LOAD ORDERS AND THEIR CLIENTS
            #
            # IMPORTANT:
            #
            # We are NOT grouping by order.
            #
            # We are grouping by CLIENT.
            #
            # Therefore:
            #
            # Client A
            #   Order 1
            #   Order 2
            #   Order 3
            #
            # becomes ONE physical DeliveryStop.
            # =========================================================

            orders = list(
                Order.objects.using(db)
                .filter(id__in=order_ids)
                .select_related("client", "end_user")
            )

            orders_by_destination = {}

            for order in orders:

                if not order.client_id:
                    continue

                # A normal TDM order has no End User, so it remains
                # grouped by Client exactly as before.
                #
                # Where an End User exists, the physical delivery
                # destination is the End User. This means multiple
                # End Users belonging to the same Client become
                # separate physical delivery stops.
                destination_key = (
                    order.client_id,
                    order.end_user_id,
                )

                orders_by_destination.setdefault(
                    destination_key,
                    []
                ).append(order)

            # =========================================================
            # 5. CREATE / REUSE ONE CUSTOMER STOP PER DESTINATION
            # =========================================================
            #
            # Destination = Client + End User
            #
            # For ordinary TDM orders:
            #   Client A + no End User
            #       -> ONE physical stop
            #
            # For funeral / End User orders:
            #   Client A + End User 1
            #       -> ONE physical stop
            #
            #   Client A + End User 2
            #       -> DIFFERENT physical stop
            #
            # Multiple orders for the SAME Client + SAME End User
            # remain grouped into ONE physical stop.
            # =========================================================

            for (client_id, end_user_id), destination_orders in orders_by_destination.items():

                # -----------------------------------------------------
                # Look for an existing CUSTOMER stop for this exact
                # physical destination on this delivery run.
                # -----------------------------------------------------

                destination_filter = {
                    "stop_type": "CUSTOMER",
                    "order__client_id": client_id,
                }

                if end_user_id:
                    destination_filter["end_user_id"] = end_user_id
                else:
                    destination_filter["end_user__isnull"] = True

                stop = (
                    run.stops.using(db)
                    .filter(**destination_filter)
                    .select_related("order", "end_user")
                    .first()
                )

                # -----------------------------------------------------
                # If there is no existing stop, create ONE using the
                # first order as the representative order.
                #
                # The other orders are NOT lost.
                #
                # Their items will be attached to this same stop
                # through DeliveryStopItem below.
                # -----------------------------------------------------

                if stop is None:

                    representative_order = destination_orders[0]

                    stop = DeliveryStop.objects.using(db).create(
                        run=run,
                        order=representative_order,
                        end_user_id=end_user_id,
                        status="assigned",
                        sequence=0,
                        stop_type="CUSTOMER",
                    )

                    # Copy the End User's delivery details when the
                    # order has an End User. Otherwise fall back to
                    # the Client's delivery details.
                    stop.snapshot_from_order()

                    stop.save(
                        using=db,
                        update_fields=[
                            "end_user",
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
                        ],
                    )

                else:

                    # -------------------------------------------------
                    # Existing customer stop.
                    #
                    # Refresh the snapshot from the representative
                    # order so the physical destination remains
                    # current.
                    # -------------------------------------------------

                    stop.snapshot_from_order()

                    stop.save(
                        using=db,
                        update_fields=[
                            "end_user",
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
                        ],
                    )

                # =====================================================
                # 6. ADD ALL ITEMS FROM ALL ORDERS FOR THIS DESTINATION
                #    TO THE SAME DELIVERY STOP
                # =====================================================

                destination_order_ids = [
                    order.id
                    for order in destination_orders
                ]

                destination_picking_items = (
                    self.items.using(db)
                    .filter(
                        order_id__in=destination_order_ids
                    )
                )

                for pi in destination_picking_items:

                    planned = (
                        pi.picked_qty
                        or pi.expected_qty
                        or Decimal("0.00")
                    )

                    DeliveryStopItem.objects.using(db).get_or_create(
                        stop=stop,
                        order_item_id=pi.order_item_id,
                        defaults={
                            "product_name": pi.product_name,
                            "sku": pi.sku,
                            "uom": pi.uom,
                            "planned_qty": planned,
                            "loaded_qty": (
                                pi.picked_qty
                                or Decimal("0.00")
                            ),
                            "delivered_qty": Decimal("0.00"),
                        },
                    )

                # Make sure the stop is assigned.
                if stop.status in ("pending", ""):
                    stop.status = "assigned"
                    stop.save(
                        using=db,
                        update_fields=[
                            "status",
                            "updated_at",
                        ],
                    )

            # =========================================================
            # 7. UPDATE ORDER STATUS
            #
            # All orders in the Picking Batch are moved to
            # ready_for_delivery.
            # =========================================================

            Order.objects.using(db).filter(
                id__in=order_ids
            ).exclude(
                status__in=[
                    "out_for_delivery",
                    "complete",
                    "returned",
                    "cancelled",
                ]
            ).update(
                status="ready_for_delivery"
            )

            # =========================================================
            # 8. RE-CALCULATE RUN TOTALS
            # =========================================================

            run.recalc_aggregates(
                save=True
            ) 


    # -------------------------------------------------
    # Wave helper
    # -------------------------------------------------

    @classmethod
    def get_or_create_wave(cls, *, service_date, wave: str, db="default"):
        assert wave in ("AM", "PM")

        base_name = f"{service_date.isoformat()} {wave}"

        open_qs = cls.objects.using(db).filter(
            service_date=service_date,
            status__in=["draft", "in_progress"],
            name__startswith=base_name,
        ).order_by("created_at")

        if open_qs.exists():
            return open_qs.last(), False

        name = base_name
        suffix = 1

        while cls.objects.using(db).filter(service_date=service_date, name=name).exists():
            suffix += 1
            name = f"{base_name} #{suffix}"

        batch = cls.objects.using(db).create(
            service_date=service_date,
            name=name,
            status="draft",
        )

        return batch, True


class PickingItem(models.Model):
    """
    A single pick line derived from an OrderItem.

    Picking semantics:
    - Picking is now a warehouse stock operation.
    - Stock is supplied from Inventory / StockReservation.
    - Supplier fields below are retained only for legacy historical rows.
    - New PickingItems do not select suppliers from ProductPricing.
    """

    # --------------------------------------------------
    # Core relations
    # --------------------------------------------------
    batch = models.ForeignKey(
        "deliveries.PickingBatch",
        on_delete=models.CASCADE,
        related_name="items",
    )

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="picking_items",
    )

    order_item = models.ForeignKey(
        "orders.OrderItem",
        on_delete=models.CASCADE,
        related_name="picking_items",
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        null=True,          # MUST remain nullable for legacy rows
        blank=True,
        editable=False,     # 🔒 locked forever
        related_name="picking_items",
    )

    # --------------------------------------------------
    # Snapshot fields
    # --------------------------------------------------
    product_name = models.CharField(max_length=220)
    sku = models.CharField(max_length=64, blank=True)
    uom = models.CharField(max_length=16, blank=True)

    expected_qty = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    picked_qty = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # --------------------------------------------------
    # 💰 Pricing snapshots
    # --------------------------------------------------
    expected_supplier_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Expected supplier price INCL VAT at time of picking.",
    )

    actual_supplier_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Actual supplier price INCL VAT as invoiced.",
    )

    is_picked = models.BooleanField(
        default=False,
        help_text="Quantity physically picked from warehouse stock.",
    )

    picked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picking_items_picked",
    )
    picked_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --------------------------------------------------
    # Meta
    # --------------------------------------------------
    class Meta:
        ordering = ["batch_id", "order_id", "id"]
        unique_together = [("batch", "order_item")]
        indexes = [
            models.Index(fields=["batch", "order"]),
            models.Index(fields=["supplier"]),
            models.Index(fields=["is_picked"]),
        ]

    def __str__(self) -> str:
        return f"{self.product_name} · x{self.expected_qty}"

    # --------------------------------------------------
    # Validation
    # --------------------------------------------------
    def clean(self):
        super().clean()

        if self.picked_qty > self.expected_qty:
            raise ValidationError({
                "picked_qty": "Picked quantity cannot exceed expected quantity."
            })

    # --------------------------------------------------
    # Save override — CRITICAL PART
    # --------------------------------------------------
    def save(self, *args, **kwargs):
        is_create = self.pk is None

        # --------------------------------------------
        # 🛑 Admin safety: strip invalid supplier=0
        # --------------------------------------------
        if self.supplier_id in (0, "0"):
            self.supplier_id = None

        # --------------------------------------------
        # UPDATE: restore immutable snapshot fields
        # --------------------------------------------
        if not is_create:
            db = self._state.db or "default"

            original = (
                type(self)
                .objects.using(db)
                .filter(pk=self.pk)
                .values(
                    "supplier_id",
                    "expected_supplier_price",
                )
                .first()
            )

            if original:
                self.supplier_id = original["supplier_id"]
                self.expected_supplier_price = original["expected_supplier_price"]

            # ❗ DO NOT full_clean on update
            super().save(*args, **kwargs)
            return

        # --------------------------------------------
        # CREATE: snapshot product identity only
        # --------------------------------------------
        if not self.order_item_id:
            raise ValidationError("PickingItem must be linked to an OrderItem.")

        product = self.order_item.product

        self.product_name = self.product_name or product.name
        self.sku = self.sku or product.sku or ""
        self.uom = self.uom or product.uom or ""

        # New picking rows are fulfilled from warehouse inventory.
        # Supplier / supplier-price fields are deliberately left blank
        # so a price-list change can never redirect a warehouse pick.
        self.supplier = None
        self.expected_supplier_price = None

        self.full_clean()
        super().save(*args, **kwargs)



    # --------------------------------------------------
    # Derived helpers
    # --------------------------------------------------
    @property
    def price_variance(self) -> Optional[Decimal]:
        if self.actual_supplier_price is None or self.expected_supplier_price is None:
            return None
        return self.actual_supplier_price - self.expected_supplier_price

    @property
    def has_price_discrepancy(self) -> bool:
        return (
            self.actual_supplier_price is not None
            and self.expected_supplier_price is not None
            and self.actual_supplier_price != self.expected_supplier_price
        )

    # --------------------------------------------------
    # Picking action
    # --------------------------------------------------
    def mark_picked(self, qty: Optional[Decimal] = None, user=None):
        self.picked_qty = qty if qty is not None else self.expected_qty
        self.is_picked = True
        self.picked_by = user if getattr(user, "is_authenticated", False) else self.picked_by
        self.picked_at = now()

        self.full_clean()
        self.save(update_fields=[
            "picked_qty",
            "is_picked",
            "picked_by",
            "picked_at",
            "updated_at",
        ])


# -----------------------------
# 2) FLEET: Delivery Run
# -----------------------------

def pod_upload_to(instance: "DeliveryStop", filename: str) -> str:
    return f"delivery/pod/{instance.run_id or 'no-run'}/{instance.id or 'new'}/{filename}"


class DeliveryRun(models.Model):
    STATUS = [
        ("draft", "Draft"),
        ("planned", "Planned"),
        ("en_route", "En Route"),
        ("paused", "Paused"),
        ("complete", "Complete"),
        ("cancelled", "Cancelled"),
    ]

    service_date = models.DateField(db_index=True)
    name = models.CharField(max_length=140, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="draft",
        db_index=True,
    )

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_runs",
    )

    vehicle = models.ForeignKey(
        "deliveries.Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_runs",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_runs_created",
    )
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_runs_dispatched",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_runs_completed",
    )

    # LEGACY: retained for existing runs; new routes do not start at suppliers.
    start_supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_runs_started_from",
    )

    start_location_label = models.CharField(
        max_length=140,
        blank=True,
    )

    start_lat = models.FloatField(
        null=True,
        blank=True,
    )

    start_lng = models.FloatField(
        null=True,
        blank=True,
    )

    # Depot
    depot_label = models.CharField(max_length=140, blank=True)
    depot_lat = models.FloatField(null=True, blank=True)
    depot_lng = models.FloatField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)

    # ============================
    # RATE SNAPSHOTS (PER KM)
    # ============================
    driver_rate_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    assistant_rate_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    total_rate_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # ============================
    # AGGREGATES
    # ============================
    total_distance_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    total_drive_min = models.PositiveIntegerField(null=True, blank=True)
    stop_count = models.PositiveIntegerField(default=0)

    # ============================
    # COST SNAPSHOTS (TOTAL)
    # ============================
    driver_total_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Driver cost = driver_rate_per_km × total_distance_km",
    )

    assistant_total_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Assistant cost = assistant_rate_per_km × total_distance_km",
    )

    overall_total_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total delivery cost (driver + assistant)",
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-service_date", "-id"]
        indexes = [
            models.Index(fields=["service_date", "status"]),
            models.Index(fields=["driver"]),
        ]

    # ============================
    # RATE APPLICATION
    # ============================
    def apply_delivery_rates(self, save=True):
        db = self._state.db or "default"

        if not self.vehicle:
            return

        if self.vehicle.is_internal:
            rate = InternalDeliveryRate.objects.using(db).filter(is_active=True).first()
        else:
            rate = ExternalDeliveryRate.objects.using(db).filter(is_active=True).first()

        if not rate:
            raise ValidationError("No active delivery rate found.")

        self.driver_rate_per_km = rate.driver_per_km
        self.assistant_rate_per_km = rate.assistant_per_km
        self.total_rate_per_km = rate.driver_per_km + rate.assistant_per_km

        if save:
            self.save(update_fields=[
                "driver_rate_per_km",
                "assistant_rate_per_km",
                "total_rate_per_km",
                "updated_at",
            ])

    # ============================
    # COST CALCULATION
    # ============================
    def calculate_total_costs(self):
        """
        Calculates total costs WITHOUT saving.
        Safe to call from save() or admin actions.
        """

        if not self.total_distance_km:
            self.driver_total_cost = None
            self.assistant_total_cost = None
            self.overall_total_cost = None
            return

        if self.driver_rate_per_km:
            self.driver_total_cost = (
                Decimal(self.driver_rate_per_km) * Decimal(self.total_distance_km)
            )
        else:
            self.driver_total_cost = None

        if self.assistant_rate_per_km:
            self.assistant_total_cost = (
                Decimal(self.assistant_rate_per_km) * Decimal(self.total_distance_km)
            )
        else:
            self.assistant_total_cost = None

        if self.driver_total_cost is not None and self.assistant_total_cost is not None:
            self.overall_total_cost = (
                self.driver_total_cost + self.assistant_total_cost
            )
        else:
            self.overall_total_cost = None




    # ============================
    # SAVE HOOK
    # ============================
    def save(self, *args, **kwargs):
        apply_rates = (
            self.vehicle is not None and
            self.total_rate_per_km is None
        )

        super().save(*args, **kwargs)

        if apply_rates:
            self.apply_delivery_rates(save=False)

        self.calculate_total_costs()

        super().save(update_fields=[
            "driver_rate_per_km",
            "assistant_rate_per_km",
            "total_rate_per_km",
            "driver_total_cost",
            "assistant_total_cost",
            "overall_total_cost",
            "updated_at",
        ])


    def recalc_aggregates(self, save=False):
        db = self._state.db or "default"

        qs = getattr(self, "stops", None)

        if qs is not None:
            agg = qs.using(db).aggregate(
                stop_count=Count("id"),
                total_distance=Sum("distance_km"),
                total_drive_min=Sum("drive_min"),
            )

            self.stop_count = agg["stop_count"] or 0
            self.total_distance_km = agg["total_distance"] or Decimal("0.00")
            self.total_drive_min = agg["total_drive_min"] or 0

        self.calculate_total_costs()

        if save:
            self.save(update_fields=[
                "stop_count",
                "total_distance_km",
                "total_drive_min",
                "driver_total_cost",
                "assistant_total_cost",
                "overall_total_cost",
                "updated_at",
            ])

    @property
    def has_depot_geo(self):
        """
        Returns True if the run has valid depot coordinates.
        Used by route planning / auto-sequencing.
        """
        return self.depot_lat is not None and self.depot_lng is not None





# -----------------------------
# 3) STOPS & POD (Proof of Delivery)
# -----------------------------

def pod_upload_to(instance, filename):
    """
    Proof-of-delivery upload path.
    Example:
    deliveries/run_12/stop_45/signature.png
    """
    return (
        f"deliveries/"
        f"run_{instance.run_id}/"
        f"stop_{instance.id or 'new'}/"
        f"{filename}"
    )


class DeliveryStop(models.Model):
    """
    One physical stop on a delivery run.

    Can represent:
      - Start
      - Supplier pickup
      - Customer delivery
      - Return to depot
    """

    # -----------------------------
    # Status & Type
    # -----------------------------
    STATUS = [
        ("pending", "Pending"),
        ("assigned", "Assigned"),
        ("en_route", "En Route"),
        ("awaiting_completion", "Awaiting Completion"),
        ("delivered", "Delivered"),
        ("failed", "Failed Attempt"),
        ("cancelled", "Cancelled"),
    ]

    STOP_TYPE = [
        ("START", "Start / Departure"),
        ("SUPPLIER", "Supplier Pickup"),
        ("CUSTOMER", "Customer Delivery"),
        ("RETURN", "Return to Driver"),

    ]

    stop_type = models.CharField(
        max_length=20,
        choices=STOP_TYPE,
        default="CUSTOMER",
        db_index=True,
    )

    # -----------------------------
    # Core relations
    # -----------------------------
    run = models.ForeignKey(
        DeliveryRun,
        on_delete=models.CASCADE,
        related_name="stops",
    )

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="delivery_stops",
        null=True,
        blank=True,
    )

    end_user = models.ForeignKey(
        "clients.EndUser",
        on_delete=models.SET_NULL,
        related_name="delivery_stops",
        null=True,
        blank=True,
        help_text="End user receiving the delivery, where applicable.",
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="delivery_stops",
    )

    # -----------------------------
    # Routing / state
    # -----------------------------
    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="pending",
        db_index=True,
    )

    sequence = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Route order (1..N).",
    )

    # -----------------------------
    # Address & contact snapshot
    # -----------------------------
    customer_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)

    address_line1 = models.CharField(max_length=220, blank=True)
    address_line2 = models.CharField(max_length=220, blank=True)
    suburb = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    province = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=120, blank=True)

    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)

    service_min = models.PositiveIntegerField(
        default=5,
        help_text="Expected time on site (minutes).",
    )

    # -----------------------------
    # Routing outputs
    # -----------------------------
    eta = models.DateTimeField(null=True, blank=True)
    distance_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )
    drive_min = models.PositiveIntegerField(null=True, blank=True)

    # -----------------------------
    # Proof of delivery / pickup
    # -----------------------------
    recipient_name = models.CharField(max_length=160, blank=True)
    recipient_id_no = models.CharField(max_length=80, blank=True)
    signature = models.ImageField(upload_to=pod_upload_to, blank=True, null=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    delivery_notes = models.TextField(blank=True)

    # -----------------------------
    # Exceptions
    # -----------------------------
    failed_reason = models.CharField(max_length=220, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    # -----------------------------
    # Audit
    # -----------------------------
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_stops_created",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_stops_updated",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # -----------------------------
    # Snapshot helpers
    # -----------------------------
    def snapshot_from_supplier(self):
        if not self.supplier:
            return

        s = self.supplier
        self.customer_name = s.name
        self.address_line1 = s.address_line1 or ""
        self.address_line2 = s.address_line2 or ""
        self.suburb = getattr(s, "suburb", "") or ""
        self.city = s.city or ""
        self.province = s.province or ""
        self.postal_code = s.postal_code or ""
        self.country = s.country or ""
        self.lat = s.delivery_lat
        self.lng = s.delivery_lng

    def snapshot_from_order(self):
        if not self.order:
            return

        # ---------------------------------------------------------
        # End User delivery
        # ---------------------------------------------------------
        # When an order is linked to an End User, the End User is
        # the physical recipient / delivery destination.
        #
        # The Client remains the commercial account on the Order.
        # ---------------------------------------------------------
        end_user = getattr(self.order, "end_user", None)

        if end_user:
            self.end_user = end_user
            self.customer_name = end_user.full_name
            self.phone = end_user.phone or end_user.whatsapp or ""
            self.email = end_user.email or ""

            self.address_line1 = end_user.address_line1 or ""
            self.address_line2 = end_user.address_line2 or ""
            self.suburb = end_user.suburb or ""
            self.city = end_user.city or ""

            self.province = (
                end_user.get_province_display()
                if end_user.province
                else ""
            )

            self.postal_code = end_user.postal_code or ""
            self.country = end_user.country or ""

            self.lat = (
                float(end_user.latitude)
                if end_user.latitude is not None
                else None
            )
            self.lng = (
                float(end_user.longitude)
                if end_user.longitude is not None
                else None
            )

            return

        # ---------------------------------------------------------
        # Existing Client delivery
        # ---------------------------------------------------------
        # If there is no End User, preserve the existing TDM
        # Client-based delivery behaviour.
        # ---------------------------------------------------------
        self.end_user = None

        c = self.order.client
        self.customer_name = str(c)
        self.phone = getattr(c, "phone", "") or ""
        self.email = getattr(c, "email", "") or ""

        self.address_line1 = c.delivery_address_line1 or c.address_line1 or ""
        self.address_line2 = c.delivery_address_line2 or c.address_line2 or ""
        self.suburb = c.delivery_suburb or c.suburb or ""
        self.city = c.delivery_city or c.city or ""

        prov_disp = getattr(c, "get_delivery_province_display", None)
        self.province = (
            prov_disp()
            if callable(prov_disp)
            else (c.delivery_province or c.province or "")
        )

        self.postal_code = c.delivery_postal_code or c.postal_code or ""
        self.country = c.delivery_country or c.country or ""
        self.lat = c.delivery_lat
        self.lng = c.delivery_lng

    # -----------------------------
    # Helpers
    # -----------------------------
    def address_one_line(self) -> str:
        parts = [
            self.address_line1,
            self.address_line2,
            self.suburb,
            self.city,
            self.province,
            self.postal_code,
        ]
        return ", ".join([p for p in parts if p])

    @property
    def has_geo(self):
        return self.lat is not None and self.lng is not None

    # -----------------------------
    # Meta
    # -----------------------------
    class Meta:
        ordering = ["run_id", "sequence", "id"]
        indexes = [
            models.Index(fields=["end_user", "status"]),
            models.Index(fields=["run", "end_user"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "order"],
                condition=models.Q(order__isnull=False),
                name="unique_order_per_run",
            ),
            models.UniqueConstraint(
                fields=["run", "supplier"],
                condition=models.Q(
                    supplier__isnull=False,
                    stop_type="SUPPLIER",
                ),
                name="unique_supplier_per_run",
            ),
        ]

    def __str__(self):
        if self.stop_type == "SUPPLIER" and self.supplier:
            label = self.supplier.name
        elif self.customer_name:
            label = self.customer_name
        else:
            label = f"Order #{self.order_id}"
        return f"{self.run.service_date} · {label} · {self.get_status_display()}"
    



class DeliveryStopItem(models.Model):
    """
    Optional per-stop item tracking (load vs delivered).
    Useful for shortages/returns tracking.
    """
    stop = models.ForeignKey(DeliveryStop, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey("orders.OrderItem", on_delete=models.PROTECT, related_name="delivery_stop_items")

    product_name = models.CharField(max_length=220)
    sku = models.CharField(max_length=64, blank=True)
    uom = models.CharField(max_length=16, blank=True)

    planned_qty = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    loaded_qty = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))]
    )
    delivered_qty = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))]
    )

    shortage_reason = models.CharField(max_length=220, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stop_id", "id"]
        unique_together = [("stop", "order_item")]

    def __str__(self) -> str:
        return f"{self.product_name} x{self.planned_qty} @ stop {self.stop_id}"

    @property
    def variance(self) -> Decimal:
        return (self.delivered_qty or Decimal("0.00")) - (self.planned_qty or Decimal("0.00"))




class DriverLocation(models.Model):
    run = models.ForeignKey(
        DeliveryRun,
        on_delete=models.CASCADE,
        related_name="locations"
    )
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    lat = models.FloatField()
    lng = models.FloatField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    
    

    def clean(self):
        if self.run.driver_id != self.driver_id:
            raise ValidationError(
                "Driver does not match the assigned driver for this run."
            )

    class Meta:
        ordering = ["recorded_at"]
        indexes = [
            models.Index(fields=["run", "recorded_at"]),
            models.Index(fields=["driver", "recorded_at"]),
        ]


class RunEvent(models.Model):
    EVENT_TYPES = [
        ("START", "Run Started"),
        ("STOP_ARRIVED", "Arrived at Stop"),
        ("DELIVERED", "Delivered"),
        ("FAILED", "Delivery Failed"),
    ]

    run = models.ForeignKey(
        DeliveryRun,
        on_delete=models.CASCADE,
        related_name="events"
    )

    stop = models.ForeignKey(
        DeliveryStop,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )

    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPES,
    )

    recorded_at = models.DateTimeField(auto_now_add=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["recorded_at"]
        indexes = [
            models.Index(fields=["run", "event_type"]),
        ]


class Vehicle(models.Model):
    VEHICLE_TYPES = [
        ("bakkie", "Bakkie"),
        ("van", "Van"),
        ("truck", "Truck"),
        ("bike", "Motorbike"),
        ("other", "Other"),
    ]

    STATUS = [
        ("active", "Active"),
        ("maintenance", "In Maintenance"),
        ("inactive", "Inactive"),
    ]

    label = models.CharField(
        max_length=80,
        help_text="Friendly name, e.g. 'Bakkie 1'"
    )

    registration_number = models.CharField(
        max_length=20,
        unique=True,
        help_text="Vehicle registration number"
    )

    vehicle_type = models.CharField(
        max_length=20,
        choices=VEHICLE_TYPES,
        default="bakkie",
    )

    capacity_kg = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Optional load capacity"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="active",
        db_index=True,
    )

    notes = models.TextField(blank=True)

    is_internal = models.BooleanField(
        default=True,
        help_text="True if this vehicle is owned/operated internally by the company"
    )


    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["vehicle_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} · {self.registration_number}"


class InternalDeliveryRate(models.Model):
    """
    Per-km costing when using company-owned vehicles
    """

    name = models.CharField(
        max_length=100,
        help_text="e.g. 'Internal Bakkie Rate'"
    )

    driver_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Driver cost per km"
    )

    assistant_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Assistant cost per km"
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_per_km(self):
        return self.driver_per_km + self.assistant_per_km




class ExternalDeliveryRate(models.Model):
    """
    Per-km costing for owner-driver / partner vehicles
    """

    name = models.CharField(
        max_length=100,
        help_text="e.g. 'Partner Bakkie Rate'"
    )

    driver_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Driver cost per km (partner)"
    )

    assistant_per_km = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Assistant cost per km (partner)"
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_per_km(self):
        return self.driver_per_km + self.assistant_per_km



