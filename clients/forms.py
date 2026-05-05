# C:\Seshibo Daily Market\seshibo_site\clients\forms.py
from __future__ import annotations
from .models import ProspectOperatingHours
from decimal import Decimal
from .models import ClientOperatingHours
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




class ClientForm(forms.ModelForm):
    """
    Main create / edit form for Clients.
    Fully aligned with original view version.
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

    class Meta:
        model = Client
        fields = [
            # Identity & Ownership
            "entity_type",
            "name",
            "organization",
            "client_type",
            "client_size_tier",
            "account_manager",
            "price_type",

            # Territory
            "area",

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

            # Preferred Delivery Slots
            "preferred_delivery_slot_1",
            "preferred_delivery_slot_2",
            "preferred_delivery_slot_3",

            # Compliance
            "registration_identifier",
            "vat_number",

            # Commercial
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
            # Text inputs
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

            "delivery_lat": forms.NumberInput(attrs={**_bs(), "step": "0.000001"}),
            "delivery_lng": forms.NumberInput(attrs={**_bs(), "step": "0.000001"}),

            "registration_identifier": forms.TextInput(attrs=_bs()),
            "vat_number": forms.TextInput(attrs=_bs()),

            "estimated_weekly_spend": forms.NumberInput(
                attrs={**_bs(), "step": "0.01", "min": "0"}
            ),

            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),

            # Selects
            "entity_type": forms.Select(attrs=_bs("form-select")),
            "client_type": forms.Select(attrs=_bs("form-select")),
            "client_size_tier": forms.Select(attrs=_bs("form-select")),
            "account_manager": forms.Select(attrs=_bs("form-select")),
            "province": forms.Select(attrs=_bs("form-select")),
            "status": forms.Select(attrs=_bs("form-select")),
            "account_type": forms.Select(attrs=_bs("form-select")),
            "credit_status": forms.Select(attrs=_bs("form-select")),
            "price_type": forms.Select(attrs=_bs("form-select")),
            "area": forms.Select(attrs=_bs("form-select")),

            "preferred_delivery_slot_1": forms.Select(attrs=_bs("form-select")),
            "preferred_delivery_slot_2": forms.Select(attrs=_bs("form-select")),
            "preferred_delivery_slot_3": forms.Select(attrs=_bs("form-select")),

            "categories": forms.SelectMultiple(
                attrs={"class": "form-select", "size": 6}
            ),
        }

    # ----------------------------
    # INIT
    # ----------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["categories"].queryset = (
            Category.objects.filter(is_active=True).order_by("name")
        )

        if not self.instance.pk and not self.initial.get("price_type"):
            self.fields["price_type"].initial = "Retail"

        self.fields["country"].initial = "South Africa"
        self.fields["delivery_country"].initial = "South Africa"

        # ----------------------------
        # OPERATING HOURS
        # ----------------------------
        for day_code, day_label in ClientOperatingHours.DAY_CHOICES:

            self.fields[f"{day_code}_is_closed"] = forms.BooleanField(
                required=False,
                label=f"{day_label} Closed",
                widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
            )

            self.fields[f"{day_code}_open"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(
                    attrs={"class": "form-control", "type": "time"}
                )
            )

            self.fields[f"{day_code}_close"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(
                    attrs={"class": "form-control", "type": "time"}
                )
            )

            if self.instance.pk:
                hours = self.instance.operating_hours.filter(day=day_code).first()
                if hours:
                    self.fields[f"{day_code}_is_closed"].initial = hours.is_closed
                    self.fields[f"{day_code}_open"].initial = hours.open_time
                    self.fields[f"{day_code}_close"].initial = hours.close_time

    # ----------------------------
    # CLEAN
    # ----------------------------
    def clean(self):
        cleaned = super().clean()

        if not cleaned.get("name") and not cleaned.get("organization"):
            raise ValidationError(
                "Please provide at least a Name or an Organization."
            )

        spend = cleaned.get("estimated_weekly_spend")
        if spend is not None and spend < Decimal("0"):
            self.add_error(
                "estimated_weekly_spend",
                "Estimated weekly spend cannot be negative."
            )

        # Prevent duplicate preferred delivery slots
        slots = [
            cleaned.get("preferred_delivery_slot_1"),
            cleaned.get("preferred_delivery_slot_2"),
            cleaned.get("preferred_delivery_slot_3"),
        ]
        slots = [s for s in slots if s]

        if len(slots) != len(set(slots)):
            raise ValidationError("Preferred delivery slots must be unique.")

        for day_code, day_label in ClientOperatingHours.DAY_CHOICES:
            is_closed = cleaned.get(f"{day_code}_is_closed")
            open_time = cleaned.get(f"{day_code}_open")
            close_time = cleaned.get(f"{day_code}_close")

            if not bool(is_closed):
                if not open_time or not close_time:
                    self.add_error(
                        f"{day_code}_open",
                        f"{day_label}: Opening and closing times required unless closed."
                    )
                elif close_time <= open_time:
                    self.add_error(
                        f"{day_code}_close",
                        f"{day_label}: Closing time must be after opening time."
                    )

        return cleaned

    # ----------------------------
    # SAVE
    # ----------------------------
    def save(self, commit=True):
        client = super().save(commit=False)

        if commit:
            client.save()

            for day_code, _ in ClientOperatingHours.DAY_CHOICES:
                is_closed = self.cleaned_data.get(f"{day_code}_is_closed")
                open_time = self.cleaned_data.get(f"{day_code}_open")
                close_time = self.cleaned_data.get(f"{day_code}_close")

                hours, _ = ClientOperatingHours.objects.get_or_create(
                    client=client,
                    day=day_code,
                )

                hours.is_closed = bool(is_closed)
                hours.open_time = None if is_closed else open_time
                hours.close_time = None if is_closed else close_time
                hours.save()

        return client

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

            # Territory
            "area",

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
            "area": forms.Select(attrs=_bs("form-select")),

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

        for day_code, day_label in ProspectOperatingHours.DAY_CHOICES:
            self.fields[f"{day_code}_is_closed"] = forms.BooleanField(
                required=False,
                label=f"{day_label} Closed",
                widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
            )

            self.fields[f"{day_code}_open"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"})
            )

            self.fields[f"{day_code}_close"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"})
            )

            if self.instance.pk:
                hours = self.instance.operating_hours.filter(day=day_code).first()
                if hours:
                    self.fields[f"{day_code}_is_closed"].initial = hours.is_closed
                    self.fields[f"{day_code}_open"].initial = hours.open_time
                    self.fields[f"{day_code}_close"].initial = hours.close_time

    def clean(self):
        cleaned = super().clean()

        # Require at least name or organization
        if not cleaned.get("name") and not cleaned.get("organization"):
            raise ValidationError(
                "Please provide at least a Name or an Organization."
            )

        

        # Spend sanity
        spend = cleaned.get("estimated_weekly_spend")
        if spend is not None and spend < Decimal("0"):
            self.add_error(
                "estimated_weekly_spend",
                "Estimated weekly spend cannot be negative."
            )

        # 🔥 WEEKDAY VALIDATION
        for day_code, day_label in ProspectOperatingHours.DAY_CHOICES:
            is_closed = cleaned.get(f"{day_code}_is_closed")
            open_time = cleaned.get(f"{day_code}_open")
            close_time = cleaned.get(f"{day_code}_close")

            if not bool(is_closed):
                if not open_time or not close_time:
                    self.add_error(
                        f"{day_code}_open",
                        f"{day_label}: Opening and closing times are required unless closed."
                    )
                elif close_time <= open_time:
                    self.add_error(
                        f"{day_code}_close",
                        f"{day_label}: Closing time must be after opening time."
                    )

        return cleaned
    
    def save(self, commit=True):
        prospect = super().save(commit=False)

        if commit:
            prospect.save()

            for day_code, _ in ProspectOperatingHours.DAY_CHOICES:
                is_closed = self.cleaned_data.get(f"{day_code}_is_closed")
                open_time = self.cleaned_data.get(f"{day_code}_open")
                close_time = self.cleaned_data.get(f"{day_code}_close")

                hours, _ = ProspectOperatingHours.objects.get_or_create(
                    prospect=prospect,
                    day=day_code,
                )

                hours.is_closed = bool(is_closed)
                hours.open_time = None if is_closed else open_time
                hours.close_time = None if is_closed else close_time
                hours.save()

        return prospect

    
class ClientOperationsForm(forms.Form):

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = client

        for day_code, day_label in ClientOperatingHours.DAY_CHOICES:

            self.fields[f"{day_code}_is_closed"] = forms.BooleanField(
                required=False,
                label=f"{day_label} Closed",
                widget=forms.CheckboxInput(
                    attrs={"class": "form-check-input"}
                )
            )

            self.fields[f"{day_code}_open"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(
                    attrs={
                        "class": "form-control",
                        "type": "time",
                    }
                )
            )

            self.fields[f"{day_code}_close"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(
                    attrs={
                        "class": "form-control",
                        "type": "time",
                    }
                )
            )

            if client:
                hours = client.operating_hours.filter(day=day_code).first()

                if hours:
                    self.fields[f"{day_code}_is_closed"].initial = hours.is_closed
                    self.fields[f"{day_code}_open"].initial = hours.open_time
                    self.fields[f"{day_code}_close"].initial = hours.close_time

    def clean(self):
        cleaned = super().clean()

        for day_code, day_label in ClientOperatingHours.DAY_CHOICES:

            is_closed = cleaned.get(f"{day_code}_is_closed")
            open_time = cleaned.get(f"{day_code}_open")
            close_time = cleaned.get(f"{day_code}_close")

            if not is_closed:

                if not open_time or not close_time:
                    raise forms.ValidationError(
                        f"{day_label}: Opening and closing times required unless closed."
                    )

                if close_time <= open_time:
                    raise forms.ValidationError(
                        f"{day_label}: Closing time must be after opening time."
                    )

        return cleaned

    def save(self):
        for day_code, _ in ClientOperatingHours.DAY_CHOICES:

            is_closed = self.cleaned_data.get(f"{day_code}_is_closed")
            open_time = self.cleaned_data.get(f"{day_code}_open")
            close_time = self.cleaned_data.get(f"{day_code}_close")

            hours, _ = ClientOperatingHours.objects.get_or_create(
                client=self.client,
                day=day_code,
            )

            hours.is_closed = bool(is_closed)
            hours.open_time = None if is_closed else open_time
            hours.close_time = None if is_closed else close_time

            hours.save()


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

    # ----------------------------
    # NEW: DELIVERY PROVINCE + COUNTRY
    # ----------------------------
    delivery_country = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs=_bs()),
        label="Delivery Country",
    )

    # ----------------------------
    # NEW: DELIVERY SLOTS
    # ----------------------------
    preferred_delivery_slot_1 = forms.ChoiceField(
        choices=Client.DELIVERY_SLOT_CHOICES,
        required=False,
        widget=forms.Select(attrs=_bs("form-select")),
        label="Preferred Delivery Slot (1st)",
    )

    preferred_delivery_slot_2 = forms.ChoiceField(
        choices=Client.DELIVERY_SLOT_CHOICES,
        required=False,
        widget=forms.Select(attrs=_bs("form-select")),
        label="Preferred Delivery Slot (2nd)",
    )

    preferred_delivery_slot_3 = forms.ChoiceField(
        choices=Client.DELIVERY_SLOT_CHOICES,
        required=False,
        widget=forms.Select(attrs=_bs("form-select")),
        label="Preferred Delivery Slot (3rd)",
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
            "area",  # 🔥 NEW

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
            "delivery_country",  # 🔥 NEW
            "delivery_postal_code",
            "delivery_lat",
            "delivery_lng",

            # --- Delivery Preferences ---
            "preferred_delivery_slot_1",  # 🔥 NEW
            "preferred_delivery_slot_2",  # 🔥 NEW
            "preferred_delivery_slot_3",  # 🔥 NEW

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
            "area": forms.Select(attrs=_bs("form-select")),  # 🔥 NEW

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

        # Default delivery country
        if not self.instance.pk:
            self.fields["delivery_country"].initial = "South Africa"

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
    Edits identity, contact, commercial and compliance data only.
    Operating hours handled separately.
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
            "area",

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
            "preferred_delivery_slot_1",
            "preferred_delivery_slot_2",
            "preferred_delivery_slot_3",

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
            "entity_type": forms.Select(attrs=_bs("form-select")),
            "province": forms.Select(attrs=_bs("form-select")),
            "client_type": forms.Select(attrs=_bs("form-select")),
            "client_size_tier": forms.Select(attrs=_bs("form-select")),
            "price_type": forms.Select(attrs=_bs("form-select")),
            "status": forms.Select(attrs=_bs("form-select")),
            "account_type": forms.Select(attrs=_bs("form-select")),
            "credit_status": forms.Select(attrs=_bs("form-select")),

            "estimated_weekly_spend": forms.NumberInput(
                attrs={**_bs(), "step": "0.01", "min": "0"}
            ),

            "delivery_lat": forms.NumberInput(
                attrs={**_bs(), "step": "0.000001"}
            ),
            "delivery_lng": forms.NumberInput(
                attrs={**_bs(), "step": "0.000001"}
            ),

            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "categories": forms.SelectMultiple(
                attrs={"class": "form-select", "size": 6}
            ),
        }

    # ----------------------------
    # INIT
    # ----------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Only active categories selectable
        self.fields["categories"].queryset = (
            Category.objects.filter(is_active=True).order_by("name")
        )

        # Defaults only for new clients
        if not self.instance.pk:
            self.fields["country"].initial = "South Africa"
            self.fields["delivery_country"].initial = "South Africa"

        # Helpful placeholders
        self.fields["email"].widget.attrs.setdefault("placeholder", "name@example.com")
        self.fields["phone"].widget.attrs.setdefault("placeholder", "+27 82 123 4567")
        self.fields["whatsapp"].widget.attrs.setdefault("placeholder", "+27 82 123 4567")

    # ----------------------------
    # CLEAN
    # ----------------------------
    def clean(self):
        cleaned = super().clean()

        # Require at least one identifier
        if not cleaned.get("name") and not cleaned.get("organization"):
            raise ValidationError(
                "Please provide at least a Name or an Organization."
            )

        # Auto-enforce credit account type
        if cleaned.get("credit_status") == "ACTIVE":
            cleaned["account_type"] = "CREDIT"

        # Prevent negative spend
        spend = cleaned.get("estimated_weekly_spend")
        if spend is not None and spend < Decimal("0"):
            self.add_error(
                "estimated_weekly_spend",
                "Estimated weekly spend cannot be negative."
            )

        return cleaned

    # ----------------------------
    # SAVE
    # ----------------------------
    def save(self, commit=True):
        client = super().save(commit=False)

        if commit:
            client.save()

        return client


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


class ClientOperationsForm(forms.Form):
    """
    Operating-hours-only form.

    This form does NOT edit Client fields like name, organization, address, etc.
    It only updates ClientOperatingHours rows linked to the client.
    """

    DAY_ORDER_MAP = {
        "MON": 1,
        "TUE": 2,
        "WED": 3,
        "THU": 4,
        "FRI": 5,
        "SAT": 6,
        "SUN": 7,
    }

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = instance

        for day_code, day_label in ClientOperatingHours.DAY_CHOICES:
            self.fields[f"{day_code}_is_closed"] = forms.BooleanField(
                required=False,
                label=f"{day_label} Closed",
                widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
            )

            self.fields[f"{day_code}_open"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(
                    attrs={
                        "class": "form-control",
                        "type": "time",
                    }
                ),
            )

            self.fields[f"{day_code}_close"] = forms.TimeField(
                required=False,
                widget=forms.TimeInput(
                    attrs={
                        "class": "form-control",
                        "type": "time",
                    }
                ),
            )

            if self.client and self.client.pk:
                hours = self.client.operating_hours.filter(day=day_code).first()

                if hours:
                    self.fields[f"{day_code}_is_closed"].initial = hours.is_closed
                    self.fields[f"{day_code}_open"].initial = hours.open_time
                    self.fields[f"{day_code}_close"].initial = hours.close_time

    def clean(self):
        cleaned = super().clean()

        for day_code, day_label in ClientOperatingHours.DAY_CHOICES:
            is_closed = cleaned.get(f"{day_code}_is_closed")
            open_time = cleaned.get(f"{day_code}_open")
            close_time = cleaned.get(f"{day_code}_close")

            if is_closed:
                continue

            if not open_time:
                self.add_error(
                    f"{day_code}_open",
                    f"{day_label}: Opening time is required unless closed.",
                )

            if not close_time:
                self.add_error(
                    f"{day_code}_close",
                    f"{day_label}: Closing time is required unless closed.",
                )

            if open_time and close_time and close_time <= open_time:
                self.add_error(
                    f"{day_code}_close",
                    f"{day_label}: Closing time must be after opening time.",
                )

        return cleaned

    def save(self):
        if not self.client:
            raise ValueError("ClientOperationsForm requires instance=client.")

        for day_code, _ in ClientOperatingHours.DAY_CHOICES:
            is_closed = self.cleaned_data.get(f"{day_code}_is_closed")
            open_time = self.cleaned_data.get(f"{day_code}_open")
            close_time = self.cleaned_data.get(f"{day_code}_close")

            hours, created = ClientOperatingHours.objects.get_or_create(
                client=self.client,
                day=day_code,
                defaults={
                    "day_order": self.DAY_ORDER_MAP.get(day_code),
                },
            )

            if not hours.day_order:
                hours.day_order = self.DAY_ORDER_MAP.get(day_code)

            hours.is_closed = bool(is_closed)
            hours.open_time = None if is_closed else open_time
            hours.close_time = None if is_closed else close_time
            hours.save()

        return self.client 



