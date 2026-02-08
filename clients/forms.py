# C:\Seshibo Daily Market\seshibo_site\clients\forms.py
from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Client
from .models import GAUTENG_CITY_CHOICES
from products.models import Category
from .models import Client, Prospect, ProspectUpdate, ClientCompliance, ClientComplianceDocument

def _bs(extra_class=None):
    """
    Bootstrap helper for form widgets.
    Usage:
      _bs() -> {"class": "form-control"}
      _bs("form-select") -> {"class": "form-select"}
    """
    return {
        "class": extra_class or "form-control"
    }

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
    Main create / edit form for Clients.
    """

    # ----------------------------
    # ADDRESS DROPDOWNS (FORM-OWNED)
    # ----------------------------
    city = forms.ChoiceField(
        choices=GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="City",
    )

    delivery_city = forms.ChoiceField(
        choices=GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Delivery City",
    )

    delivery_province = forms.ChoiceField(
        choices=Client.PROVINCES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Delivery Province",
    )

    class Meta:
        model = Client
        fields = [
            # Identity
            "entity_type",
            "name",
            "organization",
            "client_type",
            "client_size_tier",

            # Contact
            "contact_person",
            "email",
            "phone",
            "whatsapp",

            # Business address
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
            # ❌ delivery_province REMOVED
            "delivery_postal_code",
            "delivery_country",

            # Compliance
            "registration_identifier",
            "vat_number",

            # Commercial
            "price_type",
            "estimated_weekly_spend",

            # Categorisation
            "categories",

            # Status & credit
            "status",
            "account_type",
            "credit_status",

            # Notes
            "notes",
        ]
        
        widgets = {
            "entity_type": forms.Select(attrs=_bs("form-select")),
            "city": forms.Select(attrs={"class": "form-select"}),
            "province": forms.Select(attrs={"class": "form-select"}),
            "client_type": forms.Select(attrs={"class": "form-select"}),
            "client_size_tier": forms.Select(attrs={"class": "form-select"}),
            "price_type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "account_type": forms.Select(attrs={"class": "form-select"}),
            "credit_status": forms.Select(attrs={"class": "form-select"}),
        }



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
            "entity_type",
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
            "entity_type": forms.Select(attrs=_bs("form-select")),
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

    - owner & created_by are set in the view
    - client link is handled on conversion
    - City uses explicit dropdown choices (same pattern as ClientForm)
    """

    # ----------------------------
    # ADDRESS DROPDOWNS (MATCH CLIENT FORM)
    # ----------------------------
    city = forms.ChoiceField(
        choices=GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="City",
    )
    
    # ----------------------------
    # META
    # ----------------------------
    class Meta:
        model = Prospect
        fields = [
            # ---- Identity / contact ----
            "entity_type",
            "name",
            "organization",
            "contact_name",
            "email",
            "phone",
            "whatsapp",

            # ---- Segmentation ----
            "potential_client_type",
            "potential_size_tier",

            # ---- Address (conversion-ready) ----
            "address_line1",
            "address_line2",
            "suburb",
            "city",
            "province",
            "postal_code",
            "country",

            # ---- Early compliance ----
            "registration_identifier",
            "vat_number",

            # ---- Product interest ----
            "categories",

            # ---- Pipeline & value ----
            "stage",
            "status",
            "estimated_weekly_spend",

            # ---- Sales activity ----
            "last_contact_at",
            "next_follow_up_at",
            "lead_source",

            # ---- Notes ----
            "notes",
        ]

        widgets = {
            # Identity
            "entity_type": forms.Select(attrs=_bs("form-select")),
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Nando's Krugersdorp",
            }),
            "organization": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Trading name (if different)",
            }),
            "contact_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Contact person name",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "name@example.com",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "+27 82 123 4567",
            }),
            "whatsapp": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "+27 82 123 4567",
            }),

            # Segmentation
            "potential_client_type": forms.Select(attrs={"class": "form-select"}),
            "potential_size_tier": forms.Select(attrs={"class": "form-select"}),

            # Address
            "address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "suburb": forms.TextInput(attrs={"class": "form-control"}),
            "province": forms.Select(attrs={"class": "form-select"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),

            # Compliance
            "registration_identifier": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "registration_identifier",
            }),
            "vat_number": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "VAT number (if registered)",
            }),

            # Categories
            "categories": forms.SelectMultiple(
                attrs={"class": "form-select", "size": 6}
            ),

            # Pipeline & value
            "stage": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "estimated_weekly_spend": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "placeholder": "e.g. 2500.00",
            }),

            # Activity
            "last_contact_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "next_follow_up_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "lead_source": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Facebook, referral, walk-in",
            }),

            # Notes
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Extra notes about this prospect...",
            }),
        }

    # ----------------------------
    # INIT
    # ----------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["registration_identifier"].label = "Registration / ID Number"
        self.fields["registration_identifier"].help_text = (
            "Company registration number or South African ID number."
        )

        self.fields["categories"].queryset = (
            Category.objects.filter(is_active=True).order_by("name")
        )

        self.fields["country"].initial = "South Africa"

    def clean(self):
        cleaned = super().clean()

        if not any([
            cleaned.get("email"),
            cleaned.get("phone"),
            cleaned.get("whatsapp"),
        ]):
            raise ValidationError(
                "Provide at least one contact method (email, phone, or WhatsApp)."
            )

        spend = cleaned.get("estimated_weekly_spend")
        if spend is not None and spend < Decimal("0"):
            self.add_error("estimated_weekly_spend", "Spend cannot be negative.")

        return cleaned

    



