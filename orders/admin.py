# orders/admin.py
from decimal import Decimal
from django.contrib import admin, messages

from .models import Order, OrderItem, OrderAudit


# ---------- helpers ----------
def money(val: Decimal | None) -> str:
    if val is None:
        return "—"
    return f"R {val:.2f}"


# ---------- inlines ----------
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1
    autocomplete_fields = ("category", "product")
    show_change_link = False

    fields = (
        "category",
        "product",
        "sku", "product_name", "uom",
        "quantity",
        "unit_price_excl", "discount_excl", "vat_percent",
        "line_total_excl_display",
        "line_vat_amount_display",
        "line_total_inc_display",
    )

    readonly_fields = (
        "sku", "product_name", "uom",
        "line_total_excl_display",
        "line_vat_amount_display",
        "line_total_inc_display",
    )

    # --------------------------------------------------
    # 🔥 MULTI-DB FIX (CRITICAL)
    # --------------------------------------------------
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.path.startswith("/dummy-admin"):
            return qs.using("dummy")

        return qs.using("default")

    # --------------------------------------------------
    # 🔥 FK + PRODUCT LABEL CUSTOMIZATION
    # --------------------------------------------------
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)

        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        # Category queryset
        if db_field.name == "category":
            from products.models import Category
            field.queryset = Category.objects.using(db).all()

        # Product queryset + label customization
        if db_field.name == "product":
            from products.models import Product

            qs = Product.objects.using(db).all()
            field.queryset = qs

            # 🔥 Custom label with price (INC VAT)
            def label(obj):
                try:
                    pr = obj.pricing_rows.filter(is_primary=True, is_active=True).first()

                    if pr:
                        return f"{obj.sku} · {obj.name} (R {pr.retail_price_inc:.2f})"

                    return f"{obj.sku} · {obj.name}"
                except Exception:
                    return f"{obj.sku} · {obj.name}"

            field.label_from_instance = label

        return field

    # --------------------------------------------------
    # DISPLAY HELPERS
    # --------------------------------------------------
    @admin.display(description="Line Total (Excl)")
    def line_total_excl_display(self, obj: OrderItem):
        try:
            return money(obj.line_total_excl)
        except Exception:
            return "—"

    @admin.display(description="VAT (R)")
    def line_vat_amount_display(self, obj: OrderItem):
        try:
            return money(obj.line_vat_amount)
        except Exception:
            return "—"

    @admin.display(description="Line Total (Inc)")
    def line_total_inc_display(self, obj: OrderItem):
        try:
            return money(obj.line_total_inc)
        except Exception:
            return "—"


class OrderAuditInline(admin.TabularInline):
    model = OrderAudit
    extra = 0
    can_delete = False
    show_change_link = False

    fields = (
        "performed_at",
        "action",
        "performed_by",
        "status_before",
        "status_after",
        "amount_before",
        "amount_after",
        "description",
    )

    readonly_fields = fields

    ordering = ("-performed_at",)

