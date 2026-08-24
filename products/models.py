# models.py
from __future__ import annotations
import os
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
from suppliers.models import Supplier
from decimal import ROUND_CEILING
# ---------- Context flags ------------------------------------------------------
# Used to prevent variant sync in product_post_save when set True in this thread/context.
SKIP_VARIANT_SYNC: ContextVar[bool] = ContextVar("SKIP_VARIANT_SYNC", default=False)

# ---------- Constants & helpers ------------------------------------------------
SKU_NUM_WIDTH = 3  # -> 001, 002, ...

D0 = Decimal("0.00")
D1 = Decimal("1.00")



def round_up_rand(x: Decimal | None) -> Decimal:
    """
    Round UP to the next whole rand.
    57.01 -> 58.00
    57.99 -> 58.00
    57.00 -> 57.00
    """
    if x is None:
        return D0

    return (
        x.quantize(Decimal("1"), rounding=ROUND_CEILING)
         .quantize(Decimal("0.00"))
    )


def r2(x: Decimal | None) -> Decimal:
    """Round to 2dp; None -> 0.00 to keep admin displays simple."""
    if x is None:
        return D0
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _d(x) -> Decimal:
    """Coerce None -> 0 and anything else to Decimal safely."""
    return x if isinstance(x, Decimal) else (Decimal(str(x)) if x is not None else D0)

from decimal import Decimal, ROUND_HALF_UP

D0 = Decimal("0.00")

