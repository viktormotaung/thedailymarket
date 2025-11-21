from django.conf import settings
from django.db import models
from image_cropping import ImageRatioField


class Supplier(models.Model):
    # Identity
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Short internal code, e.g. HENLEY, BRM"
    )
    categories = models.ManyToManyField(
        "products.Category",   # <- string avoids import-time dependency
        related_name="suppliers",
        blank=True,
        help_text="Select one or more product categories this supplier provides."
    )

    is_active = models.BooleanField(default=True)

    # Account owner (internal)
    account_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplier_accounts",
        help_text="Internal staff member managing this account"
    )

    # Contact
    contact_person = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)
    website = models.URLField(blank=True)

    # Address
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120, blank=True)
    province = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=120, default="South Africa")

    # Notes
    notes = models.TextField(blank=True)

    PAYMENT_TERMS = [
        ("COD", "Cash on Delivery"),
        ("3D", "3 days"),
        ("7D", "7 days"),
        ("14D", "14 days"),
        ("30D", "30 days"),
    ]
    payment_terms = models.CharField(
        max_length=10,
        choices=PAYMENT_TERMS,
        default="COD",
        blank=True,
    )

    # Compliance / IDs
    vat_number = models.CharField(max_length=80, blank=True)
    company_reg_number = models.CharField(max_length=80, blank=True)

    # Files
    contract_file = models.FileField(
        upload_to="supplier_docs/contracts/",
        blank=True,
        null=True
    )

    # --- NEW: Branding / Logo with crop box ---
    logo = models.ImageField(
        upload_to="supplier_docs/logos/",
        blank=True,
        null=True,
        help_text="Upload a raster logo (PNG/JPG). Transparent PNG recommended."
    )
    # Cropping widget target (matches your THUMBNAIL_ALIASES 'logo' 400x200)
    logo_cropping = ImageRatioField("logo", "400x200", free_crop=True)

    # NEW: public visibility toggle (default No)
    visible = models.BooleanField(
        default=False,
        db_index=True,
        help_text="If Yes, this supplier can be shown publicly (e.g., in the Brands slider)."
    )

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["name"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["visible"]),
        ]

    def __str__(self):
        return f"{self.code} · {self.name}"

