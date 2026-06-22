# orders/models.py
from __future__ import annotations
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from django.db import transaction
import threading
import time
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.timezone import now
from django.conf import settings

from clients.models import Client
from products.models import Product, Category


# ---------- local numeric helpers (avoid circular imports) ----------
def r2(x: Decimal | None) -> Decimal:
    """Round to 2 decimals (bankers style), treating None as 0.00."""
    if x is None:
        x = Decimal("0.00")
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ====================================================================
# Quotation
# ====================================================================
class Quotation(models.Model):

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("expired", "Expired"),
    ]

    # =========================================================
    # RELATIONS
    # =========================================================

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="quotations",
        null=True,
        blank=True,
    )

    prospect = models.ForeignKey(
        "clients.Prospect",
        on_delete=models.CASCADE,
        related_name="quotations",
        null=True,
        blank=True,
    )

    converted_order = models.OneToOneField(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_quotation",
        help_text="Order created from this quotation."
    )

    # =========================================================
    # USERS / AUDIT
    # =========================================================

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotations_created",
        help_text="Logged-in user who created this quotation."
    )

    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotations_accepted",
    )

    accepted_at = models.DateTimeField(null=True, blank=True)

    rejected_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.TextField(
        blank=True,
        null=True,
    )

    public_decision_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    public_decision_user_agent = models.TextField(
        blank=True,
        null=True,
    )

    # =========================================================
    # CORE
    # =========================================================

    quotation_date = models.DateTimeField(default=now)

    public_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    valid_until = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        db_index=True,
    )

    customer_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # =========================================================
    # FINANCIALS
    # =========================================================

    discount_total_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    delivery_fee_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    delivery_fee_vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00")
    )

    subtotal_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    vat_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    grand_total_inc = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    # =========================================================
    # TIMESTAMPS
    # =========================================================

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # =========================================================
    # META
    # =========================================================

    class Meta:
        ordering = ["-created_at"]

        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["prospect", "status"]),
            models.Index(fields=["quotation_date"]),
            models.Index(fields=["valid_until"]),
            models.Index(fields=["created_by"]),
            models.Index(fields=["converted_order"]),
        ]

    # =========================================================
    # DISPLAY
    # =========================================================

    @property
    def target(self):
        return self.client or self.prospect

    def __str__(self):
        return f"Quotation #{self.pk or '—'} · {self.target} · {self.status}"

    # =========================================================
    # VALIDATION
    # =========================================================

    def clean(self):
        super().clean()

        # Must belong to ONE target
        if not self.client and not self.prospect:
            raise ValidationError(
                "Quotation must be linked to either a client or a prospect."
            )

        # Cannot belong to both
        if self.client and self.prospect:
            raise ValidationError(
                "Quotation cannot be linked to both a client and a prospect."
            )

    # =========================================================
    # TOTALS
    # =========================================================

    def recalc_totals(self, save=False):

        items = list(self.items.all())

        sub_excl = sum(
            (i.line_total_excl or Decimal("0.00"))
            for i in items
        )

        vat_items = sum(
            (i.line_vat_amount or Decimal("0.00"))
            for i in items
        )

        sub_after_discount = r2(
            sub_excl - (self.discount_total_excl or Decimal("0.00"))
        )

        delivery_vat = r2(
            (self.delivery_fee_excl or Decimal("0.00")) *
            (
                (self.delivery_fee_vat_percent or Decimal("0.00"))
                / Decimal("100")
            )
        )

        self.subtotal_excl = r2(sub_after_discount)

        self.vat_total = r2(
            vat_items + delivery_vat
        )

        self.grand_total_inc = r2(
            self.subtotal_excl +
            self.vat_total +
            (self.delivery_fee_excl or Decimal("0.00"))
        )

        if save:
            super().save(update_fields=[
                "subtotal_excl",
                "vat_total",
                "grand_total_inc",
                "updated_at",
            ])

    # =========================================================
    # HELPERS
    # =========================================================

    def can_edit(self):
        return (
            self.status in ["draft", "sent"]
            and self.converted_order_id is None
        )

    def is_converted(self):
        return self.converted_order_id is not None

    def can_convert_to_order(self):
        return (
            self.status == "accepted"
            and self.converted_order_id is None
        )
    


    def save(self, *args, **kwargs):
        old_status = None

        if self.pk:
            old_status = (
                Quotation.objects
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )

        super().save(*args, **kwargs)

        if (
            self.status == "accepted"
            and old_status != "accepted"
            and not self.converted_order_id
        ):
            print("========== QUOTATION ACCEPTED: START CONVERSION ==========")
            self.convert_to_order(
                user=self.accepted_by or self.created_by
            )
            print("========== QUOTATION ACCEPTED: CONVERSION COMPLETE ==========")
    





    # =========================================================
    # CONVERSION
    # =========================================================

    @transaction.atomic
    def convert_to_order(self, user=None):

        # Already converted
        if self.converted_order_id:
            return self.converted_order

        # Must be accepted
        if self.status != "accepted":
            raise ValidationError(
                "Only accepted quotations can be converted to orders."
            )

        # Must have items
        if not self.items.exists():
            raise ValidationError(
                "Quotation must have at least one item before conversion."
            )

        # =====================================================
        # IF QUOTATION HAS PROSPECT BUT NO CLIENT
        # Convert prospect into client first
        # =====================================================
        if not self.client and self.prospect:

            prospect = self.prospect

            # Mark prospect as WON
            if prospect.stage != "WON":
                prospect.stage = "WON"
                prospect.save(update_fields=["stage", "updated_at"])

            # This creates client if missing, or returns existing client
            client = prospect.convert_to_client()

            # Ensure client is active
            if client.status != "ACTIVE":
                client.status = "ACTIVE"
                client.save(update_fields=["status", "updated_at"])

            # Link quotation to client
            # Clear prospect because your clean() does not allow both
            self.client = client
            self.prospect = None
            super().save(update_fields=[
                "client",
                "prospect",
                "updated_at",
            ])

        # Final safety check
        if not self.client:
            raise ValidationError(
                "Quotation must be linked to a client before conversion to an order."
            )

        # =====================================================
        # CREATE ORDER
        # =====================================================
        order = Order.objects.create(
            client=self.client,
            created_by=user or self.created_by,
            channel="STAFF",
            order_date=now(),
            status="pending",

            customer_notes=self.customer_notes,

            notes=(
                f"Created from Quotation #{self.pk}\n\n"
                f"{self.notes}"
            ).strip(),

            discount_total_excl=self.discount_total_excl,
            delivery_fee_excl=self.delivery_fee_excl,
            delivery_fee_vat_percent=self.delivery_fee_vat_percent,
        )

        # =====================================================
        # COPY ITEMS
        # =====================================================
        for q_item in self.items.all():

            OrderItem.objects.create(
                order=order,

                category=q_item.category,
                product=q_item.product,

                sku=q_item.sku,
                product_name=q_item.product_name,
                uom=q_item.uom,

                quantity=q_item.quantity,

                unit_price_excl=q_item.unit_price_excl,
                unit_price_inc=q_item.unit_price_inc,

                discount_excl=q_item.discount_excl,
                vat_percent=q_item.vat_percent,
            )

        # =====================================================
        # RECALCULATE ORDER
        # =====================================================
        order.recalc_totals(save=True)

        
        from tasks.services import create_order_verification_task

        transaction.on_commit(
            lambda: create_order_verification_task(order)
        )
        

        # =====================================================
        # LINK QUOTATION
        # =====================================================
        self.converted_order = order
        super().save(update_fields=[
            "converted_order",
            "updated_at",
        ])

        return order
    
    
