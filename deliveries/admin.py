from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import localtime
from django.urls import path
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from decimal import Decimal
from .models import (
    Inventory,
    StockReceipt,
    StockReceiptItem,
    StockReservation,
    StockMovement,
    StockCount,
    StockCountItem,
    Vehicle,
    PickingBatch,
    PickingItem,
    DeliveryRun,
    DeliveryStop,
    DeliveryStopItem,
    DriverLocation,
    RunEvent,
    InternalDeliveryRate,
    ExternalDeliveryRate,
)
from suppliers.models import Supplier


def send_delivery_email(stop, recipient_email, recipient_name):
    subject = f"Delivery Confirmation · Order #{stop.order.id}"

    html_content = render_to_string(
        "emails/delivery_email.html",
        {
            "stop": stop,
            "order": stop.order,
            "recipient_name": recipient_name,
            "items": stop.order.items.all(),
        },
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body="Your delivery has been completed.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
    )

    email.attach_alternative(html_content, "text/html")
    email.send()


# =====================================
# VEHICLES (FLEET)
# =====================================

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "registration_number",
        "vehicle_type",
        "ownership_badge",
        "status_badge",
        "capacity_kg",
        "updated_at",
    )

    list_filter = (
        "status",
        "vehicle_type",
        "is_internal",
    )

    search_fields = (
        "label",
        "registration_number",
    )

    ordering = ("label",)

    readonly_fields = (
        "created_at",
        "updated_at",
    )

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
        ("Ownership", {
            "fields": ("is_internal",),
            "description": (
                "Internal = company-owned vehicle. "
                "Unchecked = partner / owner-driver vehicle."
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

    def ownership_badge(self, obj):
        if obj.is_internal:
            return format_html(
                '<span style="color:green; font-weight:600;">Internal</span>'
            )
        return format_html(
            '<span style="color:#0d6efd; font-weight:600;">Partner</span>'
        )
    ownership_badge.short_description = "Ownership"


# =====================================
# DELIVERY RATES (COSTING)
# =====================================

@admin.register(InternalDeliveryRate)
class InternalDeliveryRateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "driver_per_km",
        "assistant_per_km",
        "total_per_km_display",
        "is_active",
        "updated_at",
    )

    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Rate Info", {
            "fields": (
                "name",
                "driver_per_km",
                "assistant_per_km",
                "is_active",
            )
        }),
        ("System", {
            "fields": ("created_at", "updated_at")
        }),
    )

    def total_per_km_display(self, obj):
        return f"{obj.total_per_km:.2f}"
    total_per_km_display.short_description = "Total / km"


@admin.register(ExternalDeliveryRate)
class ExternalDeliveryRateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "driver_per_km",
        "assistant_per_km",
        "total_per_km_display",
        "is_active",
        "updated_at",
    )

    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)

    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Rate Info", {
            "fields": (
                "name",
                "driver_per_km",
                "assistant_per_km",
                "is_active",
            )
        }),
        ("System", {
            "fields": ("created_at", "updated_at")
        }),
    )

    def total_per_km_display(self, obj):
        return f"{obj.total_per_km:.2f}"
    total_per_km_display.short_description = "Total / km"


# =====================================
# INVENTORY / STOCK CONTROL
# =====================================


class StockReceiptItemInline(admin.TabularInline):
    model = StockReceiptItem
    extra = 0
    fields = (
        "product",
        "expected_qty",
        "received_qty",
        "quantity_variance_display",
        "unit_cost_excl",
        "vat_percent",
        "unit_cost_incl",
        "batch_reference",
    )
    readonly_fields = ("quantity_variance_display",)

    @admin.display(description="Variance")
    def quantity_variance_display(self, obj):
        if not obj.pk:
            return "—"
        variance = obj.quantity_variance
        if variance > 0:
            return format_html('<strong style="color:green;">+{}</strong>', variance)
        if variance < 0:
            return format_html('<strong style="color:red;">{}</strong>', variance)
        return "0"


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "product_sku",
        "quantity_on_hand",
        "quantity_reserved",
        "quantity_available_display",
        "minimum_units",
        "maximum_units",
        "last_supplier",
        "last_received_at",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "product__uom", "product__category")
    search_fields = (
        "product__name",
        "product__product_no",
        "product__sku",
        "last_supplier__name",
    )
    ordering = ("product__name",)
    readonly_fields = (
        "quantity_available_display",
        "last_received_at",
        "last_supplier",
        "last_stock_receipt",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Product", {
            "fields": ("product", "is_active")
        }),
        ("Current Stock", {
            "fields": (
                "quantity_on_hand",
                "quantity_reserved",
                "quantity_available_display",
                "minimum_units",
                "maximum_units",
            ),
            "description": (
                "Available stock is calculated as quantity on hand minus quantity reserved. "
                "Do not manually change stock to correct a historical movement; use the stock movement/count process."
            ),
        }),
        ("Last Receipt", {
            "fields": (
                "last_received_at",
                "last_supplier",
                "last_stock_receipt",
            )
        }),
        ("System", {
            "fields": ("created_at", "updated_at")
        }),
    )

    @admin.display(description="SKU", ordering="product__sku")
    def product_sku(self, obj):
        return obj.product.sku or "—"

    @admin.display(description="Available", ordering="quantity_on_hand")
    def quantity_available_display(self, obj):
        value = obj.quantity_available
        if value <= 0:
            return format_html('<strong style="color:red;">{}</strong>', value)
        return format_html('<strong style="color:green;">{}</strong>', value)


