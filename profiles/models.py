#profiles/models
from django.conf import settings
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from clients.models import Client
from django.utils import timezone
from datetime import timedelta
from consumers.models import Consumer
from decimal import Decimal


def _online_window():
    # fallback to 5 minutes if not set in settings
    minutes = getattr(settings, "ONLINE_WINDOW_MINUTES", 5)
    return timedelta(minutes=minutes)


class Department(models.Model):

    name = models.CharField(
        max_length=120,
        unique=True,
    )

    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Internal department code.",
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    email = models.EmailField(
        blank=True,
        null=True,
        help_text="Department email address.",
    )

    # OPTIONAL
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_departments",
    )

    # ✅ Department members
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="departments",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

        

class StaffProfile(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]


    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )
    job_title = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=50, blank=True)

    status = models.CharField(
        max_length=8,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
        help_text="Approval state of this profile.",
    )

    

    primary_department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_staff_profiles",
    )

    departments = models.ManyToManyField(
        "Department",
        blank=True,
        related_name="staff_members",
    )

    # ✅ NEW: allow staff to also be granted Sales portal access explicitly
    can_access_sales = models.BooleanField(
        default=False,
        help_text="Allow this staff member to access the Sales portal.",
    )

    # store a HASH, not the raw code
    auth_code_hash = models.CharField(
        "authorisation code (hashed)",
        max_length=128,
        blank=True,
        help_text="Hashed staff authorisation code; set via admin form.",
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # ---- helpers for the secret code ----
    def set_auth_code(self, raw_code: str, *, save: bool = True) -> None:
        self.auth_code_hash = "" if not raw_code else make_password(raw_code)
        if save:
            self.save(update_fields=["auth_code_hash", "updated_at"])

    def verify_auth_code(self, raw_code: str) -> bool:
        return bool(self.auth_code_hash and check_password(raw_code, self.auth_code_hash))

    # ---- online helpers ----
    def mark_seen(self, *, save=True):
        self.last_seen_at = timezone.now()
        if save:
            self.save(update_fields=["last_seen_at", "updated_at"])

    @property
    def is_online(self) -> bool:
        if not self.last_seen_at:
            return False
        return timezone.now() - self.last_seen_at <= _online_window()

    def __str__(self):
        name = (self.user.get_full_name() or self.user.get_username()).strip()
        return f"Staff Profile for {name}"


class CustomerProfile(models.Model):
    PROFILE_CHOICES = [
        ("CONSUMER", "Consumer"),
        ("BUSINESS", "Business"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )

    profile_type = models.CharField(
        max_length=10,
        choices=PROFILE_CHOICES,
        default="CONSUMER",
        db_index=True,
    )

    status = models.CharField(
        max_length=8,
        choices=STATUS_CHOICES,
        default="active",
        db_index=True,
        help_text="Approval state of this profile.",
    )

    # Common fields
    phone = models.CharField(max_length=50, blank=True)
    display_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="How we should address you on documents/communication.",
    )

    consumer = models.OneToOneField(
        Consumer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profile",
    )

    # Business-only linkage
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profiles",
        help_text="Required when profile type is Business.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    
    # convenience
    @property
    def is_business(self) -> bool:
        return self.profile_type == "BUSINESS"
    
    @property
    def is_consumer(self):
        return self.profile_type == "CONSUMER"


    @property
    def effective_client(self) -> Client | None:
        return self.client if self.is_business else None

    # online helpers
    def mark_seen(self, *, save=True):
        self.last_seen_at = timezone.now()
        if save:
            self.save(update_fields=["last_seen_at", "updated_at"])

    @property
    def is_online(self) -> bool:
        if not self.last_seen_at:
            return False
        return timezone.now() - self.last_seen_at <= _online_window()

    def __str__(self):
        who = self.display_name or self.user.get_full_name() or self.user.get_username()
        return f"{who} · {self.get_profile_type_display()}"
    
    def clean(self):
        from django.core.exceptions import ValidationError

        if self.profile_type == "BUSINESS" and not self.client:
            raise ValidationError({"client": "Business profiles must be linked to a Client."})

        if self.profile_type == "CONSUMER" and not self.consumer:
            raise ValidationError({"consumer": "Consumer profiles must be linked to a Consumer."})
        
    def save(self, *args, **kwargs):
        # Enforce display_name for business profiles
        if self.profile_type == "BUSINESS" and self.client:
            self.display_name = self.client.name

        self.full_clean()
        super().save(*args, **kwargs)


class SalesRole(models.Model):
    """
    Defines roles a sales user can have.
    Users can have multiple roles.
    """

    code = models.CharField(
        max_length=30,
        unique=True,
        help_text="Internal role code, e.g. rep, supervisor",
    )

    name = models.CharField(
        max_length=50,
        help_text="Human readable role name",
    )

    def __str__(self):
        return self.name


class SalesRepProfile(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sales_rep_profile",
    )

    # Link to the staff profile (optional if user might not have one yet)
    staff_profile = models.OneToOneField(
        "StaffProfile",
        on_delete=models.CASCADE,
        related_name="sales_profile",
        null=True,
        blank=True,
        help_text="Link to the staff profile (every sales rep must have a staff profile)."
    )

    status = models.CharField(
        max_length=8,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
        help_text="Approval state of this profile.",
    )

    sales_operator = models.ForeignKey(
        "SalesOperator",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_reps",
        help_text="Sales operator this sales rep belongs to."
    )

    region = models.ForeignKey(
        "clients.Region",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales_profiles",
        help_text="Region assigned to this sales user."
    )

    territory = models.ForeignKey(
        "clients.Territory",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales_profiles",
        help_text="Territory assigned to this sales user."
    )
    

    base_commission_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Standard commission percentage paid to this sales rep."
    )

    bonus_commission_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Additional bonus commission percentage paid when targets or conditions are met."
    )

    # store a HASH, not the raw code
    auth_code_hash = models.CharField(
        "authorisation code (hashed)",
        max_length=128,
        blank=True,
        help_text="Hashed staff authorisation code; set via admin form.",
    )

    department = models.CharField(
        max_length=50,
        default="SALES",
        blank=True,
        null=True,
    )

    # ✅ NEW: multi-role support
    roles = models.ManyToManyField(
        "SalesRole",
        blank=True,
        related_name="sales_profiles",
        help_text="Roles this sales user fulfills (rep, supervisor, or both).",
    )

    # ✅ NEW: supervisor for this rep
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supervised_reps",
        help_text="Supervisor/manager responsible for this sales rep.",
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)

    

    # ---- helpers for the secret code ----
    def set_auth_code(self, raw_code: str, *, save: bool = True) -> None:
        self.auth_code_hash = "" if not raw_code else make_password(raw_code)
        if save:
            self.save(update_fields=["auth_code_hash", "updated_at"])

    def verify_auth_code(self, raw_code: str) -> bool:
        return bool(self.auth_code_hash and check_password(raw_code, self.auth_code_hash))

    # ---- online helpers ----
    def mark_seen(self, *, save=True):
        self.last_seen_at = timezone.now()
        if save:
            self.save(update_fields=["last_seen_at", "updated_at"])

    @property
    def is_online(self) -> bool:
        if not self.last_seen_at:
            return False
        return timezone.now() - self.last_seen_at <= _online_window()

    def __str__(self):
        name = (self.user.get_full_name() or self.user.get_username()).strip()
        return f"SalesRepProfile for {name}"



