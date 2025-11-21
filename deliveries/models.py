# deliveries/models.py
from __future__ import annotations

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

class PickingBatch(models.Model):
    """
    A warehouse picking batch for a single service date and typically a wave (AM/PM).
    Orders can be appended into an existing open batch.
    """
    STATUS = [
        ("draft", "Draft"),
        ("in_progress", "In Progress"),
        ("complete", "Complete"),
        ("cancelled", "Cancelled"),
    ]

    name = models.CharField(max_length=140, help_text="Human-friendly label, e.g. '2025-09-20 AM'.")
    service_date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS, default="draft", db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="picking_batches_created"
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

    @property
    def item_count(self) -> int:
        return self.items.count()

    @property
    def order_count(self) -> int:
        return self.items.values("order_id").distinct().count()

    @property
    def wave(self) -> str:
        """
        Infer AM/PM from the name. If 'PM' is present (and not 'AM'), return PM; otherwise AM.
        """
        label = (self.name or "").upper()
        if "PM" in label and "AM" not in label:
            return "PM"
        if "AM" in label:
            return "AM"
        # Default to AM if not explicit
        return "AM"

    def mark_started(self, user=None):
        self.status = "in_progress"
        self.started_at = now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    # Always detect a transition to 'complete' on save (covers admin edits & API)
    def save(self, *args, **kwargs):
        old_status = None
        if self.pk:
            old_status = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
        super().save(*args, **kwargs)
        if old_status != "complete" and self.status == "complete":
            self._handoff_to_delivery()

    # Convenience: append all items for an Order into this batch
    def add_order(self, order: "orders.Order"):
        """
        Creates PickingItem rows from an order's current OrderItems.
        Snapshots qty/name/sku so pickers work off a stable list.
        """
        for oi in order.items.select_related("product", "category"):
            PickingItem.objects.get_or_create(
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

    def mark_complete(self, user=None):
        """
        Public method that flips status to 'complete'.
        The actual handoff is triggered by save() when the transition occurs.
        """
        self.status = "complete"
        if not self.completed_at:
            self.completed_at = now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def _handoff_to_delivery(self):
        """
        Warehouse → Fleet handoff executed when a batch transitions to 'complete':
          - Compute the correct delivery date from (service_date, wave).
          - Create/reuse a DeliveryRun for that date (07:30 start, preferred depot).
          - Create a DeliveryStop per distinct order in this batch (no duplicates across the date).
          - Seed stop items from the batch's picking lines.
          - Mark orders as 'ready_for_delivery'.
        """
        DeliveryRun = apps.get_model("deliveries", "DeliveryRun")
        DeliveryStop = apps.get_model("deliveries", "DeliveryStop")
        DeliveryStopItem = apps.get_model("deliveries", "DeliveryStopItem")
        Order = apps.get_model("orders", "Order")

        # 1) Choose delivery date from AM/PM policy
        target_date = _delivery_date_for(self.service_date, self.wave)

        # 2) Depot priority (can be made dynamic later)
        depot_label, depot_lat, depot_lng = DEPOT_PREFERENCE[0]

        with transaction.atomic():
            # 3) Create/reuse a run for that date; name shows wave (batch name)
            run, _ = DeliveryRun.objects.get_or_create(
                service_date=target_date,
                name=self.name or f"{target_date.isoformat()} Run",
                defaults={
                    "status": "planned",
                    "start_time": DELIVERY_START_TIME,
                    "depot_label": depot_label,
                    "depot_lat": depot_lat,
                    "depot_lng": depot_lng,
                },
            )

            # 4) Distinct orders in this batch
            order_ids = list(self.items.values_list("order_id", flat=True).distinct())

            # Avoid duplicates across ANY run on that service_date
            # Avoid duplicates on THIS run (enough to satisfy the unique_together)
            existing_in_run = set(
                run.stops.filter(order_id__in=order_ids).values_list("order_id", flat=True)
            )

            # Next sequence number (not unique, just orderly)
            next_seq = (run.stops.aggregate(m=Max("sequence"))["m"] or 0) + 1

            for oid in order_ids:
                if oid in existing_in_run:
                    continue

                try:
                    stop, created = DeliveryStop.objects.get_or_create(
                        run=run,
                        order_id=oid,
                        defaults={
                            "status": "assigned",
                            "sequence": next_seq,
                        },
                    )
                    if created:
                        next_seq += 1
                        # Snapshot address/contact for stability
                        stop.snapshot_from_order()
                        stop.save(update_fields=[
                            "customer_name","phone","email",
                            "address_line1","address_line2","suburb","city",
                            "province","postal_code","country","updated_at",
                        ])

                        # Seed stop items from this batch’s picking lines
                        batch_lines = self.items.filter(order_id=oid).select_related("order_item")
                        for pi in batch_lines:
                            planned = (pi.picked_qty or pi.expected_qty or Decimal("0.00"))
                            DeliveryStopItem.objects.get_or_create(
                                stop=stop,
                                order_item_id=pi.order_item_id,
                                defaults={
                                    "product_name": pi.product_name,
                                    "sku": pi.sku,
                                    "uom": pi.uom,
                                    "planned_qty": planned,
                                    "loaded_qty": (pi.picked_qty or Decimal("0.00")),
                                    "delivered_qty": Decimal("0.00"),
                                },
                            )
                except IntegrityError:
                    # Another request created the same (run, order) concurrently; just skip
                    continue


                # Snapshot address/contact for stability
                stop.snapshot_from_order()
                stop.save(update_fields=[
                    "customer_name", "phone", "email",
                    "address_line1", "address_line2", "suburb", "city",
                    "province", "postal_code", "country", "updated_at",
                ])

                # 5) Seed stop items from this batch’s picking lines
                batch_lines = self.items.filter(order_id=oid).select_related("order_item")
                for pi in batch_lines:
                    planned = (pi.picked_qty or pi.expected_qty or Decimal("0.00"))
                    DeliveryStopItem.objects.get_or_create(
                        stop=stop,
                        order_item_id=pi.order_item_id,
                        defaults={
                            "product_name": pi.product_name,
                            "sku": pi.sku,
                            "uom": pi.uom,
                            "planned_qty": planned,
                            "loaded_qty": (pi.picked_qty or Decimal("0.00")),
                            "delivered_qty": Decimal("0.00"),
                        },
                    )

            # 6) Mark orders ready for delivery (don’t override later stages)
            Order.objects.filter(id__in=order_ids).exclude(
                status__in=["out_for_delivery", "complete", "returned", "cancelled"]
            ).update(status="ready_for_delivery")

            # 7) Refresh run aggregates
            run.recalc_aggregates(save=True)

    @classmethod
    def get_or_create_wave(cls, *, service_date, wave: str):
        """
        Return an open (draft/in_progress) batch for service_date + wave ('AM'/'PM').
        If none is open, create one. If the base name exists but is closed, create '#2', '#3', etc.
        """
        assert wave in ("AM", "PM")
        base_name = f"{service_date.isoformat()} {wave}"

        # Prefer an open batch for this wave
        open_qs = cls.objects.filter(
            service_date=service_date,
            status__in=["draft", "in_progress"],
            name__startswith=base_name,
        ).order_by("created_at")

        if open_qs.exists():
            return open_qs.last(), False  # (batch, created=False)

        # Create new (avoid name collision if earlier wave was closed)
        name = base_name
        suffix = 1
        while cls.objects.filter(service_date=service_date, name=name).exists():
            suffix += 1
            name = f"{base_name} #{suffix}"

        batch = cls.objects.create(service_date=service_date, name=name, status="draft")
        return batch, True


class PickingItem(models.Model):
    """
    A single pick line derived from an OrderItem.
    """
    batch = models.ForeignKey(PickingBatch, on_delete=models.CASCADE, related_name="items")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="picking_items")
    order_item = models.ForeignKey("orders.OrderItem", on_delete=models.CASCADE, related_name="picking_items")

    product_name = models.CharField(max_length=220)
    sku = models.CharField(max_length=64, blank=True)
    uom = models.CharField(max_length=16, blank=True)

    expected_qty = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    picked_qty = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))]
    )

    is_picked = models.BooleanField(default=False, help_text="Checked off by warehouse.")
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["batch_id", "order_id", "id"]
        indexes = [
            models.Index(fields=["batch", "order"]),
        ]
        unique_together = [("batch", "order_item")]

    def __str__(self) -> str:
        return f"{self.product_name} ({self.sku or 'no-sku'}) · x{self.expected_qty}"

    def mark_picked(self, qty: Optional[Decimal] = None):
        """
        Mark this line picked. If qty omitted, assume fully picked.
        """
        if qty is None:
            self.picked_qty = self.expected_qty
        else:
            self.picked_qty = max(Decimal("0.00"), qty)
        self.is_picked = True
        self.save(update_fields=["picked_qty", "is_picked", "updated_at"])


