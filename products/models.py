# models.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
import re
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction, IntegrityError
from django.db.models import Q
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.text import slugify

# ---------- Context flags ------------------------------------------------------
# Used to prevent variant sync in product_post_save when set True in this thread/context.
SKIP_VARIANT_SYNC: ContextVar[bool] = ContextVar("SKIP_VARIANT_SYNC", default=False)

# ---------- Constants & helpers ------------------------------------------------
SKU_NUM_WIDTH = 3  # -> 001, 002, ...

D0 = Decimal("0.00")
D1 = Decimal("1.00")


def r2(x: Decimal | None) -> Decimal:
    """Round to 2dp; None -> 0.00 to keep admin displays simple."""
    if x is None:
        return D0
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _d(x) -> Decimal:
    """Coerce None -> 0 and anything else to Decimal safely."""
    return x if isinstance(x, Decimal) else (Decimal(str(x)) if x is not None else D0)


def make_abbreviation_3(name: str) -> list[str]:
    """
    Build a small list of 3-letter uppercase abbreviation candidates from a name.
    """
    if not name:
        return ["CAT"]

    words = re.findall(r"[A-Za-z]+", name.upper())
    letters = re.sub(r"[^A-Za-z]", "", name).upper() or "CAT"

    cands: list[str] = []

    if len(words) >= 3:
        cands.append((words[0][0] + words[1][0] + words[2][0])[:3])
    if len(words) == 2:
        w1, w2 = words
        cands.append((w1[0] + (w2[:2] if len(w2) >= 2 else (w2[0] * 2)))[:3])
    if len(words) == 1:
        w = words[0]
        pad = w[-1] if len(w) else "X"
        cands.append((w[:3] + pad * 3)[:3])

    for i in range(max(1, len(letters) - 5)):  # a few windows
        if i + 3 <= len(letters):
            cands.append(letters[i:i+3])

    seen = set()
    dedup = []
    for c in cands:
        c = c[:3]
        if len(c) == 3 and c not in seen:
            seen.add(c)
            dedup.append(c)
    return dedup or ["CAT"]


def _sku_prefix(category) -> str:
    abbr = (getattr(category, "abbreviation", "") or category.name[:3]).upper()
    abbr = re.sub(r"[^A-Z0-9]", "", abbr)[:3]
    return abbr.ljust(3, "X")


def _next_sku_for_category(category) -> str:
    prefix = _sku_prefix(category)
    skus = (
        Product.objects.filter(category=category, sku__startswith=prefix)
        .values_list("sku", flat=True)
    )
    max_n = 0
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for s in skus:
        m = pat.match(s or "")
        if m:
            try:
                n = int(m.group(1))
                max_n = max(max_n, n)
            except ValueError:
                pass
    return f"{prefix}{max_n + 1:0{SKU_NUM_WIDTH}d}"