class DriverProfile(models.Model):
    """
    Driver-specific profile.
    Extends StaffProfile with fleet & shift-related data.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("suspended", "Suspended"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="driver_profile",
    )

    staff_profile = models.OneToOneField(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="driver_profile",
        help_text="Every driver must also be a staff member.",
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)



class SalesOperator(models.Model):
    """
    Commercial sales operator / territory holder.
    Used for outsourced sales structures, territory assignments,
    and commission-linked operator management.
    """

    AREA_CHOICES = [
        ("SOUTH_WEST", "South / West"),
        ("EAST", "East"),
        ("NORTH_CENTRAL", "North / Central"),
        ("MIDVAAL", "Midvaal"),
        ("PRETORIA", "Pretoria"),
        ("OTHER", "Other"),
    ]

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Registered or trading name of the sales operator."
    )

    owner_1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="primary_sales_operators",
        help_text="Primary owner/user linked to this operator."
    )

    owner_2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="secondary_sales_operators",
        null=True,
        blank=True,
        help_text="Secondary owner/user linked to this operator (optional)."
    )

    territory = models.CharField(
        max_length=20,
        choices=AREA_CHOICES,
        db_index=True,
        help_text="Assigned operating territory."
    )

    # Address Information
    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True)

    suburb = models.CharField(max_length=120)
    city = models.CharField(max_length=120)

    province = models.CharField(max_length=120)
    postal_code = models.CharField(max_length=20)

    # Banking Details
    bank_name = models.CharField(max_length=120)
    account_holder = models.CharField(max_length=255)

    account_number = models.CharField(max_length=50)
    branch_code = models.CharField(max_length=20)

    ACCOUNT_TYPE_CHOICES = [
        ("CHEQUE", "Cheque"),
        ("SAVINGS", "Savings"),
        ("BUSINESS", "Business"),
    ]

    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPE_CHOICES,
        default="CHEQUE",
    )

    base_commission_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Standard commission percentage paid to this operator."
    )

    bonus_commission_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Additional bonus commission percentage paid when targets or conditions are met."
    )

    responsible_user_1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="primary_managed_sales_operators",
        null=True,
        blank=True,
        help_text="Primary internal user responsible for managing this sales operator."
    )

    responsible_user_2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="secondary_managed_sales_operators",
        null=True,
        blank=True,
        help_text="Secondary internal user responsible for managing this sales operator."
    )

    # Operational
    is_active = models.BooleanField(default=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Sales Operator"
        verbose_name_plural = "Sales Operators"

    def __str__(self):
        return f"{self.name} ({self.get_territory_display()})"

    @property
    def full_address(self):
        parts = [
            self.address_line_1,
            self.address_line_2,
            self.suburb,
            self.city,
            self.province,
            self.postal_code,
        ]

        return ", ".join([p for p in parts if p])