def _r2(x: Decimal | None) -> Decimal:
    if x is None:
        return D0
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _d(x):
    """Shortcut to convert to Decimal"""
    return Decimal(x)


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
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)

    category_no = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Business category number, e.g. 009."
    )

    # 👇 NEW
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        help_text="Parent category (leave blank for top-level categories)."
    )

    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    abbreviation = models.CharField(
        max_length=3,
        blank=True,
        db_index=True,
        help_text="3-letter code auto-generated from name (you can override).",
    )

    class Meta:
        ordering = ["parent__name", "sort_order", "name"]

        unique_together = ("parent", "name")

        constraints = [
            models.UniqueConstraint(
                fields=["parent", "category_no"],
                name="unique_category_number_per_parent",
            ),
        ]

        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["abbreviation"]),
            models.Index(fields=["parent"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = f"{self.parent.name}-{self.name}" if self.parent else self.name
            self.slug = slugify(base)[:140]

        if not self.abbreviation:
            candidates = make_abbreviation_3(self.name)
            for cand in candidates:
                if not Category.objects.exclude(pk=self.pk).filter(abbreviation=cand).exists():
                    self.abbreviation = cand
                    break
            if not self.abbreviation:
                self.abbreviation = candidates[0]

        super().save(*args, **kwargs)

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} → {self.name}"
        return self.name

    


# ---------- Product ------------------------------------------------------------
# ---------------------------
# Image upload path
# ---------------------------
def product_image_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"products/{instance.id}/{slugify(instance.name)}{ext}"


class Product(models.Model):
    UOM_CHOICES = [
        ("EA", "Each"),
        ("KG", "Kilogram"),
        ("L", "Litre"),
        ("PK", "Pack"),
        ("BOX", "Box"),
    ]

    product_no = models.CharField(
        max_length=11,
        unique=True,
        db_index=True,
        help_text="Unique Product ID: Category-Subcategory-Product"
    )

    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        help_text="Select the most specific category (e.g. Beef, Chicken)."
    )

    sku = models.CharField(max_length=64, blank=True, null=True)
    slug = models.SlugField(max_length=220, blank=True, null=True)

    image = models.ImageField(
        upload_to=product_image_path,
        blank=True,
        null=True
    )

    uom = models.CharField(max_length=8, choices=UOM_CHOICES, default="EA")

    # NEW: description for product detail page / catalog
    description = models.TextField(blank=True)

    VISIBILITY_CHOICES = [
        ("YES", "Yes"),
        ("NO", "No"),
    ]

    visible = models.CharField(
        max_length=3,
        choices=VISIBILITY_CHOICES,
        default="YES",
        db_index=True,
        help_text="Controls whether this product is visible in the shop and catalog."
    )

    # Base (ex VAT)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_margin_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("15.00"))

    special_label = models.CharField(
        max_length=50,
        blank=True,
        default=""
    )

    # -----------------------------
    # Specials
    # -----------------------------
    is_special = models.BooleanField(
        default=False,
        help_text="Tick if this product is currently on special."
    )

    old_wholesale_price_inc = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Previous wholesale selling price INCLUDING VAT."
    )

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
    def set_retail_from_wholesale(
        self,
        margin_pct: Optional[Decimal] = None,
        rounding: str = "0.01"
    ) -> None:
        pct = Decimal(margin_pct) if margin_pct is not None else _d(self.retail_margin_pct)
        base = _d(self.wholesale_price)
        self.retail_price = (base * (D1 + (pct / Decimal("100")))).quantize(
            Decimal(rounding),
            rounding=ROUND_HALF_UP,
        )

    def price_for_channel(self, channel: str = "wholesale") -> Decimal:
        if (channel or "").lower() == "retail":
            return r2(self.retail_price)
        return r2(self.wholesale_price)
    
    @property
    def wholesale_price_inc(self) -> Decimal:
        """
        Current wholesale price INCLUDING VAT.
        """
        if self.wholesale_price is None:
            return D0

        return round_up_rand(
            self.wholesale_price * Decimal("1.15")
        )


    @property
    def special_saving(self) -> Decimal:
        """
        Rand saving for specials.
        """
        if (
            not self.is_special
            or self.old_wholesale_price_inc is None
        ):
            return D0

        saving = self.old_wholesale_price_inc - self.wholesale_price_inc

        return saving if saving > D0 else D0


    @property
    def special_percentage(self) -> Decimal:
        """
        Percentage saving.
        """
        if (
            not self.is_special
            or self.old_wholesale_price_inc is None
            or self.old_wholesale_price_inc <= D0
        ):
            return D0

        return (
            (self.special_saving / self.old_wholesale_price_inc) * Decimal("100")
        ).quantize(
            Decimal("0.1"),
            rounding=ROUND_HALF_UP,
        )

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
                    v.save(update_fields=[
                        "wholesale_price_override",
                        "retail_price_override",
                        "updated_at",
                    ])
                    updated += 1
        return updated

    def clean(self):
        for fld in ("cost_price", "wholesale_price", "retail_price"):
            val = getattr(self, fld, None)
            if val is not None and val < D0:
                raise ValidationError({fld: "Value must be zero or positive."})

    def save(self, *args, **kwargs):
        """
        SAFE save():
        - First save without SKU logic
        - Then generate SKU ONLY if needed
        """

        is_create = self.pk is None

        # 1️⃣ FIRST SAVE (NO SKU LOGIC)
        if is_create:
            super().save(*args, **kwargs)

        # 2️⃣ SKU GENERATION (ONLY IF STILL MISSING)
        if not self.sku and self.category_id:
            for _ in range(5):
                try:
                    self.sku = _next_sku_for_category(self.category)

                    if not self.slug:
                        base = slugify(self.name) or slugify(self.sku)
                        self.slug = f"{base}-{self.sku}".lower()[:220]

                    if (self.retail_price in (None, D0)) and self.wholesale_price is not None:
                        self.set_retail_from_wholesale()

                    with transaction.atomic():
                        super().save(update_fields=[
                            "sku",
                            "slug",
                            "retail_price",
                            "updated_at",
                        ])
                    break

                except IntegrityError:
                    self.sku = None
                    continue

        # 3️⃣ NORMAL UPDATE PATH
        if not is_create:
            if not self.slug:
                base = slugify(self.name) or slugify(self.sku)
                self.slug = f"{base}-{self.sku}".lower()[:220]

            if (self.retail_price in (None, D0)) and self.wholesale_price is not None:
                self.set_retail_from_wholesale()

            super().save(*args, **kwargs)

    def __str__(self) -> str:
        # Try get primary pricing
        pr = self.pricing_rows.filter(is_primary=True, is_active=True).first()

        if pr:
            price_inc = pr.retail_price_inc  # or wholesale_price_inc depending on your use case
            return f"{self.sku} · {self.name} (R {price_inc:.2f})"

        return f"{self.sku} · {self.name}"


