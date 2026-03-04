# clients/models.py
from decimal import Decimal
from datetime import timedelta
from django.apps import apps
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models import IntegerField
from django.db.models.functions import Cast, Substr
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone  # 👈 needed for ProspectUpdate.action_at

from products.models import Category


# clients/choices.py
GAUTENG_CITY_CHOICES = [
    ("Johannesburg", "Johannesburg"),
    ("Pretoria", "Pretoria"),
    ("Centurion", "Centurion"),
    ("Midrand", "Midrand"),
    ("Sandton", "Sandton"),
    ("Randburg", "Randburg"),
    ("Roodepoort", "Roodepoort"),
    ("Soweto", "Soweto"),

    # Ekurhuleni (East Rand)
    ("Alberton", "Alberton"),
    ("Benoni", "Benoni"),
    ("Boksburg", "Boksburg"),
    ("Brakpan", "Brakpan"),
    ("Edenvale", "Edenvale"),
    ("Germiston", "Germiston"),
    ("Kempton Park", "Kempton Park"),
    ("Nigel", "Nigel"),
    ("Springs", "Springs"),

    # West Rand
    ("Krugersdorp", "Krugersdorp"),
    ("Randfontein", "Randfontein"),
    ("Westonaria", "Westonaria"),
    ("Carletonville", "Carletonville"),

    # Tshwane (wider Pretoria area)
    ("Akasia", "Akasia"),
    ("Atteridgeville", "Atteridgeville"),
    ("Mamelodi", "Mamelodi"),
    ("Soshanguve", "Soshanguve"),
    ("Ga-Rankuwa", "Ga-Rankuwa"),

    # Other well-known nodes
    ("Bedfordview", "Bedfordview"),
    ("Fourways", "Fourways"),
    ("Bryanston", "Bryanston"),
    ("Rosebank", "Rosebank"),
    ("Melville", "Melville"),
    ("Florida", "Florida"),
    ("Lenasia", "Lenasia"),
    ("Tembisa", "Tembisa"),
    ("Daveyton", "Daveyton"),
    ("Katlehong", "Katlehong"),
    ("Vosloorus", "Vosloorus"),
    ("Thokoza", "Thokoza"),
    ("Tsakane", "Tsakane"),
    ("Kwa-Thema", "Kwa-Thema"),

    # Fallback
    ("Other (Gauteng)", "Other (Gauteng)"),
]