@admin.register(StockReceipt)
class StockReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_number",
        "supplier",
        "status",
        "supplier_invoice_number",
        "received_at",
        "received_by",
        "checked_by",
        "completed_by",
    )
    list_filter = ("status", "received_at", "supplier")
    search_fields = (
        "receipt_number",
        "supplier__name",
        "supplier_invoice_number",
    )
    date_hierarchy = "received_at"
    ordering = ("-received_at", "-id")
    inlines = [StockReceiptItemInline]
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Receipt", {
            "fields": (
                "receipt_number",
                "supplier",
                "status",
                "supplier_invoice_number",
                "received_at",
            )
        }),
        ("Responsibility & Verification", {
            "fields": (
                "created_by",
                "received_by",
                "checked_by",
                "completed_by",
            ),
            "description": "These fields identify who created, received, checked and completed the stock receipt.",
        }),
        ("Notes", {"fields": ("notes",)}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(StockReservation)
class StockReservationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "inventory_product",
        "order",
        "order_item",
        "quantity",
        "status",
        "reserved_by",
        "reserved_at",
        "released_by",
        "picked_by",
    )
    list_filter = ("status", "reserved_at", "released_at", "picked_at")
    search_fields = (
        "order__id",
        "order_item__product_name",
        "inventory__product__name",
        "inventory__product__sku",
    )
    readonly_fields = (
        "reserved_at",
        "released_at",
        "picked_at",
        "updated_at",
    )
    fieldsets = (
        ("Reservation", {
            "fields": (
                "inventory",
                "order",
                "order_item",
                "quantity",
                "status",
            )
        }),
        ("Task Ownership", {
            "fields": (
                "reserved_by",
                "reserved_at",
                "released_by",
                "released_at",
                "picked_by",
                "picked_at",
            )
        }),
        ("Notes", {"fields": ("notes",)}),
        ("System", {"fields": ("updated_at",)}),
    )

    @admin.display(description="Product")
    def inventory_product(self, obj):
        return obj.inventory.product


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "performed_at",
        "movement_type",
        "product",
        "quantity",
        "quantity_before",
        "quantity_after",
        "performed_by",
        "reference_display",
        "reason",
    )
    list_filter = ("movement_type", "performed_at", "performed_by")
    search_fields = (
        "product__name",
        "product__sku",
        "performed_by__username",
        "reason",
        "notes",
    )
    date_hierarchy = "performed_at"
    ordering = ("-performed_at", "-id")
    readonly_fields = (
        "inventory",
        "product",
        "movement_type",
        "quantity",
        "quantity_before",
        "quantity_after",
        "performed_by",
        "performed_at",
        "receipt_item",
        "reservation",
        "picking_item",
        "delivery_stop_item",
        "created_at",
    )
    fieldsets = (
        ("Stock Change", {
            "fields": (
                "inventory",
                "product",
                "movement_type",
                "quantity",
                "quantity_before",
                "quantity_after",
            )
        }),
        ("Audit", {
            "fields": (
                "performed_by",
                "performed_at",
                "reason",
                "notes",
            )
        }),
        ("References", {
            "fields": (
                "receipt_item",
                "reservation",
                "picking_item",
                "delivery_stop_item",
            )
        }),
        ("System", {"fields": ("created_at",)}),
    )

    @admin.display(description="Reference")
    def reference_display(self, obj):
        if obj.receipt_item_id:
            return f"Receipt item #{obj.receipt_item_id}"
        if obj.reservation_id:
            return f"Reservation #{obj.reservation_id}"
        if obj.picking_item_id:
            return f"Picking item #{obj.picking_item_id}"
        if obj.delivery_stop_item_id:
            return f"Delivery item #{obj.delivery_stop_item_id}"
        return "—"