# ---------- Category -----------------------------------------------------------
class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    # strictly 3-letter abbreviation
    abbreviation = models.CharField(
        max_length=3, blank=True, db_index=True,
        help_text="3-letter code auto-generated from name (you can override).",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["abbreviation"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        if not self.abbreviation:
            candidates = make_abbreviation_3(self.name)
            abbr = None
            for cand in candidates:
                exists = Category.objects.exclude(pk=self.pk).filter(abbreviation=cand).exists()
                if not exists:
                    abbr = cand
                    break
            self.abbreviation = (abbr or candidates[0])[:3]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ---------- Product ------------------------------------------------------------
class Product(models.Model):
    UOM_CHOICES = [
        ("EA", "Each"),
        ("KG", "Kilogram"),
        ("L", "Litre"),
        ("PK", "Pack"),
        ("BOX", "Box"),
    ]

    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")

    sku = models.CharField(max_length=64, blank=True, null=True)
    slug = models.SlugField(max_length=220, blank=True, null=True)
    image = models.ImageField(upload_to="product_images/", blank=True, null=True)
    uom = models.CharField(max_length=8, choices=UOM_CHOICES, default="EA")

    # Base (ex VAT)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_margin_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("15.00"))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["category"]),
        ]

    # ----- Price helpers -----
    def set_retail_from_wholesale(self, margin_pct: Optional[Decimal] = None, rounding: str = "0.01") -> None:
        pct = Decimal(margin_pct) if margin_pct is not None else _d(self.retail_margin_pct)
        base = _d(self.wholesale_price)
        self.retail_price = (base * (D1 + (pct / Decimal("100")))).quantize(
            Decimal(rounding), rounding=ROUND_HALF_UP
        )

    def price_for_channel(self, channel: str = "wholesale") -> Decimal:
        if (channel or "").lower() == "retail":
            return r2(self.retail_price)
        return r2(self.wholesale_price)

    def sync_variant_prices(self, *, force: bool = True) -> int:
        """
        Push current product prices to variant overrides (ex VAT) where scales_with_pack=True.
        If force=False, only seed when overrides are empty/zero.
        Returns number of variants updated.
        """
        base_wh = self.price_for_channel("wholesale") or D0
        base_rt = self.price_for_channel("retail") or D0
        updated = 0

        with transaction.atomic():
            for v in self.variants.select_for_update().all():
                if not v.scales_with_pack or not v.pack_size:
                    continue

                derived_wh = r2(base_wh * _d(v.pack_size))
                derived_rt = r2(base_rt * _d(v.pack_size))

                set_wh = force or (v.wholesale_price_override in (None, D0))
                set_rt = force or (v.retail_price_override in (None, D0))

                changed = False
                if set_wh and v.wholesale_price_override != derived_wh:
                    v.wholesale_price_override = derived_wh
                    changed = True
                if set_rt and v.retail_price_override != derived_rt:
                    v.retail_price_override = derived_rt
                    changed = True

                if changed:
                    v.save(update_fields=["wholesale_price_override", "retail_price_override", "updated_at"])
                    updated += 1
        return updated

    def clean(self):
        for fld in ("cost_price", "wholesale_price", "retail_price"):
            val = getattr(self, fld, None)
            if val is not None and val < D0:
                raise ValidationError({fld: "Value must be zero or positive."})

    def save(self, *args, **kwargs):
        """
        Auto-generate SKU on create if blank: <CATEGORY_ABBR><NNN> (e.g., CHK001).
        Keep slug + retail seeding; tiny retry to avoid rare SKU race.
        """
        if not self.sku and self.category_id:
            for _ in range(5):
                self.sku = _next_sku_for_category(self.category)
                if not self.slug:
                    base = slugify(self.name) or slugify(self.sku)
                    self.slug = f"{base}-{self.sku}".lower()[:220]
                if (self.retail_price in (None, D0)) and self.wholesale_price is not None:
                    self.set_retail_from_wholesale()
                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    self.sku = None
                    continue
            raise
        else:
            if not self.slug:
                base = slugify(self.name) or slugify(self.sku)
                self.slug = f"{base}-{self.sku}".lower()[:220]
            if (self.retail_price in (None, D0)) and self.wholesale_price is not None:
                self.set_retail_from_wholesale()
            return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.sku} · {self.name}"