class Client(models.Model):
    # ---- Ownership ----
    account_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_clients",
        help_text="Internal staff member managing this client.",
    )

    PRICING_TYPE = [
        ("Retail", "Retail"),
        ("Wholesale", "Wholesale"),
    ]

    # Segments aligned with sales categories
    CLIENT_TYPES = [
        ("RESTAURANT", "Restaurant"),
        ("CATERER", "Caterer"),
        ("RETAIL", "Retail / Supermarket / Spaza"),
        ("VENDOR", "Vendor / Street Food"),
        ("SCHOOL", "School / Hostel / Institution"),
        ("STOKVEL", "Stokvel / Group"),
        ("EVENT", "Once-off Event / Private (Funeral, Wedding, etc.)"),
        ("OTHER", "Other (Specify in notes)"),
    ]

    # A/B/C for size within a segment
    CLIENT_SIZE_TIERS = [
        ("A", "Tier A (Large / High Volume)"),
        ("B", "Tier B (Medium Volume)"),
        ("C", "Tier C (Small / Low Volume)"),
    ]

    ACCOUNT_TYPES = [
        ("CASH", "Normal (Cash/EFT)"),
        ("CREDIT", "Credit Account"),
    ]

    CREDIT_STATUS = [
        ("INACTIVE", "Inactive"),
        ("PENDING", "Pending"),
        ("ACTIVE", "Active"),
    ]

    AREA_CHOICES = [
        ("NORTH_CENTRAL", "North/Central"),
        ("SOUTH_WEST", "South/West"),
        ("EAST", "East"),
    ]

    DELIVERY_SLOT_CHOICES = [
        ("SLOT_1", "08:00 - 10:00"),
        ("SLOT_2", "10:30 - 14:00"),
        ("SLOT_3", "14:30 - 17:00"),
    ]

    funder = models.ForeignKey(
        "credit.Funder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clients",
        help_text="Optional: which funder backs this client's credit."
    )

    name = models.CharField(
        max_length=160,
        help_text="Primary display name (person or business)."
    )
    organization = models.CharField(
        max_length=200,
        blank=True,
        help_text="Company / Trading name (if applicable)."
    )

    client_type = models.CharField(
        max_length=20,
        choices=CLIENT_TYPES,
        default="RESTAURANT"
    )

    ENTITY_TYPES = [
        ("COMPANY", "Registered Company"),
        ("SOLE_TRADER", "Sole Trader / Individual"),
    ]

    entity_type = models.CharField(
        max_length=20,
        choices=ENTITY_TYPES,
        default="COMPANY",
    )

    registration_identifier = models.CharField(
        max_length=80,
        blank=True,
        help_text="Company registration number or SA ID number.",
    )

    area = models.CharField(
        max_length=20,
        choices=AREA_CHOICES,
        help_text="Territory assignment for this client."
    )


    # A/B/C classification inside the chosen client_type
    client_size_tier = models.CharField(
        max_length=1,
        choices=CLIENT_SIZE_TIERS,
        blank=True,
        help_text="Size tier for this client: A = large, B = medium, C = small."
    )

    # Auto number like CL0001
    client_number = models.CharField(
        max_length=10,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Auto-generated client number (e.g., CL0001).",
    )

    contact_person = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)

    # ---- Address / Delivery ----
    PROVINCES = [
        ("EC", "Eastern Cape"),
        ("FS", "Free State"),
        ("GP", "Gauteng"),
        ("KZN", "KwaZulu-Natal"),
        ("LP", "Limpopo"),
        ("MP", "Mpumalanga"),
        ("NC", "Northern Cape"),
        ("NW", "North West"),
        ("WC", "Western Cape"),
    ]
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    suburb = models.CharField(max_length=120, blank=True)
    city = models.CharField(
        max_length=120,
        choices=GAUTENG_CITY_CHOICES,
        blank=True,
    )
    province = models.CharField(
        max_length=10,
        choices=PROVINCES,
        blank=True,
    )
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=120, default="South Africa")

    delivery_address_line1 = models.CharField(max_length=255, blank=True)
    delivery_address_line2 = models.CharField(max_length=255, blank=True)
    delivery_suburb = models.CharField(max_length=120, blank=True)
    delivery_city = models.CharField(
        max_length=120,
        choices=GAUTENG_CITY_CHOICES,
        blank=True,
    )
    delivery_province = models.CharField(
        max_length=10,
        choices=PROVINCES,
        blank=True
    )

    delivery_postal_code = models.CharField(max_length=20, blank=True)
    delivery_country = models.CharField(max_length=120, blank=True, default="South Africa")

    # --- Delivery geolocation ---
    delivery_lat = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("-90")), MaxValueValidator(Decimal("90"))]
    )
    delivery_lng = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("-180")), MaxValueValidator(Decimal("180"))]
    )

    preferred_delivery_slot_1 = models.CharField(
        max_length=10,
        choices=DELIVERY_SLOT_CHOICES,
        blank=True,
        help_text="Client's first preferred delivery slot."
    )

    preferred_delivery_slot_2 = models.CharField(
        max_length=10,
        choices=DELIVERY_SLOT_CHOICES,
        blank=True,
        help_text="Client's second preferred delivery slot."
    )

    preferred_delivery_slot_3 = models.CharField(
        max_length=10,
        choices=DELIVERY_SLOT_CHOICES,
        blank=True,
        help_text="Client's third preferred delivery slot."
    )
    
    # ---- Compliance (for businesses) ----
    vat_number = models.CharField(max_length=80, blank=True)
    

    # ---- Categorisation ----
    categories = models.ManyToManyField(
        Category,
        blank=True,
        related_name="clients",
        help_text="What product categories this client typically buys.",
    )

    # ---- Status ----
    STATUS = [
        ("PENDING", "Pending"),
        ("ACTIVE", "Active"),
        ("INACTIVE", "Inactive"),
    ]
    status = models.CharField(max_length=10, choices=STATUS, default="PENDING")

    # ---- Spend estimate (optional) ----
    estimated_weekly_spend = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Estimated weekly spend in Rands (e.g., 2500.00).",
    )

    # ---- Misc ----
    notes = models.TextField(blank=True)
    price_type = models.CharField(max_length=10, choices=PRICING_TYPE, blank=True)

    # ---- Meta ----
    last_order_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPES, default="CASH")
    credit_status = models.CharField(max_length=10, choices=CREDIT_STATUS, default="INACTIVE")

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["client_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["client_number"]),
            models.Index(fields=["client_type", "client_size_tier"]),  # for segment + size queries
        ]
        unique_together = [("name", "organization")]

    def __str__(self):
        return self.organization or self.name

    def ensure_compliance(self):
        """
        Ensure ClientCompliance and base ClientComplianceDocument
        rows exist for this client.
        """
        ClientCompliance = apps.get_model("clients", "ClientCompliance")
        ClientComplianceDocument = apps.get_model("clients", "ClientComplianceDocument")

        # 1) Ensure compliance row exists
        compliance, _ = ClientCompliance.objects.get_or_create(
            client=self,
            defaults={
                "registration_identifier": self.registration_identifier or "",
                "vat_number": self.vat_number or "",
            }
        )

        # 2) Ensure document placeholders exist
        existing_docs = set(
            compliance.documents.values_list("document_type", flat=True)
        )

        REQUIRED_DOC_TYPES = {
            "CIPC",
            "ID",
            "PROOF_ADDRESS",
            "BANK_LETTER",
            "CONTRACT",
        }

        missing = REQUIRED_DOC_TYPES - existing_docs

        ClientComplianceDocument.objects.bulk_create(
            [
                ClientComplianceDocument(
                    compliance=compliance,
                    document_type=doc_type,
                )
                for doc_type in missing
            ],
            ignore_conflicts=True,
        )

        return compliance


    # ---------- ensure a 1–1 CreditAccount exists (no signals) ----------
    def ensure_credit_account(self):
        """
        Lazily fetch CreditAccount model from the 'credit' app and make sure
        this client has exactly one related row.
        """
        CreditAccount = apps.get_model("credit", "CreditAccount")
        ca, _ = CreditAccount.objects.get_or_create(client=self)
        # Mirror funder down if present
        if getattr(self, "funder_id", None) is not None and ca.funder_id != self.funder_id:
            ca.funder_id = self.funder_id
            ca.save(update_fields=["funder", "updated_at"])
        return ca

    # ---------- Client number helpers ----------
    @staticmethod
    def _format_client_number(n: int) -> str:
        # CL + 4-digit zero-padded
        return f"CL{n:04d}"

    @classmethod
    def next_client_number(cls) -> str:
        """
        Compute the next CL number by extracting the numeric tail
        from existing client_number values and incrementing it.
        """
        qs = (
            cls.objects
            .annotate(num_part=Cast(Substr("client_number", 3), IntegerField()))
            .exclude(num_part__isnull=True)
            .order_by("-num_part")
        )
        last = qs.first()
        last_num = last.num_part if last else 0
        return cls._format_client_number(last_num + 1)

    def save(self, *args, **kwargs):
        """
        - If credit_status is ACTIVE, force account_type to CREDIT.
        - On first save, generate client_number (inside a transaction).
        - After any successful save, ensure related objects exist.
        """

        # 1) Enforce account_type when credit goes ACTIVE
        if self.credit_status == "ACTIVE" and self.account_type != "CREDIT":
            self.account_type = "CREDIT"

        # 2) First-time save
        if not self.client_number:
            with transaction.atomic():
                self.client_number = self.next_client_number()
                super().save(*args, **kwargs)

                self.ensure_credit_account()
                self.ensure_compliance()   # ✅ ADD THIS

                return

        # 3) Normal update
        super().save(*args, **kwargs)

        self.ensure_credit_account()
        self.ensure_compliance()   # ✅ ADD THIS


    @property
    def has_delivery_geo(self) -> bool:
        return self.delivery_lat is not None and self.delivery_lng is not None

    def delivery_address_as_line(self) -> str:
        """
        Returns the dedicated delivery address (if set) as a single line.
        Falls back to the main address fields if delivery_* are blank.
        """
        parts = []
        src = "delivery" if any([
            self.delivery_address_line1,
            self.delivery_city,
            self.delivery_province,
            self.delivery_postal_code,
        ]) else "main"

        def pick(name):
            return getattr(self, f"{src}_{name}", "") if src == "delivery" else getattr(self, name, "")

        for key in ("address_line1", "address_line2", "suburb", "city", "province", "postal_code", "country"):
            v = pick(key)
            if v:
                parts.append(str(v))
        return ", ".join(parts)

    def google_maps_link(self) -> str:
        if self.has_delivery_geo:
            return f"https://www.google.com/maps?q={self.delivery_lat},{self.delivery_lng}"
        # fallback to address search
        from urllib.parse import quote_plus
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(self.delivery_address_as_line())}"
    
    def is_open_now(self):
        now = timezone.localtime()
        today = now.strftime("%a").upper()[:3]

        hours = self.operating_hours.filter(day=today).first()

        if not hours or hours.is_closed:
            return False

        if not hours.open_time or not hours.close_time:
            return False

        return hours.open_time <= now.time() <= hours.close_time
    
    def get_today_hours(self):
        today = timezone.localtime().strftime("%a").upper()[:3]
        return self.operating_hours.filter(day=today).first()