# ====================================================================
# Quotation Item
# ====================================================================
class QuotationItem(models.Model):

    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        related_name="items"
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="quotation_items"
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="quotation_items"
    )

    sku = models.CharField(max_length=64, blank=True)
    product_name = models.CharField(max_length=220, blank=True)
    uom = models.CharField(max_length=8, choices=Product.UOM_CHOICES, blank=True)

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    unit_price_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    unit_price_inc = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    discount_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )

    class Meta:
        ordering = ["quotation_id", "id"]
        indexes = [
            models.Index(fields=["quotation", "product"]),
        ]

    def __str__(self):
        return f"{self.product_name or self.product} x {self.quantity}"

    @property
    def line_total_excl(self):
        unit_minus_discount = max(
            Decimal("0.00"),
            (self.unit_price_excl or Decimal("0.00")) -
            (self.discount_excl or Decimal("0.00"))
        )
        return r2(unit_minus_discount * (self.quantity or Decimal("0.00")))

    @property
    def line_vat_amount(self):
        return r2(
            self.line_total_excl *
            ((self.vat_percent or Decimal("0.00")) / Decimal("100"))
        )

    @property
    def line_total_inc(self):
        return r2(self.line_total_excl + self.line_vat_amount)

    def _prefill_from_product(self):
        if not self.product_id:
            return

        if not self.sku:
            self.sku = self.product.sku

        if not self.product_name:
            self.product_name = self.product.name

        if not self.uom:
            self.uom = self.product.uom

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

        if (self.unit_price_excl or Decimal("0.00")) == Decimal("0.00"):
            self._prefill_from_product()

            if (self.unit_price_excl or Decimal("0.00")) == Decimal("0.00"):
                raise ValidationError("No active pricing found for this product.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            self._prefill_from_product()
            super().save(*args, **kwargs)

            if self.quotation_id:
                self.quotation.recalc_totals(save=True)

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
        ("credit_blocked", "Credit Blocked"),
    ]

    CHANNELS = [
        ("WEB", "Web"),
        ("STAFF", "Staff-Captured"),
        ("API", "API"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="orders")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="orders_created",
    )

    channel = models.CharField(max_length=16, choices=CHANNELS, default="WEB")
    order_date = models.DateTimeField(default=now, editable=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default="pending")

    submitted_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="orders_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="orders_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    customer_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    discount_total_excl = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    delivery_fee_excl = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    delivery_fee_vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

    subtotal_excl = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    grand_total_inc = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"Order #{self.pk or '—'} · {self.client} · {self.status}"

    # -------------------------------------------------
    # Totals
    # -------------------------------------------------
    def recalc_totals(self, save=False):
        items = list(self.items.all())
        sub_excl = sum((i.line_total_excl or Decimal("0.00")) for i in items)
        vat_items = sum((i.line_vat_amount or Decimal("0.00")) for i in items)

        sub_after_discount = r2(sub_excl - (self.discount_total_excl or Decimal("0.00")))
        deliv_vat = r2(self.delivery_fee_excl * (self.delivery_fee_vat_percent / Decimal("100")))
        deliv_inc = r2(self.delivery_fee_excl + deliv_vat)

        self.subtotal_excl = sub_after_discount
        self.vat_total = r2(vat_items + deliv_vat)
        self.grand_total_inc = r2(self.subtotal_excl + self.vat_total + deliv_inc)

        if save:
            super().save(update_fields=["subtotal_excl", "vat_total", "grand_total_inc", "updated_at"])

    # -------------------------------------------------
    # Snapshot
    # -------------------------------------------------
    def _audit_snapshot(self):
        return {
            "id": self.pk,
            "client": str(self.client),
            "status": self.status,
            "grand_total_inc": str(self.grand_total_inc),
            "invoice_id": getattr(getattr(self, "invoice", None), "id", None),
        }

    # -------------------------------------------------
    # SAVE
    # -------------------------------------------------
    @transaction.atomic
    def save(self, *args, **kwargs):
        from invoices.models import Invoice
        from decimal import Decimal
        from django.core.exceptions import ValidationError
        from django.db import transaction
        import threading
        import time

        print("\n================ ORDER SAVE START ================")

        creating = self.pk is None
        old_status = None
        before_snapshot = None

        if not creating:
            try:
                old = Order.objects.using(self._state.db).get(pk=self.pk)
                old_status = old.status
                before_snapshot = old._audit_snapshot()
            except Order.DoesNotExist:
                pass

        print(f"[DEBUG] Creating: {creating}")
        print(f"[DEBUG] Old status: {old_status}")
        print(f"[DEBUG] New status (before save): {self.status}")

        super().save(*args, **kwargs)

        
        print(f"[DEBUG] Order {self.pk} saved with status: {self.status}")

        

        action = OrderAudit.CREATED if creating else OrderAudit.UPDATED
        if old_status != self.status:
            action = OrderAudit.STATUS_CHANGED

        # =================================================
        # WEB AUTO-APPROVAL (Delayed 2 seconds)
        # =================================================
        if creating and self.channel == "WEB" and self.status == "pending":

            print("[DEBUG] Scheduling WEB auto-approval in 2 seconds")

    
            def delayed_auto_approve(order_id, db):
                time.sleep(2)
                try:
                    order = Order.objects.using(db).get(pk=order_id)

                    if (
                        order.channel == "WEB"
                        and order.status == "pending"
                        and order.items.exists()
                    ):
                        print(f"[AUTO] Auto-approving Order {order.pk}")
                        order.status = "approved"
                        order.save(update_fields=["status", "updated_at"])
                    else:
                        print(f"[AUTO] Conditions not met for Order {order.pk}")

                except Exception as e:
                    print(f"[AUTO] Auto-approval failed: {e}")

            transaction.on_commit(
                lambda: threading.Thread(
                    target=delayed_auto_approve,
                    args=(self.pk, self._state.db),  # ✅ comma added
                    daemon=True
                ).start()
            )

        # -------------------------------------------------
        # APPROVED → trigger second save (ONLY IF ITEMS EXIST)
        # -------------------------------------------------
        if old_status != "approved" and self.status == "approved":

            print(f"[DEBUG] APPROVAL TRIGGERED for Order {self.pk}")

            # 🚨 Enforce items exist
            if not self.items.exists():
                print("[DEBUG] APPROVAL BLOCKED — NO ITEMS FOUND")
                raise ValidationError("Order must contain at least one item before approval.")

            # Log approval FIRST
            OrderAudit.objects.using(self._state.db).create(
                order=self,
                action=OrderAudit.APPROVED,
                performed_by=self.approved_by or self.created_by,
                status_before=old_status or "",
                status_after="approved",
                amount_before=(
                    Decimal(before_snapshot.get("grand_total_inc", "0.00"))
                    if before_snapshot else None
                ),
                amount_after=self.grand_total_inc,
                snapshot_before=before_snapshot,
                snapshot_after=self._audit_snapshot(),
                description="Order approved",
            )

            print(f"[DEBUG] Moving Order {self.pk} to awaiting_payment")

            self.status = "awaiting_payment"
            self.save(update_fields=["status", "updated_at"])
            print(f"[DEBUG] Second save complete → status now: {self.status}")
            print("================ ORDER SAVE END (APPROVAL) ================\n")
            return

        
        # -------------------------------------------------
        # FINANCIAL GATE (STATE-BASED + BULLETPROOF)
        # -------------------------------------------------
        if self.status in ["awaiting_payment"]:

            print(f"[DEBUG] ENTERING FINANCIAL GATE for Order {self.pk}")

            db = self._state.db or "default"

            # ✅ Always recalc totals safely
            self.recalc_totals(save=True)

            print(f"[DEBUG] Totals recalculated → Grand Total: {self.grand_total_inc}")

            client = self.client
            credit_status = (getattr(client, "credit_status", "") or "").upper()
            credit_account = getattr(client, "credit_account", None)

            print(f"[DEBUG] Credit status: {credit_status}")

            # =================================================
            # CREDIT CHECK
            # =================================================
            if (
                self.status == "awaiting_payment"
                and credit_status == "ACTIVE"
                and credit_account
            ):

                total = self.grand_total_inc or Decimal("0.00")

                # -------------------------------------------------
                # FIXED: DO NOT CONVERT 0% TO 100%
                # -------------------------------------------------
                raw_deposit_pct = getattr(
                    credit_account,
                    "credit_deposit_pct",
                    None
                )

                if raw_deposit_pct is None:
                    deposit_pct = Decimal("100.00")
                else:
                    deposit_pct = Decimal(str(raw_deposit_pct))

                deposit_required = r2(
                    total * (deposit_pct / Decimal("100"))
                )

                credit_required = r2(
                    total - deposit_required
                )

                credit_available = (
                    credit_account.credit_available
                    or Decimal("0.00")
                )

                print(f"[DEBUG] Deposit %: {deposit_pct}")
                print(f"[DEBUG] Deposit Required: {deposit_required}")
                print(f"[DEBUG] Credit Required: {credit_required}")
                print(f"[DEBUG] Credit Available: {credit_available}")

                # -------------------------------------------------
                # BLOCK IF CREDIT EXCEEDED
                # -------------------------------------------------
                if credit_required > credit_available:

                    print("[DEBUG] CREDIT BLOCKED")

                    self.status = "credit_blocked"

                    super().save(
                        update_fields=[
                            "status",
                            "updated_at",
                        ]
                    )

                    OrderAudit.objects.using(db).create(
                        order=self,
                        action=OrderAudit.CREDIT_BLOCKED,
                        performed_by=(
                            self.approved_by
                            or self.created_by
                        ),
                        status_before="awaiting_payment",
                        status_after="credit_blocked",
                        amount_before=self.grand_total_inc,
                        amount_after=self.grand_total_inc,
                        snapshot_before=before_snapshot,
                        snapshot_after=self._audit_snapshot(),
                        description=(
                            f"Credit insufficient. "
                            f"Required: {credit_required}, "
                            f"Available: {credit_available}"
                        ),
                    )

                    print(
                        "================ ORDER SAVE END (BLOCKED) ================\n"
                    )

                    return  # 🚨 STOP EXECUTION

            # =================================================
            # 🔥 BULLETPROOF INVOICE CREATION
            # =================================================
            from invoices.models import Invoice

            invoice_exists = (
                Invoice.objects.using(db)
                .filter(order=self)
                .exists()
            )

            print(f"[DEBUG] Invoice exists? {invoice_exists}")

            if not invoice_exists:

                print("[DEBUG] Creating invoice now...")

                Invoice.create_for_order(self)

                print("[DEBUG] Invoice created.")

            else:

                print("[DEBUG] Invoice already exists — updating invoice...")

                invoice = Invoice.objects.using(db).get(order=self)

                invoice.calculate_totals()

                invoice.save(
                    using=db,
                    update_fields=[
                        "order_total_inc",
                        "amount_due",
                        "deposit_required",
                        "credit_used",
                        "due_date",
                        "updated_at",
                    ],
                )

                invoice.ensure_invoice_out_txn()
                invoice.ensure_credit_after_deposit()

                print("[DEBUG] Invoice updated.")

            # -------------------------------------------------
            # FINAL AUDIT
            # -------------------------------------------------
            print(f"[DEBUG] Final audit action: {action}")

            OrderAudit.objects.using(db).create(
                order=self,
                action=action,
                performed_by=(
                    self.approved_by
                    or self.reviewed_by
                    or self.created_by
                ),
                status_before=old_status or "",
                status_after=self.status,
                amount_before=(
                    Decimal(
                        before_snapshot.get(
                            "grand_total_inc",
                            "0.00"
                        )
                    )
                    if before_snapshot
                    else None
                ),
                amount_after=self.grand_total_inc,
                snapshot_before=before_snapshot,
                snapshot_after=self._audit_snapshot(),
                description="Automatic system audit entry",
            )

            print("================ ORDER SAVE END ================\n")

            
            
        
