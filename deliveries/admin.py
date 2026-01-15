from django.contrib import admin
from django.utils.html import format_html

from .models import (
    PickingBatch,
    PickingItem,
    DeliveryRun,
    DeliveryStop,
    DeliveryStopItem,
)

# =====================================================
# WAREHOUSE — Picking
# =====================================================

class PickingItemInline(admin.TabularInline):
    model = PickingItem
    extra = 0
    show_change_link = True

    fields = (
        "order",
        "order_item",
        "supplier",
        "product_name",
        "sku",
        "uom",
        "expected_qty",
        "picked_qty",
        "is_picked",
        "notes",
    )

    readonly_fields = (
        "order",
        "order_item",
        "supplier",
        "product_name",
        "sku",
        "uom",
        "expected_qty",
    )

    autocomplete_fields = ("order_item",)

    can_delete = False


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
    ordering = ("-service_date", "-id")

    inlines = [PickingItemInline]

    readonly_fields = (
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
    )

    actions = ("mark_in_progress", "mark_complete")

    @admin.display(description="Wave")
    def wave(self, obj):
        return obj.wave

    def mark_in_progress(self, request, queryset):
        updated = 0
        for batch in queryset.exclude(status="complete"):
            batch.mark_started(user=request.user)
            updated += 1
        self.message_user(request, f"{updated} batch(es) marked in progress.")
    mark_in_progress.short_description = "Mark selected batches as In Progress"

    def mark_complete(self, request, queryset):
        updated = 0
        for batch in queryset.exclude(status="complete"):
            batch.mark_complete(user=request.user)
            updated += 1
        self.message_user(
            request,
            f"{updated} batch(es) completed and handed off to delivery."
        )
    mark_complete.short_description = "Complete selected batches (handoff to delivery)"


@admin.register(PickingItem)
class PickingItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "batch",
        "order",
        "product_name",
        "supplier",
        "expected_qty",
        "picked_qty",
        "expected_supplier_price",
        "actual_supplier_price",
        "is_picked",
    )

    # 🔒 CRITICAL LINE — THIS SOLVES EVERYTHING
    exclude = ("supplier",)

    readonly_fields = (
        "batch",
        "order",
        "order_item",
        "product_name",
        "sku",
        "uom",
        "expected_qty",
        "expected_supplier_price",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Core", {
            "fields": (
                "batch",
                "order",
                "order_item",
                "product_name",
                "sku",
                "uom",
            )
        }),
        ("Quantities", {
            "fields": (
                "expected_qty",
                "picked_qty",
                "is_picked",
            )
        }),
        ("Pricing", {
            "fields": (
                "expected_supplier_price",
                "actual_supplier_price",
            )
        }),
        ("Meta", {
            "fields": (
                "notes",
                "created_at",
                "updated_at",
            )
        }),
    )




# =====================================================
# FLEET — Delivery Runs
# =====================================================

class DeliveryStopItemInline(admin.TabularInline):
    model = DeliveryStopItem
    extra = 0
    can_delete = False

    fields = (
        "order_item",
        "product_name",
        "sku",
        "uom",
        "planned_qty",
        "loaded_qty",
        "delivered_qty",
        "variance_display",
        "shortage_reason",
        "notes",
    )

    readonly_fields = (
        "order_item",
        "product_name",
        "sku",
        "uom",
        "planned_qty",
        "variance_display",
    )

    autocomplete_fields = ("order_item",)

    @admin.display(description="Variance")
    def variance_display(self, obj):
        if obj.variance == 0:
            return "0"
        color = "red" if obj.variance < 0 else "green"
        return format_html(
            '<strong style="color:{};">{}</strong>',
            color,
            obj.variance,
        )


@admin.register(DeliveryStop)
class DeliveryStopAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "sequence",
        "order",
        "customer_name",
        "city",
        "status",
        "eta",
    )

    list_filter = (
        "status",
        "run__service_date",
        "run",
    )

    search_fields = (
        "customer_name",
        "order__id",
        "city",
        "suburb",
    )

    ordering = ("run", "sequence")

    autocomplete_fields = ("run", "order")

    readonly_fields = (
        "created_at",
        "updated_at",
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
    )

    inlines = [DeliveryStopItemInline]


@admin.register(DeliveryRun)
class DeliveryRunAdmin(admin.ModelAdmin):
    list_display = (
        "service_date",
        "name",
        "status",
        "driver_display",
        "vehicle_label",
        "stop_count",
    )

    list_filter = ("status", "service_date")
    search_fields = ("name", "driver_name", "vehicle_label")
    date_hierarchy = "service_date"
    ordering = ("-service_date", "-id")

    autocomplete_fields = ("driver",)

    readonly_fields = (
        "stop_count",
        "total_distance_km",
        "total_drive_min",
        "created_at",
        "updated_at",
    )

    actions = ("recalc_run_stats",)

    @admin.display(description="Driver")
    def driver_display(self, obj):
        return obj.driver.get_username() if obj.driver_id else (obj.driver_name or "—")

    def recalc_run_stats(self, request, queryset):
        for run in queryset:
            run.recalc_aggregates(save=True)
        self.message_user(request, "Run statistics recalculated.")
    recalc_run_stats.short_description = "Recalculate run statistics"