class ClientOperatingHours(models.Model):
    DAY_CHOICES = [
        ("MON", "Monday"),
        ("TUE", "Tuesday"),
        ("WED", "Wednesday"),
        ("THU", "Thursday"),
        ("FRI", "Friday"),
        ("SAT", "Saturday"),
        ("SUN", "Sunday"),
    ]

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="operating_hours",
    )

    day = models.CharField(
        max_length=3,
        choices=DAY_CHOICES,
    )

    day_order = models.IntegerField(editable=False)

    is_closed = models.BooleanField(default=False)

    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)

    class Meta:
        unique_together = ("client", "day")
        ordering = ["day"]

    def __str__(self):
        return f"{self.client} - {self.get_day_display()}"
    
    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}

        # -----------------------------
        # If marked as closed
        # -----------------------------
        if self.is_closed:
            if self.open_time or self.close_time:
                errors["is_closed"] = "Closed days must not have opening or closing times."

        # -----------------------------
        # If marked as open
        # -----------------------------
        else:
            # Both times required
            if not self.open_time:
                errors["open_time"] = "Opening time is required when the day is not closed."

            if not self.close_time:
                errors["close_time"] = "Closing time is required when the day is not closed."

            # Only compare times if both exist
            if self.open_time and self.close_time:
                if self.close_time <= self.open_time:
                    errors["close_time"] = "Closing time must be after opening time."

        # -----------------------------
        # Raise structured validation
        # -----------------------------
        if errors:
            raise ValidationError(errors)
    
    
