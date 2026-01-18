from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import localtime

from .models import (
    Vehicle,
    PickingBatch,
    PickingItem,
    DeliveryRun,
    DeliveryStop,
    DeliveryStopItem,
    DriverLocation,
    RunEvent,
)

# =====================================
# VEHICLES (FLEET)
# =====================================

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "registration_number",
        "vehicle_type",
        "status_badge",
        "capacity_kg",
        "updated_at",
    )
    list_filter = ("status", "vehicle_type")
    search_fields = ("label", "registration_number")
    ordering = ("label",)

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Vehicle Info", {
            "fields": (
                "label",
                "registration_number",
                "vehicle_type",
                "capacity_kg",
                "status",
            )
        }),
        ("Notes", {
            "fields": ("notes",)
        }),
        ("System", {
            "fields": ("created_at", "updated_at")
        }),
    )

    def status_badge(self, obj):
        colors = {
            "active": "green",
            "maintenance": "orange",
            "inactive": "red",
        }
        return format_html(
            '<b style="color:{};">{}</b>',
            colors.get(obj.status, "gray"),
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"


# =====================================
# PICKING (WAREHOUSE)
# =====================================

class PickingItemInline(admin.TabularInline):
    model = PickingItem
    extra = 0
    readonly_fields = (
        "order",
        "order_item",
        "supplier",
        "product_name",
        "sku",
        "uom",
        "expected_qty",
        "expected_supplier_price",
        "created_at",
    )
    fields = (
        "order",
        "product_name",
        "expected_qty",
        "picked_qty",
        "is_picked",
        "supplier",
    )


@admin.register(PickingBatch)
class PickingBatchAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "service_date",
        "wave",
        "status",
        "order_count",
        "item_count",
        "started_at",
        "completed_at",
    )
    list_filter = ("status", "service_date")
    search_fields = ("name",)
    date_hierarchy = "service_date"
    inlines = [PickingItemInline]

    readonly_fields = (
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "order_count",
        "item_count",
    )

    actions = ("mark_in_progress", "mark_complete")

    def mark_in_progress(self, request, queryset):
        for batch in queryset:
            if batch.status == "draft":
                batch.mark_started(user=request.user)
    mark_in_progress.short_description = "▶ Mark selected batches In Progress"

    def mark_complete(self, request, queryset):
        for batch in queryset:
            if batch.status != "complete":
                batch.mark_complete(user=request.user)
    mark_complete.short_description = "✅ Complete batches (handoff to delivery)"


# =====================================
# DELIVERY RUN (FLEET)
# =====================================

class DeliveryStopInline(admin.TabularInline):
    model = DeliveryStop
    extra = 0
    readonly_fields = (
        "order",
        "customer_name",
        "status",
        "sequence",
        "started_at",
        "ended_at",
    )
    fields = (
        "sequence",
        "customer_name",
        "status",
        "distance_km",
        "drive_min",
    )


@admin.register(DeliveryRun)
class DeliveryRunAdmin(admin.ModelAdmin):
    list_display = (
        "service_date",
        "name",
        "driver",
        "vehicle",
        "status",
        "stop_count",
        "total_drive_min",
        "total_distance_km",
    )
    list_filter = ("status", "service_date", "vehicle")
    search_fields = ("name", "driver__username", "vehicle__label")
    date_hierarchy = "service_date"
    inlines = [DeliveryStopInline]

    readonly_fields = (
        "created_at",
        "updated_at",
        "stop_count",
        "total_distance_km",
        "total_drive_min",
    )

    actions = ("recalculate_aggregates",)

    fieldsets = (
        ("Run Details", {
            "fields": (
                "service_date",
                "name",
                "status",
                "driver",
                "vehicle",
                "start_time",
            )
        }),
        ("Depot", {
            "fields": (
                "depot_label",
                "depot_lat",
                "depot_lng",
            )
        }),
        ("Aggregates", {
            "fields": (
                "stop_count",
                "total_drive_min",
                "total_distance_km",
            )
        }),
        ("Notes", {
            "fields": ("notes",)
        }),
        ("System", {
            "fields": ("created_at", "updated_at")
        }),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "vehicle":
            kwargs["queryset"] = Vehicle.objects.filter(status="active")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def recalculate_aggregates(self, request, queryset):
        for run in queryset:
            run.recalc_aggregates(save=True)
    recalculate_aggregates.short_description = "🔄 Recalculate run aggregates"


# =====================================
# DELIVERY STOPS (OPERATIONS)
# =====================================

class DeliveryStopItemInline(admin.TabularInline):
    model = DeliveryStopItem
    extra = 0
    readonly_fields = (
        "order_item",
        "product_name",
        "sku",
        "uom",
        "planned_qty",
    )
    fields = (
        "product_name",
        "planned_qty",
        "loaded_qty",
        "delivered_qty",
        "shortage_reason",
    )


@admin.register(DeliveryStop)
class DeliveryStopAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "sequence",
        "customer_name",
        "status",
        "drive_min",
        "distance_km",
        "arrival_time_display",
    )
    list_filter = ("status", "run__service_date")
    search_fields = ("customer_name", "order__id")
    ordering = ("run", "sequence")
    inlines = [DeliveryStopItemInline]

    readonly_fields = (
        "run",
        "order",
        "sequence",
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
        "distance_km",
        "drive_min",
        "started_at",
        "ended_at",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Run Info", {
            "fields": ("run", "order", "sequence", "status")
        }),
        ("Customer Snapshot", {
            "fields": (
                "customer_name",
                "phone",
                "email",
                "address_line1",
                "address_line2",
                "suburb",
                "city",
                "province",
                "postal_code",
            )
        }),
        ("Routing", {
            "fields": ("lat", "lng", "distance_km", "drive_min")
        }),
        ("Timing", {
            "fields": ("started_at", "ended_at")
        }),
    )

    def arrival_time_display(self, obj):
        if obj.ended_at:
            return localtime(obj.ended_at).strftime("%H:%M")
        return "—"
    arrival_time_display.short_description = "Arrival Time"


# =====================================
# DRIVER TELEMETRY
# =====================================

@admin.register(DriverLocation)
class DriverLocationAdmin(admin.ModelAdmin):
    list_display = ("run", "driver", "lat", "lng", "recorded_at")
    list_filter = ("run", "driver")
    readonly_fields = ("recorded_at",)
    ordering = ("-recorded_at",)


# =====================================
# RUN EVENTS (AUDIT / TIMELINE)
# =====================================

@admin.register(RunEvent)
class RunEventAdmin(admin.ModelAdmin):
    list_display = ("run", "stop", "event_type", "recorded_at")
    list_filter = ("event_type", "run__service_date")
    search_fields = ("run__name", "notes")
    readonly_fields = ("recorded_at",)
    ordering = ("-recorded_at",)