# ---------- ProductPricing -----------------------------------------------------
class ProductPricing(models.Model):
    """
    One pricing row per (product, supplier).

    You capture either:
    - supplier_price_input as EXCL VAT (checkbox off), or
    - supplier_price_input as INCL VAT (checkbox on, we back-calc EXCL).

    We then compute wholesale/retail ladders from supplier_price_excl.
    """

    MARGIN_CHOICES = [
        (Decimal("15.00"), "15%"),
        (Decimal("17.50"), "17.50%"),
        (Decimal("20.00"), "20%"),
        (Decimal("22.50"), "22.50%"),
        (Decimal("25.00"), "25%"),
        (Decimal("27.50"), "27.50%"),
        (Decimal("30.00"), "30%"),
        (Decimal("32.50"), "32.50%"),
        (Decimal("35.00"), "35%"),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="pricing_rows")
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT, related_name="product_pricing")

    # Supplier inputs (canonical EXCL value stored here)
    supplier_price_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=D0,
        validators=[MinValueValidator(D0)],
        help_text="Supplier price excluding VAT (R).",
    )
    supplier_vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(D0), MaxValueValidator(Decimal("100.00"))],
        help_text="Supplier VAT % (usually 15%).",
    )

    # Wholesale ladder
    wholesale_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        choices=MARGIN_CHOICES,
        default=Decimal("15.00"),
    )

    wholesale_vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(D0), MaxValueValidator(Decimal("100.00"))],
        help_text="VAT % used for wholesale INCL.",
    )

    # Retail ladder
    retail_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        choices=MARGIN_CHOICES,
        default=Decimal("25.00"),
    )
    retail_vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(D0), MaxValueValidator(Decimal("100.00"))],
        help_text="VAT % used for retail INCL.",
    )

    # Choose which pricing row drives product base prices
    is_primary = models.BooleanField(
        default=False,
        help_text="If true, this row sets Product wholesale/retail base prices.",
    )

    # Per-save checkbox to avoid variant sync on this operation
    skip_variant_sync = models.BooleanField(
        default=False,
        help_text="If ticked, updating product prices from this row will NOT push prices to variants for this save.",
    )

    # New fields: how the supplier price was entered
    supplier_price_is_inclusive = models.BooleanField(
        default=False,
        help_text="Tick if the entered supplier price is VAT inclusive.",
    )
    supplier_price_input = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional: raw supplier price as entered on the invoice (EXCL or INCL depending on the checkbox).",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("product", "supplier"),)
        ordering = ["supplier__name"]
        indexes = [
            models.Index(fields=["product", "supplier"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            # At most one primary per product
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_primary=True),
                name="uniq_primary_pricing_per_product",
            ),
        ]

    def __str__(self) -> str:
        supplier_name = getattr(self.supplier, "name", getattr(self.supplier, "code", "Supplier"))
        return f"{self.product.sku} · {supplier_name}"

    # ---- supplier computed ----
    @property
    def supplier_vat_amount(self) -> Decimal:
        return r2(_d(self.supplier_price_excl) * (_d(self.supplier_vat_percent) / Decimal("100")))

    @property
    def supplier_price_incl(self) -> Decimal:
        return r2(_d(self.supplier_price_excl) + _d(self.supplier_vat_amount))


    # ---- WHOLESALE based on supplier INCL price ----
    @property
    def wholesale_price_inc(self) -> Decimal:

        """
        FINAL wholesale selling price based on real supplier cost (INCL).
        Formula:
            wholesale_price_inc = supplier_price_incl × (1 + margin%)
        """
        supplier_incl = self.supplier_price_incl
        pct = _d(self.wholesale_margin_percent) / Decimal("100")
        return r2(supplier_incl * (D1 + pct))

    @property
    def wholesale_price_excl(self) -> Decimal:
        """
        Derived EXCL price from final selling price.
        Needed internally for product sync and variant scaling.
        """
        vat_rate = _d(self.wholesale_vat_percent) / Decimal("100")
        if vat_rate <= 0:
            return self.wholesale_price_inc
        return r2(self.wholesale_price_inc / (D1 + vat_rate))

    @property
    def wholesale_margin_amount(self) -> Decimal:
        """
        Real margin based on true supplier cost.
        """
        return r2(self.wholesale_price_inc - self.supplier_price_incl)

    # ---- RETAIL based on supplier INCL price ----
    @property
    def retail_price_inc(self) -> Decimal:
        """
        FINAL retail selling price based on real supplier cost (INCL).
        Formula:
            retail_price_inc = supplier_price_incl × (1 + margin%)
        """
        supplier_incl = self.supplier_price_incl
        pct = _d(self.retail_margin_percent) / Decimal("100")
        return r2(supplier_incl * (D1 + pct))

    @property
    def retail_price_excl(self) -> Decimal:
        """
        Derived EXCL retail price for system consistency.
        """
        vat_rate = _d(self.retail_vat_percent) / Decimal("100")
        if vat_rate <= 0:
            return self.retail_price_inc
        return r2(self.retail_price_inc / (D1 + vat_rate))

    @property
    def retail_margin_amount(self) -> Decimal:
        """
        True retail margin based on INCL supplier cost.
        """
        return r2(self.retail_price_inc - self.supplier_price_incl)


    def clean(self):
        # 1) Run Django's default model validation
        super().clean()

        # 2) Enforce max 5 suppliers per product (existing rule)
        if self.product_id:
            qs = ProductPricing.objects.filter(product=self.product)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.count() >= 5:
                raise ValidationError("You can only add up to 5 suppliers per product.")

        # 3) Handle supplier input (EXCL/INCL)
        # If supplier_price_input is None, we leave supplier_price_excl as-is
        # (important for existing rows that already have data).
        if self.supplier_price_input is not None:
            vat_rate = _d(self.supplier_vat_percent) / Decimal("100")  # e.g. 0.15

            if self.supplier_price_is_inclusive:
                # User entered an INCL price → work backwards to EXCL
                excl = _d(self.supplier_price_input) / (D1 + vat_rate)
                self.supplier_price_excl = excl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                # User entered EXCL price → just copy it
                self.supplier_price_excl = r2(self.supplier_price_input)