class Prospect(models.Model):
    """
    A potential client that the sales team is working on.
    Designed to align closely with Client so conversion
    requires minimal or no re-entry of data.
    """

    # -------------------------------------------------
    # Pipeline / lifecycle
    # -------------------------------------------------
    STAGE_CHOICES = [
        ("NEW", "New"),
        ("CONTACTED", "Contacted"),
        ("SITE_VISIT", "Site visit"),
        ("NEGOTIATION", "Negotiation"),
        ("WON", "Won"),
        ("LOST", "Lost"),
    ]

    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("ARCHIVED", "Archived"),
    ]

    AREA_CHOICES = [
        ("NORTH_CENTRAL", "North/Central"),
        ("SOUTH_WEST", "South/West"),
        ("EAST", "East"),
    ]

    

    stage = models.CharField(
        max_length=20,
        choices=STAGE_CHOICES,
        default="NEW",
        db_index=True,
        help_text="Where this prospect is in the sales pipeline.",
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="ACTIVE",
        db_index=True,
    )

    ENTITY_TYPES = [
        ("COMPANY", "Registered Company"),
        ("SOLE_TRADER", "Sole Trader / Individual"),
    ]



    # -------------------------------------------------
    # Ownership / responsibility
    # -------------------------------------------------
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospects",
        help_text="Sales rep responsible for this prospect.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospects_created",
        help_text="Who originally created this prospect.",
    )

    # -------------------------------------------------
    # Identity / contact (mirrors Client)
    # -------------------------------------------------
    name = models.CharField(
        max_length=160,
        help_text="Primary name (business or person).",
    )

    organization = models.CharField(
        max_length=200,
        blank=True,
        help_text="Trading name if different.",
    )

    entity_type = models.CharField(
        max_length=20,
        choices=ENTITY_TYPES,
        default="COMPANY",
        help_text="Whether this prospect is a registered company or a sole trader.",
    )

    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)

    # -------------------------------------------------
    # Segmentation (directly maps to Client)
    # -------------------------------------------------
    CLIENT_TYPES = Client.CLIENT_TYPES
    CLIENT_SIZE_TIERS = Client.CLIENT_SIZE_TIERS
    PROVINCES = Client.PROVINCES

    potential_client_type = models.CharField(
        max_length=20,
        choices=CLIENT_TYPES,
        blank=True,
        help_text="Expected client type (e.g. Restaurant, Caterer).",
    )

    potential_size_tier = models.CharField(
        max_length=1,
        choices=CLIENT_SIZE_TIERS,
        blank=True,
        help_text="Expected size tier: A (large), B (medium), C (small).",
    )

    # -------------------------------------------------
    # Address (light but conversion-ready)
    # -------------------------------------------------
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    suburb = models.CharField(max_length=120, blank=True)
    city = models.CharField(
        max_length=120,
        choices=GAUTENG_CITY_CHOICES,
        blank=True,
    )
    province = models.CharField(
        max_length=10,
        choices=PROVINCES,
        blank=True,
    )
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=120, default="South Africa")

    area = models.CharField(
        max_length=20,
        choices=AREA_CHOICES,
        help_text="Territory assignment for this prospect."
    )

    # -------------------------------------------------
    # Early compliance (optional, speeds up conversion)
    # -------------------------------------------------
    vat_number = models.CharField(max_length=80, blank=True)
    
    registration_identifier = models.CharField(
        max_length=80,
        blank=True,
    )

    # -------------------------------------------------
    # Product interest (mirrors Client.categories)
    # -------------------------------------------------
    categories = models.ManyToManyField(
        Category,
        blank=True,
        related_name="prospects",
        help_text="What this prospect is likely to buy.",
    )

    # -------------------------------------------------
    # Value & forecasting
    # -------------------------------------------------
    estimated_weekly_spend = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Estimated weekly spend if converted (Rands).",
    )

    # -------------------------------------------------
    # Sales activity tracking
    # -------------------------------------------------
    last_contact_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last engagement with this prospect.",
    )

    next_follow_up_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Planned next follow-up.",
    )

    lead_source = models.CharField(
        max_length=120,
        blank=True,
        help_text="Where this lead came from (referral, walk-in, Facebook, etc.).",
    )

    # -------------------------------------------------
    # Conversion link
    # -------------------------------------------------
    client = models.ForeignKey(
        Client,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="prospects",
        help_text="Client created from this prospect (if converted).",
    )

    # -------------------------------------------------
    # Notes & meta
    # -------------------------------------------------
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # -------------------------------------------------
    # Meta
    # -------------------------------------------------
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["stage"]),
            models.Index(fields=["status"]),
            models.Index(fields=["owner", "stage"]),
            models.Index(fields=["city", "province"]),
            models.Index(fields=["created_by", "created_at"]),
        ]

    # -------------------------------------------------
    # Helpers
    # -------------------------------------------------
    def __str__(self) -> str:
        return self.organization or self.name

    @property
    def age_days(self) -> int:
        if not self.created_at:
            return 0
        today = timezone.localdate()
        return (today - self.created_at.date()).days

    @property
    def is_closed(self) -> bool:
        return self.stage in {"WON", "LOST"}

    @property
    def is_overdue(self) -> bool:
        if self.is_closed:
            return False
        return self.age_days > 7

    @property
    def sla_status(self) -> str:
        if self.is_closed:
            return "Closed"
        days = self.age_days
        if days <= 2:
            return "Fresh"
        elif days <= 7:
            return "On track"
        elif days <= 14:
            return "Overdue"
        return "Very overdue"
    
    


    
