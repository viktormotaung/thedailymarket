# C:\Seshibo Daily Market\seshibo_site\clients\forms.py
from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Client, Prospect, ProspectUpdate

# Try import CITY_CHOICES if you expose it; otherwise provide a sensible fallback
try:
    from .models import CITY_CHOICES  # if you’ve exported it in models/__init__ or models.py
except Exception:
    CITY_CHOICES = [
        ("Johannesburg", "Johannesburg"),
        ("Pretoria", "Pretoria"),
        ("Centurion", "Centurion"),
        ("Midrand", "Midrand"),
        ("Sandton", "Sandton"),
        ("Randburg", "Randburg"),
        ("Roodepoort", "Roodepoort"),
        ("Soweto", "Soweto"),
        ("Other (Gauteng)", "Other (Gauteng)"),
    ]


# ----------------------------
# Small helper for Bootstrap
# ----------------------------
def _add_bs_classes(field: forms.Field, *, is_check: bool = False) -> None:
    widget = field.widget
    if is_check:
        widget.attrs.setdefault("class", "form-check-input")
    else:
        base = widget.attrs.get("class", "")
        widget.attrs["class"] = (base + " form-control").strip()


# --------------------------------
# Full-fat Client editor form
# --------------------------------
class ClientForm(forms.ModelForm):
    """
    Comprehensive Client editor. Use this in your back-office/admin-ish UI.
    Includes validation and light Bootstrap styling.
    """

    # Make some explicit ChoiceFields for nicer dropdowns
    city = forms.ChoiceField(choices=CITY_CHOICES, required=False)
    delivery_city = forms.ChoiceField(choices=CITY_CHOICES, required=False)

    # Expose model choices safely
    client_type = forms.ChoiceField(
        choices=getattr(Client, "CLIENT_TYPES", ()),
        required=True,
        initial="HOUSEHOLD",  # keeping your original default
        label="Client Type",
    )
    price_type = forms.ChoiceField(
        choices=getattr(
            Client,
            "PRICING_TYPE",
            (("Retail", "Retail"), ("Wholesale", "Wholesale")),
        ),
        required=False,
        label="Price Type",
    )
    status = forms.ChoiceField(
        choices=getattr(
            Client,
            "STATUS",
            (("PENDING", "Pending"), ("ACTIVE", "Active"), ("INACTIVE", "Inactive")),
        ),
        required=True,
        initial="PENDING",
        label="Status",
    )
    account_type = forms.ChoiceField(
        choices=getattr(
            Client,
            "ACCOUNT_TYPES",
            (("CASH", "Normal (Cash/EFT)"), ("CREDIT", "Credit Account")),
        ),
        required=True,
        initial="CASH",
        label="Account Type",
    )
    credit_status = forms.ChoiceField(
        choices=getattr(
            Client,
            "CREDIT_STATUS",
            (("INACTIVE", "Inactive"), ("PENDING", "Pending"), ("ACTIVE", "Active")),
        ),
        required=True,
        initial="INACTIVE",
        label="Credit Status",
    )

    class Meta:
        model = Client
        fields = [
            # Identity
            "name",
            "organization",
            "client_type",
            "status",
            # Contacts
            "contact_person",
            "email",
            "phone",
            "whatsapp",
            # Billing/Main address
            "address_line1",
            "address_line2",
            "suburb",
            "city",
            "province",
            "postal_code",
            "country",
            # Delivery address
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_suburb",
            "delivery_city",
            "delivery_province",
            "delivery_postal_code",
            "delivery_country",
            # Delivery geolocation
            "delivery_lat",
            "delivery_lng",
            # Compliance (business)
            "vat_number",
            "company_reg_number",
            # Commercials
            "estimated_weekly_spend",
            "price_type",
            # Accounting flags
            "account_type",
            "credit_status",
            # Notes
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Styling
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.RadioSelect, forms.CheckboxInput)):
                _add_bs_classes(field, is_check=True)
            else:
                _add_bs_classes(field)

        # Optional placeholders
        self.fields["name"].widget.attrs.setdefault(
            "placeholder", "Primary display name (person or business)"
        )
        self.fields["organization"].widget.attrs.setdefault(
            "placeholder", "Company / Trading name (optional)"
        )
        self.fields["email"].widget.attrs.setdefault(
            "placeholder", "name@example.com"
        )
        self.fields["phone"].widget.attrs.setdefault(
            "placeholder", "+27 82 123 4567"
        )
        self.fields["whatsapp"].widget.attrs.setdefault(
            "placeholder", "+27 82 123 4567"
        )

    # -------- Validation --------
    def clean(self):
        cleaned = super().clean()

        name = (cleaned.get("name") or "").strip()
        org = (cleaned.get("organization") or "").strip()
        if not name and not org:
            raise ValidationError("Provide at least a Name or an Organization.")

        # If credit_status becomes ACTIVE, force account_type to CREDIT (mirrors model.save logic)
        credit_status = cleaned.get("credit_status")
        if credit_status == "ACTIVE":
            cleaned["account_type"] = "CREDIT"

        # Guard against negative spend
        spend = cleaned.get("estimated_weekly_spend")
        if spend is not None and spend < Decimal("0"):
            self.add_error(
                "estimated_weekly_spend",
                "Estimated weekly spend cannot be negative.",
            )

        return cleaned


