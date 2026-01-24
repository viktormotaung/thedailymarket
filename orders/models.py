# orders/models.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.timezone import now

from clients.models import Client
from products.models import Product, Category


# ---------- local numeric helpers (avoid circular imports) ----------
def r2(x: Decimal | None) -> Decimal:
    """Round to 2 decimals (bankers style), treating None as 0.00."""
    if x is None:
        x = Decimal("0.00")
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ====================================================================
# Order
# ====================================================================
class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),                 
        ("approved", "Approved"),
        ("awaiting_payment", "Awaiting Payment"),              
        ("at_warehouse", "At Warehouse"),
        ("ready_for_delivery", "Ready for Delivery"),
        ("out_for_delivery", "Out for Delivery"),
        ("complete", "Complete"),
        ("returned", "Returned"),
        ("cancelled", "Cancelled"),
    ]

    CHANNELS = [
        ("WEB", "Web"),
        ("STAFF", "Staff-Captured"),
        ("API", "API"),
    ]

    # --- Ownership / identity ---
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="orders")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="orders_created",
        help_text="Null if self-serve; set if captured by staff.",
    )

    # --- Flow / timing ---
    channel = models.CharField(max_length=16, choices=CHANNELS, default="WEB")
    order_date = models.DateTimeField(default=now, editable=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default="pending")

    submitted_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="orders_reviewed",
        help_text="Staff member who reviewed the order.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="orders_approved",
        help_text="Staff member who approved the order.",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    customer_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True, help_text="Internal notes visible to staff only.")

    # --- Order-level totals (snapshots) ---
    discount_total_excl = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    delivery_fee_excl = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    delivery_fee_vat_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),  # not VAT-registered currently
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )

    subtotal_excl = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    grand_total_inc = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["submitted_at"]),
            models.Index(fields=["client", "status"]),
        ]

    def __str__(self):
        return f"Order #{self.pk or '—'} · {self.client} · {self.status}"

    # ---- Convenience ----
    @property
    def is_approved(self) -> bool:
        return self.status == "approved" and self.approved_at is not None

    def mark_reviewed(self, user):
        self.reviewed_by = user
        self.reviewed_at = now()
        self.save(update_fields=["reviewed_by", "reviewed_at", "updated_at"])

    def ensure_delivery_artifacts(self) -> bool:
        """
        Make sure delivery-related rows exist for this order:
        - DeliveryReceipt (1:1 with Order)
        - DeliveryPickList (+ DeliveryPickItem rows cloned from Order items)

        Returns True if anything was created; False if everything already existed.
        """
        DeliveryReceipt = apps.get_model("deliveries", "DeliveryReceipt")
        DeliveryPickList = apps.get_model("deliveries", "DeliveryPickList")
        DeliveryPickItem = apps.get_model("deliveries", "DeliveryPickItem")

        created_any = False

        with transaction.atomic():
            # 1) Receipt (for client signature on delivery)
            _, created = DeliveryReceipt.objects.get_or_create(
                order=self,
                defaults={
                    "client": self.client,
                    "status": "pending",
                },
            )
            created_any = created or created_any

            # 2) Pick list (for the warehouse)
            pick, created = DeliveryPickList.objects.get_or_create(
                order=self,
                defaults={
                    "client": self.client,
                    "status": "pending",
                },
            )
            created_any = created or created_any

            # If we just created the pick list, populate its items from the order items
            if created:
                items_to_create = []
                for oi in self.items.select_related("product"):
                    items_to_create.append(
                        DeliveryPickItem(
                            pick_list=pick,
                            product=oi.product,                                # FK to Product
                            product_name=oi.product_name or oi.product.name,   # snapshot
                            sku=oi.sku or oi.product.sku,                      # snapshot
                            uom=oi.uom or oi.product.uom,                      # snapshot
                            quantity=oi.quantity,
                        )
                    )
                if items_to_create:
                    DeliveryPickItem.objects.bulk_create(items_to_create)

        return created_any

    def mark_approved(self, user):
        """
        Mark approved and ensure an invoice exists.
        Also ensures delivery artifacts exist (non-blocking).
        """
        self.approved_by = user
        self.approved_at = now()
        self.status = "approved"
        self.save(update_fields=["approved_by", "approved_at", "status", "updated_at"])

        # Create invoice if it doesn't exist
        try:
            self.invoice  # touching relation
        except Exception:
            from invoices.models import Invoice  # lazy import to avoid circulars
            if not Invoice.objects.filter(order=self).exists():
                Invoice.create_for_order(self)

        # Ensure delivery artefacts (don't block on failure)
        try:
            self.ensure_delivery_artifacts()
        except Exception:
            pass

    # ---- Delivery VAT ----
    @property
    def delivery_fee_vat_amount(self) -> Decimal:
        return r2(self.delivery_fee_excl * (self.delivery_fee_vat_percent / Decimal("100")))

    # ---- Totals rollup ----
    def recalc_totals(self, save: bool = False):
        items = list(self.items.all())
        sub_excl = sum((i.line_total_excl or Decimal("0.00")) for i in items)
        vat_items = sum((i.line_vat_amount or Decimal("0.00")) for i in items)

        sub_after_discount = r2(sub_excl - (self.discount_total_excl or Decimal("0.00")))
        deliv_vat = self.delivery_fee_vat_amount
        deliv_inc = r2(self.delivery_fee_excl + deliv_vat)

        self.subtotal_excl = sub_after_discount
        self.vat_total = r2(vat_items + deliv_vat)
        self.grand_total_inc = r2(self.subtotal_excl + self.vat_total + deliv_inc)

        if save:
            self.save(update_fields=["subtotal_excl", "vat_total", "grand_total_inc", "updated_at"])

    def _audit_snapshot(self) -> dict:
        """
        Small, safe JSON snapshot used in the audit trail.
        Keep this light so logs stay readable.
        """
        return {
            "id": self.pk,
            "client_id": self.client_id,
            "client": str(self.client),
            "status": self.status,
            "totals": {
                "subtotal_excl": str(self.subtotal_excl or Decimal("0.00")),
                "vat_total": str(self.vat_total or Decimal("0.00")),
                "grand_total_inc": str(self.grand_total_inc or Decimal("0.00")),
            },
            "items_count": self.items.count(),
            "invoice_id": getattr(getattr(self, "invoice", None), "id", None),
        }

    @transaction.atomic
    def delete_with_audit(
        self,
        *,
        request,                 # pass the current request so we can record actor/IP/UA
        reason: str = "",
        auth_verified: bool = False,
        auth_method: str = "",   # e.g. "staff_code"
        extra: dict | None = None,
    ):
        """
        Logs an 'order_delete' audit event and then deletes the order
        within the same DB transaction. If the delete fails, the log
        also rolls back.
        """
        from audit.utils import log_event  # lazy import

        before = self._audit_snapshot()

        # Write the audit row first; lives/dies with this transaction
        log_event(
            request=request,
            action="order_delete",
            obj=self,
            reason=reason,
            auth_verified=auth_verified,
            auth_method=auth_method or "",
            before_snapshot=before,
            extra=extra or {},
        )

        # Perform the actual deletion (will cascade to items by FK)
        super(Order, self).delete()

    # ---- Credit gate (enforce only when there is outstanding credit) ----
    def _enforce_credit_rule_on_create(self):
        """
        Enforce: if client has ACTIVE credit **and** outstanding credit_used > 0,
        require that the most recent repayment after the last credit-out is >= 50%
        of that credit-out before allowing a new order.

        This allows first orders / COD-only clients or clients with zero utilisation
        to place orders without being blocked.
        """
        # Only for brand new orders
        if self.pk is not None:
            return

        # Enforce only for ACTIVE credit clients
        status = (getattr(self.client, "credit_status", "") or "").upper()
        if status != "ACTIVE":
            return

        # If no account or no outstanding utilisation, do not block
        try:
            credit_account = getattr(self.client, "credit_account", None)
            if credit_account is None:
                return
            used = getattr(credit_account, "credit_used", Decimal("0.00")) or Decimal("0.00")
            if used <= Decimal("0.00"):
                # Nothing outstanding -> skip the rule
                return
        except Exception:
            # If we cannot read the account safely, do not block checkout
            return

        # There is outstanding usage: now enforce the 50% repayment rule
        try:
            from credit.models import CreditEntry  # lazy import to avoid cycles
            ok, reason = CreditEntry.check_50pct_rule(self.client)
        except Exception:
            # Fail-open: if credit module/logic is unavailable, don't block web checkout
            ok, reason = True, ""

        if not ok:
            nice_reason = reason or (
                "Outstanding credit requires a repayment of at least 50% before a new order."
            )
            # Attach to 'client' field for a friendly form error
            raise ValidationError({"client": nice_reason})