class OrderAudit(models.Model):

    # -------------------------------------------------
    # RELATION
    # -------------------------------------------------
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="audits"
    )

    # -------------------------------------------------
    # ACTION TYPE
    # -------------------------------------------------
    CREATED         = "created"
    UPDATED         = "updated"
    STATUS_CHANGED  = "status_changed"
    CREDIT_BLOCKED  = "credit_blocked"
    APPROVED        = "approved"
    CANCELLED       = "cancelled"
    DELETED         = "deleted"

    ACTION_CHOICES = [
        (CREATED, "Created"),
        (UPDATED, "Updated"),
        (STATUS_CHANGED, "Status Changed"),
        (CREDIT_BLOCKED, "Credit Blocked"),
        (APPROVED, "Approved"),
        (CANCELLED, "Cancelled"),
        (DELETED, "Deleted"),
    ]

    action = models.CharField(
        max_length=32,
        choices=ACTION_CHOICES,
    )

    # -------------------------------------------------
    # USER + TIMESTAMP
    # -------------------------------------------------
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_audit_actions",
    )

    performed_at = models.DateTimeField(auto_now_add=True)

    # -------------------------------------------------
    # SNAPSHOTS
    # -------------------------------------------------
    status_before = models.CharField(
        max_length=32,
        blank=True,
    )
    status_after = models.CharField(
        max_length=32,
        blank=True,
    )

    amount_before = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    amount_after = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Optional structured state capture
    snapshot_before = models.JSONField(
        null=True,
        blank=True,
    )
    snapshot_after = models.JSONField(
        null=True,
        blank=True,
    )

    # -------------------------------------------------
    # DESCRIPTION
    # -------------------------------------------------
    description = models.TextField(blank=True)

    # -------------------------------------------------
    # META
    # -------------------------------------------------
    class Meta:
        ordering = ["-performed_at", "-id"]
        indexes = [
            models.Index(fields=["order", "performed_at"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"Order #{self.order_id} · {self.action} · {self.performed_at}"


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
        from decimal import Decimal
        from django.db import transaction

        with transaction.atomic():

            # ------------------------------------------
            # 1️⃣ Prefill pricing + save item
            # ------------------------------------------
            self._prefill_from_product()
            super().save(*args, **kwargs)

            if not self.order_id:
                return

            order = self.order

            # ------------------------------------------
            # 2️⃣ Recalculate order totals
            # ------------------------------------------
            order.recalc_totals(save=True)

            