# -----------------------------
# 2) FLEET: Delivery Run
# -----------------------------

def pod_upload_to(instance: "DeliveryStop", filename: str) -> str:
    return f"delivery/pod/{instance.run_id or 'no-run'}/{instance.id or 'new'}/{filename}"


class DeliveryRun(models.Model):
    """
    A single driver's run/route for a day.
    """
    STATUS = [
        ("draft", "Draft"),
        ("planned", "Planned"),
        ("en_route", "En Route"),
        ("paused", "Paused"),
        ("complete", "Complete"),
        ("cancelled", "Cancelled"),
    ]

    service_date = models.DateField(db_index=True)
    name = models.CharField(max_length=140, blank=True, help_text="Optional label, e.g. '2025-09-27 AM'.")
    status = models.CharField(max_length=20, choices=STATUS, default="draft", db_index=True)

    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="delivery_runs"
    )
    driver_name = models.CharField(max_length=140, blank=True, help_text="If driver is not a system user.")
    vehicle_label = models.CharField(max_length=80, blank=True, help_text="e.g. 'Bakkie 1 / GP12AB GP'.")

    # Depot / start point
    depot_label = models.CharField(max_length=140, blank=True, help_text="e.g. 'Seshibo Warehouse'.")
    depot_lat = models.FloatField(null=True, blank=True)
    depot_lng = models.FloatField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)

    # Optional overall stats
    total_distance_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    total_drive_min = models.PositiveIntegerField(null=True, blank=True)
    stop_count = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="delivery_runs_created"
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-service_date", "-id"]
        indexes = [
            models.Index(fields=["service_date", "status"]),
        ]

    def __str__(self) -> str:
        who = self.driver.get_username() if self.driver_id else (self.driver_name or "Unassigned")
        return f"{self.service_date} · {self.name or 'Run'} · {who} · {self.get_status_display()}"

    @property
    def has_depot_geo(self) -> bool:
        return self.depot_lat is not None and self.depot_lng is not None

    def recalc_aggregates(self, save=True):
        qs = self.stops.all()
        self.stop_count = qs.count()
        # Sum where available
        dist = Decimal("0.00")
        mins = 0
        for s in qs:
            if s.distance_km is not None:
                dist += Decimal(str(s.distance_km))
            if s.drive_min is not None:
                mins += int(s.drive_min)
        self.total_distance_km = dist
        self.total_drive_min = mins
        if save:
            self.save(update_fields=["stop_count", "total_distance_km", "total_drive_min", "updated_at"])

    # Optional helper to call your planner service from anywhere (lazy import)
    def auto_plan(self):
        from .services import plan_run_sequence
        return plan_run_sequence(self)