# ====================================================================
# OrderItem
# ====================================================================
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")

    # selection
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="order_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")

    # snapshots (auto-filled from Product)
    sku = models.CharField(max_length=64, blank=True, help_text="Snapshot of product SKU at order time.")
    product_name = models.CharField(max_length=220, blank=True, help_text="Snapshot of product name at order time.")
    uom = models.CharField(max_length=8, choices=Product.UOM_CHOICES, blank=True)

    # pricing
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    unit_price_excl = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        default=Decimal("0.00"),
    )
    unit_price_inc = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        default=Decimal("0.00"),
    )
    discount_excl = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    vat_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )

    class Meta:
        ordering = ["order_id", "id"]
        indexes = [
            models.Index(fields=["order", "product"]),
        ]

    # ---- computed totals ----
    @property
    def line_total_excl(self) -> Decimal:
        unit_minus_disc = max(
            Decimal("0.00"),
            (self.unit_price_excl or Decimal("0.00")) - (self.discount_excl or Decimal("0.00")),
        )
        return r2(unit_minus_disc * (self.quantity or Decimal("0.00")))

    @property
    def line_vat_amount(self) -> Decimal:
        return r2(self.line_total_excl * (self.vat_percent / Decimal("100")))

    @property
    def line_total_inc(self) -> Decimal:
        return r2(self.unit_price_inc * (self.quantity or Decimal("0.00")))

    # ---------- helper ----------
    def _client_price_mode(self) -> str:
        return "WHOLESALE"

    # ---------- autofill helpers ----------
    def _prefill_from_product(self):
        if not self.product_id:
            return

        # Snapshots
        if not self.sku:
            self.sku = self.product.sku
        if not self.product_name:
            self.product_name = self.product.name
        if not self.uom:
            self.uom = self.product.uom

        # Only derive if price is not set
        if (self.unit_price_excl or Decimal("0.00")) == Decimal("0.00"):
            pr_qs = self.product.pricing_rows.filter(is_active=True)
            best_price_excl = None
            best_price_inc = None
            best_vat = None

            for pr in pr_qs:
                price_excl = pr.wholesale_price_excl
                price_inc = pr.wholesale_price_inc
                vat_pct = pr.wholesale_vat_percent

                if price_excl is None or price_excl <= Decimal("0.00"):
                    continue

                if best_price_excl is None or price_excl < best_price_excl:
                    best_price_excl = price_excl
                    best_price_inc = price_inc
                    best_vat = vat_pct

            if best_price_excl is not None:
                self.unit_price_excl = best_price_excl
                self.unit_price_inc = best_price_inc or best_price_excl
                if (self.vat_percent or Decimal("0.00")) == Decimal("0.00") and best_vat is not None:
                    self.vat_percent = best_vat

    def clean(self):
        super().clean()
        if not self.category_id:
            raise ValidationError("Please select a category.")
        if not self.product_id:
            raise ValidationError("Please select a product.")
        if self.product and self.product.category_id != self.category_id:
            raise ValidationError("Selected product is not in the chosen category.")

        # Ensure unit prices exist
        if (self.unit_price_excl or Decimal("0.00")) == Decimal("0.00"):
            self._prefill_from_product()
            if (self.unit_price_excl or Decimal("0.00")) == Decimal("0.00"):
                raise ValidationError("No active pricing found for this product; please enter a unit price.")

    def save(self, *args, **kwargs):
        self._prefill_from_product()
        super().save(*args, **kwargs)
        if self.order_id:
            self.order.recalc_totals(save=True)