# -------------------------------------------------
# Lightweight “quick create” form (front-office)
# -------------------------------------------------
class ClientQuickCreateForm(forms.ModelForm):
    """
    Minimal form you can use on a public-facing “Become a Supplier/Client”
    or sales capture page. Keeps fields lean but valid.
    """

    city = forms.ChoiceField(choices=CITY_CHOICES, required=False)

    class Meta:
        model = Client
        fields = [
            "name",
            "organization",
            "client_type",
            "email",
            "phone",
            "whatsapp",
            "address_line1",
            "suburb",
            "city",
            "province",
            "postal_code",
            "estimated_weekly_spend",
            "price_type",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "client_type": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for f in self.fields.values():
            if isinstance(f.widget, (forms.RadioSelect, forms.CheckboxInput)):
                _add_bs_classes(f, is_check=True)
            else:
                _add_bs_classes(f)

        # Sensible defaults
        if "client_type" in self.fields and not self.fields["client_type"].initial:
            self.fields["client_type"].initial = "HOUSEHOLD"

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("name") or "").strip()
        org = (cleaned.get("organization") or "").strip()
        if not name and not org:
            raise ValidationError("Provide at least a Name or an Organization.")
        return cleaned


# -------------------------------------------------
# Contact-only updater (useful for “Edit Contact”)
# -------------------------------------------------
class ClientContactForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["contact_person", "email", "phone", "whatsapp", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            _add_bs_classes(f)


# -------------------------------------------------
# Prospect Forms
# -------------------------------------------------
class ProspectForm(forms.ModelForm):
    """
    Main create / edit form for Prospects.

    - Owner & created_by are set in the view (from request.user), so excluded.
    - Client link is managed when you convert a prospect to a client, so also excluded.
    """

    class Meta:
        model = Prospect
        fields = [
            "name",
            "organization",
            "contact_name",
            "email",
            "phone",
            "whatsapp",
            "potential_client_type",
            "potential_size_tier",
            "suburb",
            "city",
            "province",
            "stage",
            "status",
            "estimated_weekly_spend",
            "last_contact_at",
            "next_follow_up_at",
            "lead_source",
            "notes",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Nando's Krugersdorp",
                }
            ),
            "organization": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Trading name (if different)",
                }
            ),
            "contact_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Contact person name",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Email address",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Primary phone number",
                }
            ),
            "whatsapp": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "WhatsApp number (if different)",
                }
            ),
            "potential_client_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "potential_size_tier": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "suburb": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),
            "city": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),
            "province": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "stage": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "estimated_weekly_spend": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "e.g. 2500.00",
                }
            ),
            "last_contact_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "next_follow_up_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "lead_source": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Facebook, referral, walk-in",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Extra notes about this prospect...",
                }
            ),
        }

    def clean(self):
        """
        Light validation:
        - Require at least one direct contact channel (phone / WhatsApp / email).
        """
        cleaned = super().clean()
        email = cleaned.get("email")
        phone = cleaned.get("phone")
        whatsapp = cleaned.get("whatsapp")

        if not email and not phone and not whatsapp:
            raise forms.ValidationError(
                "Please provide at least one contact method (phone, WhatsApp or email)."
            )

        return cleaned