# -----------------------------
# 3) STOPS & POD (Proof of Delivery)
# -----------------------------

class DeliveryStop(models.Model):
    """
    One order on a delivery run (one physical drop).
    Holds address & contact snapshots, routing data, POD/signature.
    """
    STATUS = [
        ("pending", "Pending"),             # created; not assigned or not picked
        ("assigned", "Assigned"),           # part of a planned run
        ("en_route", "En Route"),           # driver heading to/arrived
        ("delivered", "Delivered"),
        ("failed", "Failed Attempt"),
        ("cancelled", "Cancelled"),
    ]

    run = models.ForeignKey(DeliveryRun, on_delete=models.CASCADE, related_name="stops")
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="delivery_stops")

    status = models.CharField(max_length=20, choices=STATUS, default="pending", db_index=True)
    sequence = models.PositiveIntegerField(null=True, blank=True, help_text="Route order (1..N).")

    # Address / Contact snapshots (from order.client at time of creation)
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
    service_min = models.PositiveIntegerField(default=5, help_text="Expected time on site.")

    # Routing outputs
    eta = models.DateTimeField(null=True, blank=True)
    distance_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    drive_min = models.PositiveIntegerField(null=True, blank=True)

    # Proof of delivery
    recipient_name = models.CharField(max_length=160, blank=True)
    recipient_id_no = models.CharField(max_length=80, blank=True)
    signature = models.ImageField(upload_to=pod_upload_to, blank=True, null=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    delivery_notes = models.TextField(blank=True)

    # Exceptions
    failed_reason = models.CharField(max_length=220, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="delivery_stops_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="delivery_stops_updated"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["run_id", "sequence", "id"]
        indexes = [
            models.Index(fields=["run", "status"]),
            models.Index(fields=["order"]),
        ]
        unique_together = [("run", "order")]  # each order appears at most once per run

    def __str__(self) -> str:
        label = self.customer_name or f"Order #{self.order_id}"
        return f"{self.run.service_date} · {label} · {self.get_status_display()}"

    @property
    def has_geo(self) -> bool:
        return self.lat is not None and self.lng is not None

    def address_one_line(self) -> str:
        parts = [self.address_line1, self.address_line2, self.suburb, self.city, self.province, self.postal_code]
        return ", ".join([p for p in parts if p])

    def snapshot_from_order(self):
        """
        Seed snapshot fields from the Order’s current client details.
        """
        c = self.order.client
        self.customer_name = str(c)
        self.phone = getattr(c, "phone", "") or ""
        self.email = getattr(c, "email", "") or ""
        self.address_line1 = getattr(c, "address_line1", "") or ""
        self.address_line2 = getattr(c, "address_line2", "") or ""
        self.suburb = getattr(c, "suburb", "") or ""
        self.city = getattr(c, "city", "") or ""
        # prefer display name if stored as choice
        prov_disp = getattr(c, "get_province_display", None)
        self.province = prov_disp() if callable(prov_disp) else (getattr(c, "province", "") or "")
        self.postal_code = getattr(c, "postal_code", "") or ""
        self.country = getattr(c, "country", "") or ""

    def mark_delivered(self, *, recipient_name: str = "", recipient_id_no: str = "", user=None):
        self.status = "delivered"
        if recipient_name:
            self.recipient_name = recipient_name
        if recipient_id_no:
            self.recipient_id_no = recipient_id_no
        self.signed_at = now()
        if user:
            self.updated_by = user
        self.save(update_fields=[
            "status", "recipient_name", "recipient_id_no", "signed_at", "updated_by", "updated_at"
        ])

    def mark_failed(self, reason: str, user=None):
        self.status = "failed"
        self.failed_reason = reason[:220]
        self.failed_at = now()
        if user:
            self.updated_by = user
        self.save(update_fields=["status", "failed_reason", "failed_at", "updated_by", "updated_at"])


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