# ---------- order admin ----------
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.path.startswith("/dummy-admin"):
            return qs.using("dummy")

        return qs.using("default")

    # --------------------------------------------------
    # 🔥 MAKE CLIENT READ-ONLY AFTER CREATION
    # --------------------------------------------------
    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)

        # If editing existing order → lock client
        if obj:
            ro.append("client")

        return ro

    # date_hierarchy removed – MySQL-safe
    inlines = [OrderItemInline, OrderAuditInline]

    list_display = (
        "id",
        "client",
        "status",
        "channel",
        "subtotal_excl_display",
        "vat_total_display",
        "grand_total_inc_display",
        "submitted_at",
        "approved_at",
    )

    list_filter = (
        "status",
        "channel",
        ("submitted_at", admin.DateFieldListFilter),
        ("approved_at", admin.DateFieldListFilter),
    )

    search_fields = (
        "id",
        "client__name",
        "client__organization",
        "client__email",
        "client__phone",
    )

    autocomplete_fields = ("client", "created_by")

    readonly_fields = (
        "submitted_at",
        "reviewed_at",
        "approved_at",
        "updated_at",
        "subtotal_excl",
        "vat_total",
        "grand_total_inc",
        "delivery_fee_vat_amount_display",
    )

    fieldsets = (
        ("Order Info", {
            "fields": (
                ("client", "created_by"),
                ("status", "channel"),
                "customer_notes",
                "notes",
                ("order_date",),
            )
        }),
        ("Charges / Discounts", {
            "fields": (
                "discount_total_excl",
                ("delivery_fee_excl", "delivery_fee_vat_percent", "delivery_fee_vat_amount_display"),
            )
        }),
        ("Totals (auto)", {
            "fields": (
                "subtotal_excl",
                "vat_total",
                "grand_total_inc",
                ("submitted_at", "reviewed_at", "approved_at", "updated_at"),
            )
        }),
    )

    # --------------------------------------------------
    # DISPLAY HELPERS
    # --------------------------------------------------
    @admin.display(description="Subtotal (Excl)")
    def subtotal_excl_display(self, obj: Order):
        return money(obj.subtotal_excl)

    @admin.display(description="VAT (R)")
    def vat_total_display(self, obj: Order):
        return money(obj.vat_total)

    @admin.display(description="Grand Total (Inc)")
    def grand_total_inc_display(self, obj: Order):
        return money(obj.grand_total_inc)

    @admin.display(description="Delivery VAT (R)")
    def delivery_fee_vat_amount_display(self, obj: Order):
        try:
            return money(obj.delivery_fee_vat_amount)
        except Exception:
            return "—"

    # --------------------------------------------------
    # SAVE LOGIC (MULTI-DB SAFE)
    # --------------------------------------------------
    def save_model(self, request, obj, form, change):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        with transaction.atomic(using=db):
            obj.save(using=db)
            obj.recalc_totals(save=True)

    def save_related(self, request, form, formsets, change):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        for formset in formsets:
            instances = formset.save(commit=False)

            for obj in instances:
                obj.save(using=db)

            for obj in formset.deleted_objects:
                obj.delete(using=db)

            formset.save_m2m()

        form.instance.recalc_totals(save=True)

    # --------------------------------------------------
    # ACTIONS
    # --------------------------------------------------
    actions = [
        "action_recalc_totals",
        "action_mark_warehouse",
        "action_mark_packaging",
        "action_mark_ready_for_delivery",
        "action_mark_out_for_delivery",
        "action_mark_complete",
        "action_mark_cancelled",
    ]

    @admin.action(description="Recalculate totals for selected orders")
    def action_recalc_totals(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        n = 0
        for o in queryset.using(db):
            o.recalc_totals(save=True)
            n += 1

        self.message_user(request, f"Recalculated totals for {n} order(s).", level=messages.SUCCESS)

    @admin.action(description="Mark selected as Warehouse")
    def action_mark_warehouse(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        count = 0
        for obj in queryset.using(db):
            obj.status = "warehouse"
            obj.save(using=db)
            count += 1

        self.message_user(request, f"Updated {count} order(s) to Warehouse.", level=messages.SUCCESS)

    @admin.action(description="Mark selected as Packaging")
    def action_mark_packaging(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        count = 0
        for obj in queryset.using(db):
            obj.status = "packaging"
            obj.save(using=db)
            count += 1

        self.message_user(request, f"Updated {count} order(s) to Packaging.", level=messages.SUCCESS)

    @admin.action(description="Mark selected as Ready for Delivery")
    def action_mark_ready_for_delivery(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        count = 0
        for obj in queryset.using(db):
            obj.status = "ready_for_delivery"
            obj.save(using=db)
            count += 1

        self.message_user(request, f"Updated {count} order(s) to Ready for Delivery.", level=messages.SUCCESS)

    @admin.action(description="Mark selected as Out for Delivery")
    def action_mark_out_for_delivery(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        count = 0
        for obj in queryset.using(db):
            obj.status = "out_for_delivery"
            obj.save(using=db)
            count += 1

        self.message_user(request, f"Updated {count} order(s) to Out for Delivery.", level=messages.SUCCESS)

    @admin.action(description="Mark selected as Complete")
    def action_mark_complete(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        count = 0
        for obj in queryset.using(db):
            obj.status = "complete"
            obj.save(using=db)
            count += 1

        self.message_user(request, f"Updated {count} order(s) to Complete.", level=messages.SUCCESS)

    @admin.action(description="Mark selected as Cancelled")
    def action_mark_cancelled(self, request, queryset):
        db = "dummy" if request.path.startswith("/dummy-admin") else "default"

        count = 0
        for obj in queryset.using(db):
            obj.status = "cancelled"
            obj.save(using=db)
            count += 1

        self.message_user(request, f"Updated {count} order(s) to Cancelled.", level=messages.SUCCESS)
# (optional) register items for direct browsing
@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "category",
        "product",
        "sku",
        "product_name",
        "uom",
        "quantity",
        "unit_price_excl_display",
        "discount_excl",
        "vat_percent",
        "line_total_excl_display",
        "line_total_inc_display",
    )
    list_filter = ("category", "product__category")
    search_fields = ("sku", "product_name", "order__id", "product__name", "product__sku")
    autocomplete_fields = ("order", "category", "product")
    readonly_fields = ("sku", "product_name", "uom")

    @admin.display(description="Unit Price (Excl)")
    def unit_price_excl_display(self, obj: OrderItem):
        return money(obj.unit_price_excl)

    @admin.display(description="Line Total (Excl)")
    def line_total_excl_display(self, obj: OrderItem):
        return money(obj.line_total_excl)

    @admin.display(description="Line Total (Inc)")
    def line_total_inc_display(self, obj: OrderItem):
        return money(obj.line_total_inc)


@admin.register(OrderAudit)
class OrderAuditAdmin(admin.ModelAdmin):

    list_display = (
        "order",
        "action",
        "performed_by",
        "status_before",
        "status_after",
        "amount_before",
        "amount_after",
        "performed_at",
    )

    list_filter = (
        "action",
        "performed_at",
    )

    search_fields = (
        "order__id",
        "description",
        "performed_by__username",
    )

    readonly_fields = (
        "order",
        "action",
        "performed_by",
        "performed_at",
        "status_before",
        "status_after",
        "amount_before",
        "amount_after",
        "snapshot_before",
        "snapshot_after",
        "description",
    )

    ordering = ("-performed_at",)

    