# ---------- ProductVariant -----------------------------------------------------
class ProductVariant(models.Model):
    """
    A pre-packed option (sub-product) for a Product.
    If overrides are blank/zero, price derives from parent product price * pack_size (when scalable).
    """
    UOM_CHOICES = Product.UOM_CHOICES

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    pack_size = models.DecimalField(max_digits=8, decimal_places=2)  # e.g. 1.5, 2.5, 5, 10
    uom = models.CharField(max_length=8, choices=UOM_CHOICES, default="KG")

    name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional display name; blank -> auto from pack_size + UOM.",
    )
    sku = models.CharField(max_length=50, blank=True, null=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    image = models.ImageField(upload_to="product_images/variants/", blank=True, null=True)

    # Optional overrides (ex VAT)
    wholesale_price_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_price_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # If True, derived price = parent_price * pack_size (typical for KG/L/EA quantity packs)
    scales_with_pack = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__name", "pack_size"]
        indexes = [
            models.Index(fields=["product", "pack_size"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        label = self.name or f"{self.pack_size} {self.get_uom_display()}"
        return f"{self.product.name} · {label}"

    # --- Price helpers (ex VAT) ---
    def price_for_channel(self, channel: str = "retail") -> Decimal:
        ch = (channel or "retail").lower()
        if ch == "retail" and self.retail_price_override not in (None, D0):
            return self.retail_price_override
        if ch == "wholesale" and self.wholesale_price_override not in (None, D0):
            return self.wholesale_price_override

        base = self.product.price_for_channel(ch) or D0
        if self.scales_with_pack and self.pack_size:
            try:
                return (base * _d(self.pack_size)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except Exception:
                return base
        return base

    def clean(self):
        if self.scales_with_pack and self.uom != self.product.uom:
            # Usually your scalable variants should use the same UOM as parent
            # (relax/remove if you intentionally mix UOMs).
            raise ValidationError({"uom": "Variant UOM should match product UOM when scales_with_pack=True."})

    # --- Slug/SKU/name defaults ---
    def save(self, *args, **kwargs):
        if not self.name:
            self.name = f"{self.pack_size} {self.get_uom_display()}"
        if not self.slug:
            base = slugify(f"{self.product.slug}-{self.pack_size}-{self.uom}") or slugify(self.name)
            self.slug = base[:220]
        if not self.sku:
            pack_tag = str(self.pack_size).replace(".", "_")
            self.sku = f"{self.product.sku}-{pack_tag}{self.uom}"
        super().save(*args, **kwargs)

    @property
    def wholesale_derived(self) -> Decimal:
        # Derived from product wholesale, ignoring override
        base = self.product.price_for_channel("wholesale") or D0
        if self.scales_with_pack and self.pack_size:
            return r2(base * _d(self.pack_size))
        return base

    @property
    def retail_derived(self) -> Decimal:
        base = self.product.price_for_channel("retail") or D0
        if self.scales_with_pack and self.pack_size:
            return r2(base * _d(self.pack_size))
        return base



# ---------- Signals & helpers: keep product/variants in sync -------------------
def _apply_primary_pricing_to_product(pp: ProductPricing) -> None:
    """
    Copy prices from the given pricing row onto the Product, then
    (optionally) sync variants. If pp.skip_variant_sync is True, variants will
    NOT be synced for this save.
    """
    p = pp.product

    # TRUE COST = supplier INCLUSIVE price
    p.cost_price      = pp.supplier_price_incl        # 👈 IMPORTANT LINE
    p.wholesale_price = pp.wholesale_price_excl       # ex VAT selling
    p.retail_price    = pp.retail_price_excl          # ex VAT selling

    if pp.skip_variant_sync:
        # Guard the product save so post_save doesn't propagate to variants.
        token = SKIP_VARIANT_SYNC.set(True)
        try:
            p.save(update_fields=["cost_price", "wholesale_price", "retail_price", "updated_at"])
        finally:
            SKIP_VARIANT_SYNC.reset(token)
    else:
        # Normal behaviour: saving product will trigger its post_save to sync variants
        p.save(update_fields=["cost_price", "wholesale_price", "retail_price", "updated_at"])



@receiver(post_save, sender=Product, dispatch_uid="product_sync_variants_on_save")
def product_post_save_sync_variants(sender, instance: Product, created, **kwargs):
    # Skip if a calling context explicitly requested no variant sync.
    if SKIP_VARIANT_SYNC.get():
        return
    # Push new base prices down to scalable variants
    instance.sync_variant_prices(force=True)


@receiver(pre_save, sender=ProductPricing, dispatch_uid="pricing_enforce_single_primary")
def pricing_pre_save_enforce_single_primary(sender, instance: ProductPricing, **kwargs):
    """
    If a row is set to primary=True, clear primary on other rows for that product.
    UniqueConstraint also enforces this at DB level, but we tidy proactively.
    """
    if instance.pk is None and instance.is_primary:
        ProductPricing.objects.filter(product=instance.product, is_primary=True).update(is_primary=False)
    elif instance.pk is not None:
        old = ProductPricing.objects.filter(pk=instance.pk).only("is_primary").first()
        if old and not old.is_primary and instance.is_primary:
            ProductPricing.objects.filter(product=instance.product, is_primary=True).exclude(pk=instance.pk).update(
                is_primary=False
            )


@receiver(post_save, sender=ProductPricing, dispatch_uid="pricing_update_product_on_save")
def pricing_post_save_update_product_and_variants(sender, instance: ProductPricing, created, **kwargs):
    """
    If this pricing row is_primary & active, make it authoritative:
    update Product base prices from it (EXCL) and (maybe) variants.

    Fallback: If no primary exists for the product, choose the cheapest active
    supplier row and apply it to the Product.
    """
    if not instance.is_active:
        # If primary got deactivated, consider picking a new one
        has_primary = ProductPricing.objects.filter(
            product=instance.product, is_active=True, is_primary=True
        ).exists()
        if not has_primary:
            cheapest = (
                ProductPricing.objects
                .filter(product=instance.product, is_active=True)
                .order_by("supplier_price_excl")
                .first()
            )
            if cheapest:
                _apply_primary_pricing_to_product(cheapest)
        return

    if instance.is_primary:
        _apply_primary_pricing_to_product(instance)
        return

    # Not primary: if there is no active primary at all, auto-pick cheapest.
    has_primary = ProductPricing.objects.filter(
        product=instance.product, is_active=True, is_primary=True
    ).exists()
    if not has_primary:
        cheapest = (
            ProductPricing.objects
            .filter(product=instance.product, is_active=True)
            .order_by("supplier_price_excl")
            .first()
        )
        if cheapest:
            _apply_primary_pricing_to_product(cheapest)