class ProspectOperatingHours(models.Model):
    DAY_CHOICES = ClientOperatingHours.DAY_CHOICES

    prospect = models.ForeignKey(
        Prospect,
        on_delete=models.CASCADE,
        related_name="operating_hours",
    )

    day = models.CharField(
        max_length=3,
        choices=DAY_CHOICES,
    )

    day_order = models.IntegerField(editable=False)

    is_closed = models.BooleanField(default=False)

    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)

    class Meta:
        unique_together = ("prospect", "day")
        ordering = ["day"]

    def __str__(self):
        return f"{self.prospect} - {self.get_day_display()}"
    
    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}

        if self.is_closed:
            if self.open_time or self.close_time:
                errors["is_closed"] = "Closed days must not have opening or closing times."

        else:
            if not self.open_time:
                errors["open_time"] = "Opening time is required when the day is not closed."

            if not self.close_time:
                errors["close_time"] = "Closing time is required when the day is not closed."

            if self.open_time and self.close_time:
                if self.close_time <= self.open_time:
                    errors["close_time"] = "Closing time must be after opening time."

        if errors:
            raise ValidationError(errors)
        
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    



class ClientCompliance(models.Model):
    VETTING_STATUS = [
        ("PENDING", "Pending"),
        ("IN_REVIEW", "In Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("EXPIRED", "Expired"),
    ]

    client = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name="compliance",
    )

    # --- Registration & identity ---
    registration_identifier = models.CharField(
        max_length=80,
        blank=True,
    )
    vat_number = models.CharField(max_length=80, blank=True)

    # --- Vetting state ---
    vetting_status = models.CharField(
        max_length=20,
        choices=VETTING_STATUS,
        default="PENDING",
        db_index=True,
    )

    vetted_at = models.DateTimeField(null=True, blank=True)
    vetted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vetted_clients",
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)



    
class ClientComplianceDocument(models.Model):
    DOCUMENT_TYPES = [
        ("CIPC", "CIPC Registration"),
        ("ID", "Director ID"),
        ("PROOF_ADDRESS", "Proof of Address"),
        ("BANK_LETTER", "Bank Confirmation Letter"),
        ("CONTRACT", "Signed Contract / Agreement"),
        ("OTHER", "Other"),
    ]
    
    DOCUMENT_STATUS = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    compliance = models.ForeignKey(
        ClientCompliance,
        on_delete=models.CASCADE,
        related_name="documents",
    )

    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPES)
    file = models.FileField(upload_to="compliance/client_docs/", blank=True)
    
    status = models.CharField(
        max_length=20,
        choices=DOCUMENT_STATUS,
        default="PENDING",
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_documents",
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    notes = models.CharField(max_length=255, blank=True)




# --------- keep CreditAccount.funder mirrored from Client.funder ----------
@receiver(post_save, sender=Client)
def sync_creditaccount_funder(sender, instance: Client, created, **kwargs):
    """
    Keep CreditAccount.funder in sync with Client.funder IF that field exists.
    No-op if CreditAccount has no 'funder' field.
    """
    # Ensure the 1–1 exists (per your earlier helper)
    ca = instance.ensure_credit_account()

    # If CreditAccount has no funder field, just bail out
    if not hasattr(ca, "funder_id"):
        return

    client_funder_id = getattr(instance, "funder_id", None)
    if ca.funder_id != client_funder_id:
        # Update only if the field exists
        ca.funder_id = client_funder_id
        ca.save(update_fields=["funder"])






class ProspectUpdate(models.Model):
    """
    Timeline entry for a prospect:
    - calls, WhatsApps, visits, emails, samples, etc.
    - outcome (answered, no answer, interested, not interested, etc.)
    - optional stage transitions (old_stage → new_stage)
    """

    ACTION_CHOICES = [
        ("CALL", "Call"),
        ("WHATSAPP", "WhatsApp"),
        ("VISIT", "Visit"),
        ("EMAIL", "Email"),
        ("SAMPLE", "Sample delivered / site visit"),
        ("NEGOTIATION", "Negotiation / deal discussion"),
        ("OTHER", "Other"),
    ]

    OUTCOME_CHOICES = [
        ("NO_ANSWER", "No answer"),
        ("ANSWERED", "Answered"),
        ("INTERESTED", "Interested"),
        ("NOT_INTERESTED", "Not interested"),
        ("REQUESTED_PRICELIST", "Requested price list"),
        ("REQUESTED_SAMPLE", "Requested sample"),
        ("SAMPLE_DROPPED", "Sample dropped off"),
        ("FOLLOW_UP_AGREED", "Follow-up agreed"),
        ("DEAL_WON", "Deal won"),
        ("DEAL_LOST", "Deal lost"),
        ("OTHER", "Other"),
    ]

    prospect = models.ForeignKey(
        Prospect,
        on_delete=models.CASCADE,
        related_name="updates",
        help_text="Prospect this update belongs to.",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospect_updates",
        help_text="Who logged/performed this action.",
    )

    action_type = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        help_text="Type of activity (call, WhatsApp, visit, sample, etc.).",
    )
    outcome = models.CharField(
        max_length=30,
        choices=OUTCOME_CHOICES,
        blank=True,
        help_text="Outcome of this action (answered, no answer, interested, etc.).",
    )

    # When the action actually happened (could be backdated)
    action_at = models.DateTimeField(
        default=timezone.now,
        help_text="When this action took place.",
    )

    # Optional stage transition
    old_stage = models.CharField(
        max_length=20,
        choices=Prospect.STAGE_CHOICES,
        blank=True,
    )
    new_stage = models.CharField(
        max_length=20,
        choices=Prospect.STAGE_CHOICES,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
        help_text="Extra detail (e.g. 'Called at 10:30, rang out' or 'Dropped 2kg wings').",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # For site visit actions
    visit_date = models.DateField(null=True, blank=True)
    visit_time_arrived = models.TimeField(null=True, blank=True)
    visit_time_left = models.TimeField(null=True, blank=True)
    visit_contact_name = models.CharField(max_length=120, blank=True)
    visit_photo = models.ImageField(
        upload_to="prospects/site_visits/",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-action_at", "-created_at"]
        indexes = [
            models.Index(fields=["prospect", "action_at"]),
            models.Index(fields=["action_type"]),
            models.Index(fields=["outcome"]),
        ]

    # For negotiation actions
    negotiation_products = models.TextField(
        blank=True,
        help_text="What products they are interested in (now).",
    )
    negotiation_menu_opportunities = models.TextField(
        blank=True,
        help_text="Other menu items / future opportunities to target later.",
    )
    negotiation_competitor_info = models.TextField(
        blank=True,
        help_text="Current supplier, approximate pricing, or deal constraints (optional).",
    )

    def __str__(self) -> str:
        label = dict(self.ACTION_CHOICES).get(self.action_type, self.action_type)
        return f"{self.prospect.name} · {label} @ {self.action_at:%Y-%m-%d %H:%M}"