class ProspectUpdateForm(forms.ModelForm):
    """
    Log an activity against a Prospect:
    - call, WhatsApp, visit, sample, etc.
    - optional stage transition
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
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "e.g. Called at 10:30, rang out. Left WhatsApp message.",
            }),
        }

    def __init__(self, *args, **kwargs):
        self.current_stage = kwargs.pop("current_stage", None)
        super().__init__(*args, **kwargs)

        # Default action time = now (for UX)
        if not self.initial.get("action_at"):
            self.initial["action_at"] = timezone.now().strftime("%Y-%m-%dT%H:%M")

        # new_stage is optional
        self.fields["new_stage"].required = False

    def save(self, commit=True):
        """
        - Capture old_stage
        - Apply stage transition if selected
        - Always sync last_contact_at
        """
        update = super().save(commit=False)
        prospect = update.prospect

        current_stage = prospect.stage

        if update.new_stage and update.new_stage != current_stage:
            update.old_stage = current_stage
            prospect.stage = update.new_stage
        else:
            update.old_stage = current_stage

        prospect.last_contact_at = update.action_at or timezone.now()

        if commit:
            prospect.save(update_fields=["stage", "last_contact_at", "updated_at"])
            update.save()

        return update


class ClientMinimalForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            "entity_type",
            "name",
            "organization",
            "registration_identifier",
            "client_type",
        ]
        widgets = {
            "entity_type": forms.Select(attrs=_bs("form-select")),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "organization": forms.TextInput(attrs={"class": "form-control"}),
            "registration_identifier": forms.TextInput(attrs={"class": "form-control"}),  # 🔑
            "client_type": forms.Select(attrs={"class": "form-select"}),
        }


class ClientBusinessForm(forms.ModelForm):
    """
    Business Profile form used in onboarding / profile UI.
    """

    # ----------------------------
    # CITY DROPDOWNS (KEY FIX)
    # ----------------------------
    city = forms.ChoiceField(
        choices=GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="City",
    )

    delivery_city = forms.ChoiceField(
        choices=GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Delivery City",
    )

    class Meta:
        model = Client
        fields = [
            # --- Identity & Contact ---
            "entity_type",
            "name",
            "organization",
            "contact_person",
            "email",
            "phone",
            "whatsapp",
            "client_type",
            "client_size_tier",

            # --- Business Address ---
            "address_line1",
            "address_line2",
            "suburb",
            "city",
            "province",
            "postal_code",

            # --- Delivery Address ---
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_suburb",
            "delivery_city",
            "delivery_province",
            "delivery_postal_code",
            "delivery_lat",
            "delivery_lng",

            # --- Compliance / Commercial ---
            "vat_number",
            "registration_identifier",
            "price_type",
            "estimated_weekly_spend",
        ]

        widgets = {
            # Text inputs
            "entity_type": forms.Select(attrs=_bs("form-select")),
            "name": forms.TextInput(attrs=_bs()),
            "organization": forms.TextInput(attrs=_bs()),
            "contact_person": forms.TextInput(attrs=_bs()),
            "email": forms.EmailInput(attrs=_bs()),
            "phone": forms.TextInput(attrs=_bs()),
            "whatsapp": forms.TextInput(attrs=_bs()),

            "address_line1": forms.TextInput(attrs=_bs()),
            "address_line2": forms.TextInput(attrs=_bs()),
            "suburb": forms.TextInput(attrs=_bs()),
            "postal_code": forms.TextInput(attrs=_bs()),

            "delivery_address_line1": forms.TextInput(attrs=_bs()),
            "delivery_address_line2": forms.TextInput(attrs=_bs()),
            "delivery_suburb": forms.TextInput(attrs=_bs()),
            "delivery_postal_code": forms.TextInput(attrs=_bs()),

            # Selects
            "province": forms.Select(attrs=_bs("form-select")),
            "delivery_province": forms.Select(attrs=_bs("form-select")),
            "client_type": forms.Select(attrs=_bs("form-select")),
            "client_size_tier": forms.Select(attrs=_bs("form-select")),
            "price_type": forms.Select(attrs=_bs("form-select")),

            # Numbers
            "estimated_weekly_spend": forms.NumberInput(
                attrs={**_bs(), "step": "0.01", "min": "0"}
            ),
        }

    # ----------------------------
    # INIT
    # ----------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Helpful placeholders
        self.fields["email"].widget.attrs.setdefault("placeholder", "name@example.com")
        self.fields["phone"].widget.attrs.setdefault("placeholder", "+27 82 123 4567")
        self.fields["whatsapp"].widget.attrs.setdefault("placeholder", "+27 82 123 4567")

    # ----------------------------
    # VALIDATION
    # ----------------------------
    def clean(self):
        cleaned = super().clean()

        # Require at least name or organization
        if not cleaned.get("name") and not cleaned.get("organization"):
            raise ValidationError(
                "Please provide at least a Name or an Organization."
            )

        # Guard against negative spend
        spend = cleaned.get("estimated_weekly_spend")
        if spend is not None and spend < Decimal("0"):
            self.add_error(
                "estimated_weekly_spend",
                "Estimated weekly spend cannot be negative.",
            )

        return cleaned
    


class ClientEditForm(forms.ModelForm):
    """
    Staff-facing Client edit form.
    Full coverage of Client model including delivery geo.
    """

    # ----------------------------
    # ADDRESS DROPDOWNS
    # ----------------------------
    city = forms.ChoiceField(
        choices=GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="City",
    )

    delivery_city = forms.ChoiceField(
        choices=GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Delivery City",
    )

    delivery_province = forms.ChoiceField(
        choices=Client.PROVINCES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Delivery Province",
    )

    # ----------------------------
    # META
    # ----------------------------
    class Meta:
        model = Client
        fields = [
            # Identity
            "entity_type",
            "name",
            "organization",
            "client_type",
            "client_size_tier",

            # Contact
            "contact_person",
            "email",
            "phone",
            "whatsapp",

            # Business address
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

            # Delivery geo
            "delivery_lat",
            "delivery_lng",

            # Compliance
            "vat_number",
            "registration_identifier",

            # Commercial
            "price_type",
            "estimated_weekly_spend",

            # Categorisation
            "categories",

            # Status & credit
            "status",
            "account_type",
            "credit_status",

            # Notes
            "notes",
        ]

        widgets = {
            # Text
            "entity_type": forms.Select(attrs=_bs("form-select")),
            "name": forms.TextInput(attrs=_bs()),
            "organization": forms.TextInput(attrs=_bs()),
            "contact_person": forms.TextInput(attrs=_bs()),
            "email": forms.EmailInput(attrs=_bs()),
            "phone": forms.TextInput(attrs=_bs()),
            "whatsapp": forms.TextInput(attrs=_bs()),

            "address_line1": forms.TextInput(attrs=_bs()),
            "address_line2": forms.TextInput(attrs=_bs()),
            "suburb": forms.TextInput(attrs=_bs()),
            "postal_code": forms.TextInput(attrs=_bs()),
            "country": forms.TextInput(attrs=_bs()),

            "delivery_address_line1": forms.TextInput(attrs=_bs()),
            "delivery_address_line2": forms.TextInput(attrs=_bs()),
            "delivery_suburb": forms.TextInput(attrs=_bs()),
            "delivery_postal_code": forms.TextInput(attrs=_bs()),
            "delivery_country": forms.TextInput(attrs=_bs()),

            # Selects
            "province": forms.Select(attrs=_bs("form-select")),
            "client_type": forms.Select(attrs=_bs("form-select")),
            "client_size_tier": forms.Select(attrs=_bs("form-select")),
            "price_type": forms.Select(attrs=_bs("form-select")),
            "status": forms.Select(attrs=_bs("form-select")),
            "account_type": forms.Select(attrs=_bs("form-select")),
            "credit_status": forms.Select(attrs=_bs("form-select")),

            # Numbers
            "estimated_weekly_spend": forms.NumberInput(
                attrs={**_bs(), "step": "0.01", "min": "0"}
            ),

            # Geo (hidden but editable by JS/maps later)
            "delivery_lat": forms.NumberInput(
                attrs={**_bs(), "step": "0.000001"}
            ),
            "delivery_lng": forms.NumberInput(
                attrs={**_bs(), "step": "0.000001"}
            ),

            # Notes
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),

            # Categories
            "categories": forms.SelectMultiple(
                attrs={"class": "form-select", "size": 6}
            ),
        }

    # ----------------------------
    # INIT
    # ----------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Active categories only
        self.fields["categories"].queryset = (
            Category.objects.filter(is_active=True).order_by("name")
        )

        # Defaults
        self.fields["country"].initial = "South Africa"
        self.fields["delivery_country"].initial = "South Africa"

        # Placeholders
        self.fields["email"].widget.attrs.setdefault("placeholder", "name@example.com")
        self.fields["phone"].widget.attrs.setdefault("placeholder", "+27 82 123 4567")
        self.fields["whatsapp"].widget.attrs.setdefault("placeholder", "+27 82 123 4567")

    # ----------------------------
    # VALIDATION
    # ----------------------------
    def clean(self):
        cleaned = super().clean()

        # Require at least name or organization
        if not cleaned.get("name") and not cleaned.get("organization"):
            raise ValidationError(
                "Please provide at least a Name or an Organization."
            )

        # Credit logic safety
        if cleaned.get("credit_status") == "ACTIVE":
            cleaned["account_type"] = "CREDIT"

        # Spend sanity
        spend = cleaned.get("estimated_weekly_spend")
        if spend is not None and spend < Decimal("0"):
            self.add_error(
                "estimated_weekly_spend",
                "Estimated weekly spend cannot be negative."
            )

        return cleaned
    


class ClientComplianceForm(forms.ModelForm):
    """
    Staff-facing compliance editor.
    Only allows editing of vetting_status and notes.
    """

    class Meta:
        model = ClientCompliance
        fields = [
            "vetting_status",
            "notes",
        ]

        widgets = {
            "vetting_status": forms.Select(
                attrs={"class": "form-select"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Add compliance notes (will be appended)",
                }
            ),
        }

    def save(self, commit=True, user=None):
        """
        - Always updates vetted_by + vetted_at when saved
        - Appends notes instead of overwriting
        """
        instance = super().save(commit=False)

        # --- audit fields ---
        instance.vetted_at = timezone.now()
        if user:
            instance.vetted_by = user

        # --- append notes ---
        if self.cleaned_data.get("notes"):
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
            username = user.get_full_name() if user else "System"

            new_entry = f"[{timestamp}] {username}\n{self.cleaned_data['notes']}\n\n"

            instance.notes = new_entry + (instance.notes or "")

        if commit:
            instance.save()

        return instance
    
class ClientComplianceDocumentForm(forms.ModelForm):
    """
    Upload / edit a single compliance document.
    """

    class Meta:
        model = ClientComplianceDocument
        fields = [
            "document_type",
            "file",
            "notes",
        ]

        widgets = {
            "document_type": forms.Select(attrs=_bs("form-select")),
            "file": forms.ClearableFileInput(attrs=_bs()),
            "notes": forms.TextInput(
                attrs={
                    **_bs(),
                    "placeholder": "Optional note about this document",
                }
            ),
        }

    def clean_file(self):
        file = self.cleaned_data.get("file")

        if file:
            max_size_mb = 10
            if file.size > max_size_mb * 1024 * 1024:
                raise ValidationError(
                    f"File size must be under {max_size_mb}MB."
                )

        return file




class ClientComplianceDocumentStatusForm(forms.ModelForm):
    """
    Staff-only form to review a single compliance document.
    """

    class Meta:
        model = ClientComplianceDocument
        fields = ["status", "notes"]

        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Optional review notes",
                }
            ),
        }