# =============================================================================
# PRODUCT KNOWLEDGE
# =============================================================================

class ProductKnowledge(models.Model):
    """
    Sales knowledge profile for a Product.

    This model is separate from the Product master data.

    Product master information such as:
        - Product No.
        - Product Name
        - Category
        - Subcategory
        - Image
        - UOM
        - Price Per

    remains on the Product / Category structure.

    This model stores the knowledge required by the sales team
    to understand, position and sell the product.
    """

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="knowledge",
        help_text="Product this knowledge profile belongs to.",
    )

    # =========================================================================
    # SINGLE-ANSWER KNOWLEDGE
    # =========================================================================

    # 1. Product Description / Definition
    product_description = models.TextField(
        blank=True,
        help_text=(
            "What is this product? Provide a clear definition "
            "for the sales representative."
        ),
    )

    # 3. Where / What It Is Used For
    usage_application = models.TextField(
        blank=True,
        help_text=(
            "What meals, menu items or applications is this product "
            "used for? Enter N/A if not applicable."
        ),
    )

    # 5. Yield / Portion Information
    yield_portion_information = models.TextField(
        blank=True,
        help_text=(
            "Provide useful yield, portion or serving information. "
            "Enter N/A if not applicable."
        ),
    )

    # 6. Variants - Not Applicable
    variants_not_applicable = models.BooleanField(
        default=False,
        help_text=(
            "Tick this if the product has no relevant knowledge variants. "
            "This counts the Variants section as complete."
        ),
    )

    # 9. Why Choose The Daily Market
    why_choose_tdm = models.TextField(
        blank=True,
        help_text=(
            "Why should the customer choose this product from "
            "The Daily Market?"
        ),
    )

    # 12. Key Takeaways
    key_takeaways = models.TextField(
        blank=True,
        help_text=(
            "The most important things the sales representative "
            "must remember about this product."
        ),
    )

    # =========================================================================
    # CONTROL / APPROVAL
    # =========================================================================

    is_approved = models.BooleanField(
        default=False,
        help_text=(
            "Indicates whether the Product Knowledge profile "
            "has been reviewed and approved."
        ),
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["product__name"]

    def __str__(self):
        return f"Product Knowledge · {self.product.name}"

    # =========================================================================
    # COMPLETION HELPERS
    # =========================================================================

    @staticmethod
    def _answered(value):
        """
        Determines whether a single-answer question is answered.

        Any non-empty value counts as complete.
        This includes 'N/A'.
        """
        return bool(value and value.strip())

    def completion_sections(self):
        """
        Return the completion state of every Product Knowledge question.

        IMPORTANT:
        Each question counts only ONCE.

        For repeatable sections:
            - 1 record = complete
            - 10 records = complete
            - 0 records = incomplete

        N/A is considered a valid completed answer.
        """

        return {
            # 1
            "product_description": self._answered(
                self.product_description
            ),

            # 2
            "customer_business_types": self.customer_business_types.exists(),

            # 3
            "usage_application": self._answered(
                self.usage_application
            ),

            # 4
            "product_benefits": self.product_benefits.exists(),

            # 5
            "yield_portion_information": self._answered(
                self.yield_portion_information
            ),

            # 6
            "variants": self.variants_answered(),

            # 7
            "customer_alternatives": self.customer_alternatives.exists(),

            # 8
            "competitor_comparison": self.product_competitors.exists(),

            # 9
            "why_choose_tdm": self._answered(
                self.why_choose_tdm
            ),

            # 10
            "customer_questions": self.customer_questions.exists(),

            # 11
            "common_objections": self.product_objections.exists(),

            # 12
            "key_takeaways": self._answered(
                self.key_takeaways
            ),
        }

    # =========================================================================
    # VARIANTS COMPLETION
    # =========================================================================

    def variants_answered(self):
        """
        Product Knowledge variants are completely independent
        from the existing ProductVariant model.

        This section is complete when:
            1. At least one ProductKnowledgeVariant exists, OR
            2. The user explicitly marks the section as N/A.

        This model does NOT use or inspect the existing ProductVariant
        records.
        """

        if self.variants_not_applicable:
            return True

        return self.knowledge_variants.exists()

    # =========================================================================
    # COMPLETION PERCENTAGE
    # =========================================================================

    @property
    def completion_percentage(self):
        """
        Calculate Product Knowledge completion percentage.

        Each knowledge question has equal weight.

        Example:

            12 questions
            9 completed

            9 / 12 = 75%

        Multiple records inside a section do NOT increase
        the percentage.
        """

        sections = self.completion_sections()

        total_sections = len(sections)

        if total_sections == 0:
            return 0

        completed_sections = sum(
            1
            for completed in sections.values()
            if completed
        )

        return round(
            (completed_sections / total_sections) * 100
        )

    @property
    def knowledge_status(self):
        """
        Human-readable completion status.
        """

        percentage = self.completion_percentage

        if percentage == 100:
            return "COMPLETE"

        if percentage >= 80:
            return "ALMOST COMPLETE"

        if percentage >= 50:
            return "IN PROGRESS"

        if percentage > 0:
            return "INCOMPLETE"

        return "NOT STARTED"

    @property
    def is_complete(self):
        return self.completion_percentage == 100
    
# =============================================================================
# CUSTOMER / BUSINESS TYPES
# =============================================================================

class ProductKnowledgeBusinessType(models.Model):
    """
    Business/customer types that use this product.

    Multiple business types can be recorded for one product.
    """

    product_knowledge = models.ForeignKey(
        ProductKnowledge,
        on_delete=models.CASCADE,
        related_name="customer_business_types",
    )

    business_type = models.CharField(
        max_length=150,
        help_text="Type of food business that uses this product.",
    )

    notes = models.TextField(
        blank=True,
        help_text=(
            "Optional explanation of why this business type "
            "uses the product."
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["sort_order", "business_type"]

    def __str__(self):
        return self.business_type


# =============================================================================
# PRODUCT BENEFITS
# =============================================================================

class ProductKnowledgeBenefit(models.Model):
    """
    Individual product benefit.

    Multiple benefits can be recorded for one product.
    """

    product_knowledge = models.ForeignKey(
        ProductKnowledge,
        on_delete=models.CASCADE,
        related_name="product_benefits",
    )

    benefit = models.CharField(
        max_length=200,
        help_text="Short name of the product benefit.",
    )

    explanation = models.TextField(
        blank=True,
        help_text=(
            "Explain why this benefit matters to the customer."
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["sort_order", "benefit"]

    def __str__(self):
        return self.benefit


# =============================================================================
# PRODUCT KNOWLEDGE VARIANTS
# =============================================================================

class ProductKnowledgeVariant(models.Model):
    """
    Sales knowledge variant.

    IMPORTANT:
    This model is completely independent of ProductVariant.

    ProductVariant handles operational/product information such as
    pack size, SKU and pricing.

    ProductKnowledgeVariant handles sales knowledge such as:
        - What the variant is
        - Who it is suited for
        - What benefit it provides
        - When the sales representative should recommend it
    """

    product_knowledge = models.ForeignKey(
        ProductKnowledge,
        on_delete=models.CASCADE,
        related_name="knowledge_variants",
    )

    variant_name = models.CharField(
        max_length=150,
        help_text="Name of the product knowledge variant.",
    )

    description = models.TextField(
        help_text=(
            "Explain what this variant is and what makes it different."
        ),
    )

    best_suited_for = models.TextField(
        help_text=(
            "Which customers, businesses, meals or applications "
            "are best suited to this variant?"
        ),
    )

    customer_benefit = models.TextField(
        help_text=(
            "What benefit does this particular variant provide "
            "to the customer?"
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["sort_order", "variant_name"]

    def __str__(self):
        return self.variant_name


# =============================================================================
# CUSTOMER ALTERNATIVES
# =============================================================================

class ProductKnowledgeAlternative(models.Model):
    """
    Alternative products or brands customers may currently use.

    Multiple alternatives can be recorded for one product.
    """

    product_knowledge = models.ForeignKey(
        ProductKnowledge,
        on_delete=models.CASCADE,
        related_name="customer_alternatives",
    )

    brand = models.CharField(
        max_length=150,
        help_text="Alternative brand.",
    )

    product_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Specific alternative product, if known.",
    )

    notes = models.TextField(
        blank=True,
        help_text=(
            "Why customers may use this alternative."
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["sort_order", "brand", "product_name"]

    def __str__(self):
        if self.product_name:
            return f"{self.brand} · {self.product_name}"

        return self.brand


# =============================================================================
# COMPETITOR COMPARISON
# =============================================================================

class ProductKnowledgeCompetitor(models.Model):
    """
    Structured competitor comparison.

    Multiple competitors can be recorded for one product.
    """

    product_knowledge = models.ForeignKey(
        ProductKnowledge,
        on_delete=models.CASCADE,
        related_name="product_competitors",
    )

    competitor_brand = models.CharField(
        max_length=150,
        help_text="Competitor brand.",
    )

    competitor_product = models.CharField(
        max_length=200,
        blank=True,
        help_text="Specific competitor product, if known.",
    )

    why_customer_uses_it = models.TextField(
        help_text=(
            "Why customers currently choose this competitor."
        ),
    )

    tdm_positioning = models.TextField(
        help_text=(
            "How the sales representative should position "
            "The Daily Market against this competitor."
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = [
            "sort_order",
            "competitor_brand",
            "competitor_product",
        ]

    def __str__(self):
        if self.competitor_product:
            return (
                f"{self.competitor_brand} · "
                f"{self.competitor_product}"
            )

        return self.competitor_brand


# =============================================================================
# CUSTOMER QUESTIONS
# =============================================================================

class ProductKnowledgeQuestion(models.Model):
    """
    Questions the sales representative should ask the customer.

    Multiple questions can be recorded for one product.
    """

    product_knowledge = models.ForeignKey(
        ProductKnowledge,
        on_delete=models.CASCADE,
        related_name="customer_questions",
    )

    question = models.TextField(
        help_text=(
            "Question the sales representative should ask."
        ),
    )

    purpose = models.TextField(
        blank=True,
        help_text=(
            "Why should the representative ask this question?"
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.question


# =============================================================================
# COMMON OBJECTIONS & RESPONSES
# =============================================================================

class ProductKnowledgeObjection(models.Model):
    """
    Common customer objections and recommended responses.

    Multiple objections can be recorded for one product.
    """

    product_knowledge = models.ForeignKey(
        ProductKnowledge,
        on_delete=models.CASCADE,
        related_name="product_objections",
    )

    objection = models.TextField(
        help_text=(
            "Common objection the customer may raise."
        ),
    )

    response = models.TextField(
        help_text=(
            "Recommended response for the sales representative."
        ),
    )

    notes = models.TextField(
        blank=True,
        help_text=(
            "Additional guidance for the representative."
        ),
    )

    sort_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.objection[:100]


    
# ---------- ProductPricing -----------------------------------------------------
class ProductPricing(models.Model):
    """
    One pricing row per (product, supplier).

    Supplier price is captured once and stored canonically as EXCL VAT.
    Wholesale & Retail prices are derived from TRUE supplier cost (INCL).
    """

    # -----------------------------
    # Margins
    # -----------------------------
    MARGIN_CHOICES = [
        (Decimal("0.00"), "0%"),
        (Decimal("5.00"), "5%"),
        (Decimal("7.50"), "7.50%"),
        (Decimal("10.00"), "10%"),
        (Decimal("12.50"), "12.50%"),
        (Decimal("15.00"), "15%"),
        (Decimal("17.50"), "17.50%"),
        (Decimal("20.00"), "20%"),
        (Decimal("22.50"), "22.50%"),
        (Decimal("25.00"), "25%"),
        (Decimal("27.50"), "27.50%"),
        (Decimal("30.00"), "30%"),
        (Decimal("32.50"), "32.50%"),
        (Decimal("35.00"), "35%"),
        (Decimal("37.50"), "37.50%"),
        (Decimal("40.00"), "40%"),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="pricing_rows",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="product_pricing",
    )

    # -----------------------------
    # Supplier pricing (canonical)
    # -----------------------------
    supplier_price_excl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=D0,
        validators=[MinValueValidator(D0)],
        help_text="Supplier price EXCL VAT (R).",
    )
    supplier_vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(D0), MaxValueValidator(Decimal("100.00"))],
    )

    supplier_price_input = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Raw price as entered (EXCL or INCL).",
    )
    supplier_price_is_inclusive = models.BooleanField(
        default=False,
        help_text="Tick if supplier_price_input is VAT inclusive.",
    )

    # -----------------------------
    # Wholesale ladder
    # -----------------------------
    wholesale_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        choices=MARGIN_CHOICES,
        default=Decimal("15.00"),
    )
    wholesale_vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(D0), MaxValueValidator(Decimal("100.00"))],
    )

    # -----------------------------
    # Retail ladder
    # -----------------------------
    retail_margin_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        choices=MARGIN_CHOICES,
        default=Decimal("25.00"),
    )
    retail_vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(D0), MaxValueValidator(Decimal("100.00"))],
    )

    # -----------------------------
    # Behaviour flags
    # -----------------------------
    is_primary = models.BooleanField(
        default=False,
        help_text="If true, sync prices to Product.",
    )
    skip_variant_sync = models.BooleanField(
        default=False,
        help_text="Skip pushing prices to variants on this save.",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # -----------------------------
    # Meta
    # -----------------------------
    class Meta:
        unique_together = (("product", "supplier"),)
        ordering = ["supplier__name"]
        indexes = [
            models.Index(fields=["product", "supplier"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_primary=True),
                name="uniq_primary_pricing_per_product",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product.sku} · {self.supplier.name}"

    # =====================================================
    # Computed supplier values
    # =====================================================
    @property
    def supplier_vat_amount(self) -> Decimal:
        return r2(self.supplier_price_excl * (self.supplier_vat_percent / Decimal("100")))

    @property
    def supplier_price_incl(self) -> Decimal:
        return r2(self.supplier_price_excl + self.supplier_vat_amount)

    # =====================================================
    # WHOLESALE
    # =====================================================
    @property
    def wholesale_price_inc(self) -> Decimal:
        return round_up_rand(
            self.supplier_price_incl
            * (D1 + (self.wholesale_margin_percent / Decimal("100")))
        )

    
    @property
    def wholesale_price_excl(self) -> Decimal:
        vat = self.wholesale_vat_percent / Decimal("100")

        return (
            self.wholesale_price_inc
            if vat <= 0
            else r2(
                self.wholesale_price_inc / (D1 + vat)
            )
        )

    @property
    def wholesale_margin_amount(self) -> Decimal:
        return r2(self.wholesale_price_inc - self.supplier_price_incl)

    # =====================================================
    # RETAIL
    # =====================================================
    @property
    def retail_price_inc(self) -> Decimal:
        return round_up_rand(
            self.supplier_price_incl
            * (D1 + (self.retail_margin_percent / Decimal("100")))
        )

    
    @property
    def retail_price_excl(self) -> Decimal:
        vat = self.retail_vat_percent / Decimal("100")

        return (
            self.retail_price_inc
            if vat <= 0
            else r2(
                self.retail_price_inc / (D1 + vat)
            )
        )

    @property
    def retail_margin_amount(self) -> Decimal:
        return r2(self.retail_price_inc - self.supplier_price_incl)

    # =====================================================
    # Validation
    # =====================================================
    def clean(self):
        super().clean()

        # Max 5 suppliers per product
        qs = ProductPricing.objects.filter(product=self.product)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if qs.count() >= 5:
            raise ValidationError("You can only add up to 5 suppliers per product.")

        # Handle supplier input conversion
        if self.supplier_price_input is not None:
            vat_rate = self.supplier_vat_percent / Decimal("100")

            if self.supplier_price_is_inclusive:
                self.supplier_price_excl = r2(
                    self.supplier_price_input / (D1 + vat_rate)
                )
            else:
                self.supplier_price_excl = r2(self.supplier_price_input)

    # =====================================================
    # Save
    # =====================================================
    def save(self, *args, **kwargs):
        # ALWAYS compute pricing
        self.full_clean()
        super().save(*args, **kwargs)

        # Sync to Product if primary
        if self.is_primary:
            Product.objects.filter(pk=self.product_id).update(
                wholesale_price=self.wholesale_price_excl,
                retail_price=self.retail_price_excl,
                retail_margin_pct=self.retail_margin_percent,
            )

            if not self.skip_variant_sync:
                self.product.sync_variant_prices(force=True)



class ProductPriceHistory(models.Model):
    """
    Records actual pricing events for a product/supplier combination.

    A history record is created only when:
    - the product is newly introduced, or
    - one or more prices actually change.

    Re-importing the same price does not create a new record.
    """

    CHANGE_TYPE_CHOICES = [
        ("INITIAL", "Initial Price"),
        ("INCREASE", "Price Increase"),
        ("DECREASE", "Price Decrease"),
        ("MIXED", "Mixed Price Change"),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="price_history",
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="product_price_history",
    )

    change_type = models.CharField(
        max_length=10,
        choices=CHANGE_TYPE_CHOICES,
    )

    # Supplier cost
    previous_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    new_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    cost_change = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Wholesale selling price
    previous_wholesale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    new_wholesale_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    wholesale_change = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Retail selling price
    previous_retail_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    new_retail_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    retail_change = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    changed_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["product", "-changed_at"]),
            models.Index(fields=["supplier", "-changed_at"]),
            models.Index(fields=["change_type"]),
        ]

    def __str__(self):
        return (
            f"{self.product.product_no} · "
            f"{self.product.name} · "
            f"{self.get_change_type_display()} · "
            f"{self.changed_at:%Y-%m-%d}"
        )


    
# ---------- ProductVariant -----------------------------------------------------
class ProductVariant(models.Model):
    """
    A pre-packed option (sub-product) for a Product.
    If overrides are blank/zero, price derives from parent product price * pack_size (when scalable).
    Prices are stored inclusive of VAT.
    """
    UOM_CHOICES = Product.UOM_CHOICES  # assuming Product model exists

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    pack_size = models.DecimalField(max_digits=8, decimal_places=2)  # e.g. 1.5, 2.5, 5, 10
    uom = models.CharField(max_length=8, choices=UOM_CHOICES, default="KG")

    name = models.CharField(max_length=200, blank=True)
    sku = models.CharField(max_length=50, blank=True, null=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    image = models.ImageField(upload_to="product_images/variants/", blank=True, null=True)

    # Optional overrides (ex VAT)
    wholesale_price_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_price_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Stored final prices inclusive of VAT
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

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
        return self.name or f"{self.product.name} · {self.pack_size} {self.get_uom_display()}"

    # --- Helpers ---
    def price_for_channel_inc(self, channel: str = "retail") -> Decimal:
        """Return stored inclusive-VAT price for the given channel."""
        ch = (channel or "retail").lower()
        if ch == "retail":
            return self.retail_price or D0
        if ch == "wholesale":
            return self.wholesale_price or D0
        return D0

    def clean(self):
        if self.scales_with_pack and self.uom != self.product.uom:
            raise ValidationError({"uom": "Variant UOM should match product UOM when scales_with_pack=True."})

    # --- Save ---
    def save(self, *args, **kwargs):
        VAT_RATE = Decimal("0.15")  # 15% VAT

        # Defaults
        if not self.name:
            self.name = f"{self.pack_size} {self.get_uom_display()}"
        if not self.slug:
            self.slug = slugify(f"{self.product.slug}-{self.pack_size}-{self.uom}")[:220]
        if not self.sku:
            self.sku = f"{self.product.sku}-{str(self.pack_size).replace('.', '_')}{self.uom}"

        # --- Wholesale price inclusive VAT ---
        base_wholesale = self.wholesale_price_override or self.product.price_for_channel("wholesale") or D0
        if self.scales_with_pack and self.pack_size:
            base_wholesale *= _d(self.pack_size)
        self.wholesale_price = round_up_rand(
            base_wholesale * (1 + VAT_RATE)
        )

        # --- Retail price inclusive VAT ---
        base_retail = self.retail_price_override or self.product.price_for_channel("retail") or D0
        if self.scales_with_pack and self.pack_size:
            base_retail *= _d(self.pack_size)
        self.retail_price = round_up_rand(
            base_retail * (1 + VAT_RATE)
        )

        super().save(*args, **kwargs)

    # --- Derived properties (inclusive only) ---
    @property
    def wholesale_derived(self) -> Decimal:
        """Calculate derived wholesale price inclusive VAT."""
        base = self.product.price_for_channel("wholesale") or D0
        if self.scales_with_pack and self.pack_size:
            base *= _d(self.pack_size)
        return round_up_rand(base * Decimal("1.15"))

    @property
    def retail_derived(self) -> Decimal:
        """Calculate derived retail price inclusive VAT."""
        base = self.product.price_for_channel("retail") or D0
        if self.scales_with_pack and self.pack_size:
            base *= _d(self.pack_size)
        return round_up_rand(base * Decimal("1.15"))
    
# ---------- Signals & helpers: keep product/variants in sync -------------------
def _apply_primary_pricing_to_product(pp: ProductPricing) -> None:
    """
    Copy prices from the given pricing row onto the Product, then
    (optionally) sync variants. If pp.skip_variant_sync is True, variants will
    NOT be synced for this save.
    """
    p = pp.product

    # TRUE COST = supplier INCLUSIVE price
    p.cost_price = pp.supplier_price_incl        # 👈 IMPORTANT LINE
    p.wholesale_price = pp.wholesale_price_excl  # ex VAT selling
    p.retail_price = pp.retail_price_excl        # ex VAT selling

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

    # -------------------------------------------------------------------------
    # PRODUCT KNOWLEDGE
    # -------------------------------------------------------------------------
    # Every new Product automatically gets a ProductKnowledge record.
    #
    # get_or_create() makes this safe:
    # - New Product     -> creates ProductKnowledge
    # - Existing Product -> does nothing
    # - Existing Knowledge -> does not create a duplicate
    # -------------------------------------------------------------------------
    if created:
        ProductKnowledge.objects.get_or_create(
            product=instance
        )

    # -------------------------------------------------------------------------
    # EXISTING VARIANT SYNC
    # -------------------------------------------------------------------------
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
            product=instance.product,
            is_active=True,
            is_primary=True,
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
        product=instance.product,
        is_active=True,
        is_primary=True,
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