class StockCountItemInline(admin.TabularInline):
    model = StockCountItem
    extra = 0
    fields = (
        "product",
        "inventory",
        "system_qty",
        "counted_qty",
        "variance_display",
        "counted_by",
        "counted_at",
        "notes",
    )
    readonly_fields = ("system_qty", "variance_display")

    @admin.display(description="Variance")
    def variance_display(self, obj):
        if not obj.pk or obj.counted_qty is None:
            return "—"
        variance = obj.variance
        if variance > 0:
            return format_html('<strong style="color:green;">+{}</strong>', variance)
        if variance < 0:
            return format_html('<strong style="color:red;">{}</strong>', variance)
        return "0"


@admin.register(StockCount)
class StockCountAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "status",
        "started_by",
        "started_at",
        "completed_by",
        "completed_at",
        "approved_by",
        "approved_at",
    )
    list_filter = ("status", "started_at", "completed_at", "approved_at")
    search_fields = ("reference", "notes")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")
    inlines = [StockCountItemInline]
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Count", {
            "fields": ("reference", "status", "notes")
        }),
        ("Audit", {
            "fields": (
                "started_by",
                "started_at",
                "completed_by",
                "completed_at",
                "approved_by",
                "approved_at",
            )
        }),
        ("System", {"fields": ("created_at", "updated_at")}),
    )


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
        "picked_by",
        "picked_at",
        "created_at",
    )
    fields = (
        "order",
        "product_name",
        "expected_qty",
        "picked_qty",
        "is_picked",
        "picked_by",
        "picked_at",
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
        "started_by",
        "started_at",
        "completed_by",
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
        "started_by",
        "completed_by",
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
# DELIVERY RUN (FLEET + COSTING)
# =====================================

class DeliveryStopInline(admin.TabularInline):
    model = DeliveryStop
    extra = 0
    readonly_fields = (
        "order",
        "end_user",
        "customer_name",
        "status",
        "sequence",
        "started_at",
        "ended_at",
    )
    fields = (
        "sequence",
        "customer_name",
        "end_user",
        "status",
        "distance_km",
        "drive_min",
    )



@admin.register(DeliveryRun)
class DeliveryRunAdmin(admin.ModelAdmin):
    list_display = (
        "service_date",
        "name",
        "start_supplier",
        "driver",
        "vehicle",
        "status",
        "created_by",
        "dispatched_by",
        "completed_by",
        "stop_count",
        "total_distance_km",
        "overall_total_cost_display",
    )

    list_filter = (
        "status",
        "service_date",
        "vehicle",
    )

    search_fields = (
        "name",
        "driver__username",
        "vehicle__label",
        "vehicle__registration_number",
    )

    date_hierarchy = "service_date"
    inlines = [DeliveryStopInline]

    readonly_fields = (
        "created_at",
        "updated_at",

        # Audit actors
        "created_by",
        "dispatched_by",
        "completed_by",

        "stop_count",
        "total_distance_km",
        "total_drive_min",

        # Journey Origin snapshot
        "start_location_label",
        "start_lat",
        "start_lng",

        # Rate snapshot
        "driver_rate_per_km",
        "assistant_rate_per_km",
        "total_rate_per_km",

        # Cost snapshot
        "driver_total_cost",
        "assistant_total_cost",
        "overall_total_cost",
    )

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

        ("Journey Origin", {
            "description": (
                "Optional starting location for route generation. "
                "If left blank, the depot will be used."
            ),
            "fields": (
                "start_supplier",
                "start_location_label",
                (
                    "start_lat",
                    "start_lng",
                ),
            ),
        }),


        ("Depot", {
            "fields": (
                "depot_label",
                "depot_lat",
                "depot_lng",
            )
        }),
        ("Costing (Per KM Snapshot)", {
            "fields": (
                "driver_rate_per_km",
                "assistant_rate_per_km",
                "total_rate_per_km",
            ),
            "description": (
                "Rates are automatically applied when a vehicle is assigned. "
                "These are historical snapshots."
            )
        }),
        ("Costing (Totals)", {
            "fields": (
                "driver_total_cost",
                "assistant_total_cost",
                "overall_total_cost",
            ),
            "description": (
                "Calculated from rates × total distance. "
                "Values are locked for audit accuracy."
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
        ("Audit", {
            "fields": (
                "created_by",
                "dispatched_by",
                "completed_by",
            ),
            "description": "Records who created, dispatched and completed the delivery run.",
        }),
        ("System", {
            "fields": ("created_at", "updated_at")
        }),
    )

    actions = ("recalculate_aggregates",)

    # =========================
    # DISPLAY HELPERS
    # =========================

    def overall_total_cost_display(self, obj):
        value = obj.overall_total_cost

        if value is None:
            return "—"

        try:
            value = Decimal(value)
        except Exception:
            return format_html("<strong>{}</strong>", value)

        return format_html("<strong>R {:,.2f}</strong>", value)

    overall_total_cost_display.short_description = "Total Cost"
    overall_total_cost_display.admin_order_field = "overall_total_cost"

    # =========================
    # ACTIONS
    # =========================

    def recalculate_aggregates(self, request, queryset):
        for run in queryset:
            run.recalc_aggregates(save=False)
            run.calculate_total_costs()
            run.save()


    recalculate_aggregates.short_description = "🔄 Recalculate aggregates & costs"

    # =========================
    # VEHICLE FILTERING
    # =========================

    from suppliers.models import Supplier

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "vehicle":
            kwargs["queryset"] = Vehicle.objects.filter(status="active")

        elif db_field.name == "start_supplier":
            kwargs["queryset"] = Supplier.objects.filter(is_active=True)

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

# =====================================
# DELIVERY STOPS
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
        "end_user_name",
        "stop_type",
        "supplier",
        "status",
        "drive_min",
        "distance_km",
        "arrival_time_display",
    )

    list_filter = (
        "status",
        "end_user__end_user_type",
        "end_user__status",
        "run__service_date",
    )

    search_fields = (
        "customer_name",
        "end_user__end_user_number",
        "end_user__first_name",
        "end_user__surname",
        "end_user__phone",
        "order__id",
    )

    ordering = (
        "run",
        "sequence",
    )

    inlines = [DeliveryStopItemInline]

    readonly_fields = (
        "run",
        "order",
        "end_user",
        "stop_type",
        "supplier",
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
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

    # =====================================
    # CUSTOM ADMIN URLS
    # =====================================

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<int:stop_id>/send-email/",
                self.admin_site.admin_view(
                    self.send_delivery_email_view
                ),
                name="delivery-stop-send-email",
            ),
        ]

        return custom_urls + urls

    # =====================================
    # SEND DELIVERY EMAIL
    # =====================================

    def send_delivery_email_view(self, request, stop_id):
        stop = get_object_or_404(DeliveryStop, pk=stop_id)

        if not stop.email:
            self.message_user(
                request,
                "This delivery stop has no customer email address.",
                level=messages.ERROR,
            )
            return redirect(
                f"/admin/deliveries/deliverystop/{stop.id}/change/"
            )

        try:
            send_delivery_email(
                stop=stop,
                recipient_email=stop.email,
                recipient_name=stop.customer_name,
            )

            self.message_user(
                request,
                "Delivery email sent successfully.",
                level=messages.SUCCESS,
            )

        except Exception as e:
            self.message_user(
                request,
                f"Error sending delivery email: {e}",
                level=messages.ERROR,
            )

        return redirect(
            f"/admin/deliveries/deliverystop/{stop.id}/change/"
        )

    # =====================================
    # DISPLAY HELPERS
    # =====================================

    @admin.display(description="End User")
    def end_user_name(self, obj):
        if not obj.end_user:
            return "—"
        return f"{obj.end_user.full_name} ({obj.end_user.end_user_number})"

    def arrival_time_display(self, obj):
        if obj.ended_at:
            return localtime(obj.ended_at).strftime("%H:%M")
        return "—"

    arrival_time_display.short_description = "Arrival Time"


# =====================================
# RUN EVENTS (AUDIT)
# =====================================

@admin.register(RunEvent)
class RunEventAdmin(admin.ModelAdmin):
    list_display = ("run", "stop", "event_type", "recorded_at")
    list_filter = ("event_type", "run__service_date")
    search_fields = ("run__name", "notes")
    readonly_fields = ("recorded_at",)
    ordering = ("-recorded_at",)


# =====================================
# END
# =====================================