# deliveries/admin.py
from django.contrib import admin
from django.utils.timezone import now

from .models import (
    PickingBatch, PickingItem,
    DeliveryRun, DeliveryStop, DeliveryStopItem,
)


# -----------------------------
# Inlines
# -----------------------------

class PickingItemInline(admin.TabularInline):
    model = PickingItem
    extra = 0
    fields = ("order", "order_item", "product_name", "sku", "uom",
              "expected_qty", "picked_qty", "is_picked", "notes")
    readonly_fields = ("order", "order_item", "product_name", "sku", "uom", "expected_qty")
    raw_id_fields = ("order", "order_item")


class DeliveryStopInline(admin.TabularInline):
    model = DeliveryStop
    extra = 0
    fields = (
        "sequence", "order", "status", "customer_name", "city",
        "eta", "distance_km", "drive_min",
    )
    raw_id_fields = ("order",)
    ordering = ("sequence",)


class DeliveryStopItemInline(admin.TabularInline):
    model = DeliveryStopItem
    extra = 0
    fields = (
        "order_item", "product_name", "sku", "uom",
        "planned_qty", "loaded_qty", "delivered_qty",
        "shortage_reason", "notes",
    )
    raw_id_fields = ("order_item",)


# -----------------------------
# PickingBatch Admin
# -----------------------------

@admin.register(PickingBatch)
class PickingBatchAdmin(admin.ModelAdmin):
    list_display = ("name", "service_date", "status", "order_count", "item_count", "created_at")
    list_filter = ("status", "service_date")
    search_fields = ("name",)
    date_hierarchy = "service_date"
    inlines = [PickingItemInline]
    raw_id_fields = ("created_by",)
    readonly_fields = ("created_at", "updated_at", "started_at", "completed_at")
    list_per_page = 50

    @admin.action(description="Mark selected batches as Started")
    def mark_started(self, request, queryset):
        for batch in queryset:
            batch.mark_started(user=request.user)

    @admin.action(description="Mark selected batches as Complete")
    def mark_complete(self, request, queryset):
        for batch in queryset:
            batch.mark_complete(user=request.user)

    actions = ["mark_started", "mark_complete"]


# -----------------------------
# DeliveryRun Admin
# -----------------------------

@admin.register(DeliveryRun)
class DeliveryRunAdmin(admin.ModelAdmin):
    list_display = (
        "service_date", "name", "status", "driver_display", "vehicle_label",
        "stop_count", "total_distance_km", "total_drive_min", "has_depot_geo",
        "created_at",
    )
    list_filter = ("status", "service_date", "driver")
    search_fields = ("name", "driver_name", "vehicle_label")
    date_hierarchy = "service_date"
    inlines = [DeliveryStopInline]
    raw_id_fields = ("driver", "created_by")
    readonly_fields = ("created_at", "updated_at", "stop_count", "total_distance_km", "total_drive_min")
    list_per_page = 50
    ordering = ("-service_date", "-id")

    @admin.display(description="Driver", ordering="driver_name")
    def driver_display(self, obj):
        if obj.driver_id:
            return obj.driver.get_username()
        return obj.driver_name or "—"

    @admin.action(description="Set status → Planned")
    def set_planned(self, request, queryset):
        queryset.update(status="planned", updated_at=now())

    @admin.action(description="Set status → En Route")
    def set_en_route(self, request, queryset):
        queryset.update(status="en_route", updated_at=now())

    @admin.action(description="Set status → Complete")
    def set_complete(self, request, queryset):
        queryset.update(status="complete", updated_at=now())

    @admin.action(description="Set status → Cancelled")
    def set_cancelled(self, request, queryset):
        queryset.update(status="cancelled", updated_at=now())

    actions = ["set_planned", "set_en_route", "set_complete", "set_cancelled"]


# -----------------------------
# DeliveryStop Admin
# -----------------------------

@admin.register(DeliveryStop)
class DeliveryStopAdmin(admin.ModelAdmin):
    list_display = (
        "run", "sequence", "status", "order", "customer_name",
        "city", "eta", "signed_at", "failed_reason",
    )
    list_filter = ("status", "run__service_date", "run__driver")
    search_fields = ("customer_name", "phone", "email", "address_line1", "city", "province", "postal_code")
    inlines = [DeliveryStopItemInline]
    raw_id_fields = ("run", "order", "created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at", "signed_at", "failed_at")
    list_per_page = 50
    ordering = ("run", "sequence", "id")

    fieldsets = (
        (None, {
            "fields": ("run", "order", "status", "sequence")
        }),
        ("Contact", {
            "fields": ("customer_name", "phone", "email")
        }),
        ("Address", {
            "fields": (
                "address_line1", "address_line2", "suburb", "city", "province",
                "postal_code", "country", "lat", "lng",
            )
        }),
        ("Routing", {
            "fields": ("eta", "distance_km", "drive_min", "service_min")
        }),
        ("POD / Signature", {
            "fields": ("recipient_name", "recipient_id_no", "signature", "signed_at", "delivery_notes")
        }),
        ("Exceptions", {
            "fields": ("failed_reason", "failed_at")
        }),
        ("Audit", {
            "fields": ("created_by", "updated_by", "created_at", "updated_at")
        }),
    )

    @admin.action(description="Mark selected stops as Delivered")
    def mark_delivered(self, request, queryset):
        for stop in queryset:
            stop.mark_delivered(user=request.user)

    @admin.action(description="Mark selected stops as Failed (reason: Admin bulk)")
    def mark_failed(self, request, queryset):
        for stop in queryset:
            stop.mark_failed("Admin bulk", user=request.user)

    actions = ["mark_delivered", "mark_failed"]


# -----------------------------
# DeliveryStopItem Admin (optional direct access)
# -----------------------------

@admin.register(DeliveryStopItem)
class DeliveryStopItemAdmin(admin.ModelAdmin):
    list_display = ("stop", "order_item", "product_name", "planned_qty", "loaded_qty", "delivered_qty", "variance")
    list_filter = ("stop__run__service_date",)
    search_fields = ("product_name", "sku")
    raw_id_fields = ("stop", "order_item")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50
    ordering = ("stop", "id")