class ProspectUpdateForm(forms.ModelForm):
    """
    Form for logging an activity against a Prospect:
    - call, WhatsApp, visit, sample, etc.
    - outcome (no answer, interested, etc.)
    - optional stage transition (e.g. CONTACTED → NEGOTIATION).
    """

    class Meta:
        model = ProspectUpdate
        fields = [
            "action_type",
            "outcome",
            "action_at",
            "new_stage",
            "notes",
        ]
        widgets = {
            "action_type": forms.Select(attrs={"class": "form-select"}),
            "outcome": forms.Select(attrs={"class": "form-select"}),
            "action_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "new_stage": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "e.g. Called at 10:30, rang out. Left WhatsApp message.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        # allow view to pass current prospect stage for UX (optional)
        self.current_stage = kwargs.pop("current_stage", None)
        super().__init__(*args, **kwargs)

        # Default action_at (for the datetime-local input)
        if not self.initial.get("action_at"):
            self.initial["action_at"] = timezone.now().strftime("%Y-%m-%dT%H:%M")

        # new_stage is optional – user can log activity without moving the pipeline
        self.fields["new_stage"].required = False

    def save(self, commit=True):
        """
        On save:
        - Set old_stage to the prospect's current stage (if available).
        - If new_stage is set and different from prospect.stage:
          * populate old_stage/new_stage on the update
          * update the Prospect.stage
        - Always set Prospect.last_contact_at = action_at
        """
        update = super().save(commit=False)

        prospect = getattr(update, "prospect", None)
        if prospect:
            current_stage = prospect.stage

            # If user selected a new_stage, record transition
            if update.new_stage:
                if update.new_stage != current_stage:
                    update.old_stage = current_stage
                    prospect.stage = update.new_stage
            else:
                # No new_stage given; keep old_stage = current stage for history if not already set
                if not update.old_stage:
                    update.old_stage = current_stage

            # Sync last_contact_at with this interaction
            prospect.last_contact_at = update.action_at or timezone.now()

            if commit:
                prospect.save(update_fields=["stage", "last_contact_at", "updated_at"])

        if commit:
            update.save()

        return update
    
class ClientMinimalForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            "name",
            "organization",
            "company_reg_number",
            "client_type",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "organization": forms.TextInput(attrs={"class": "form-control"}),
            "company_reg_number": forms.TextInput(attrs={"class": "form-control"}),  # 🔑
            "client_type": forms.Select(attrs={"class": "form-select"}),
        }


class ClientBusinessForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            # --- Identity & Contact ---
            "name",
            "organization",
            "contact_person",
            "email",
            "phone",
            "whatsapp",
            "client_type",
            "client_size_tier",
            "categories",

            # --- Address ---
            "address_line1",
            "address_line2",
            "suburb",
            "city",
            "province",
            "postal_code",

            # --- Delivery ---
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_suburb",
            "delivery_city",
            "delivery_province",
            "delivery_postal_code",
            "delivery_lat",
            "delivery_lng",

            # --- Compliance ---
            "vat_number",
            "company_reg_number",
            "price_type",
            "estimated_weekly_spend",
            "notes",
        ]

        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
            "categories": forms.CheckboxSelectMultiple(),
        }