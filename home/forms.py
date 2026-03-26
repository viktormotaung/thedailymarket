# your_app/forms.py
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from clients.models import Client
from profiles.models import CustomerProfile
from clients.models import GAUTENG_CITY_CHOICES


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "First name"
            }),
            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Last name"
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "Email address"
            }),
        }


class RegisterUserForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = [
            "username", "email",
            "first_name", "last_name",   # ← add these
            "password1", "password2",
        ]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),  # ←
            "last_name": forms.TextInput(attrs={"class": "form-control"}),   # ←
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({"class": "form-control"})
        self.fields["password2"].widget.attrs.update({"class": "form-control"})


class ClientFullForm(forms.ModelForm):
    # Use your Gauteng city list for a clean dropdown
    city = forms.ChoiceField(
        choices=[("", "— Select City —")] + GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    # Let users pick multiple categories
    categories = forms.ModelMultipleChoiceField(
        queryset=Client._meta.get_field("categories").remote_field.model.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select"})
    )

    class Meta:
        model = Client
        fields = [
            # Basics
            "name",
            "organization",
            "registration_identifier",  # ✅ CORRECT FIELD
            "client_type",
            "price_type",

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

            # Delivery address (optional)
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_suburb",
            "delivery_city",
            "delivery_province",
            "delivery_postal_code",
            "delivery_country",

            # Other
            "estimated_weekly_spend",
            "categories",
            "notes",
        ]

        widgets = {
            # Basics
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "organization": forms.TextInput(attrs={"class": "form-control"}),
            "registration_identifier": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Registration number or SA ID (optional)"
            }),
            "client_type": forms.Select(attrs={"class": "form-select"}),
            "price_type": forms.Select(attrs={"class": "form-select"}),

            # Contacts
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "whatsapp": forms.TextInput(attrs={"class": "form-control"}),

            # Billing/Main address
            "address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "suburb": forms.TextInput(attrs={"class": "form-control"}),
            "province": forms.Select(attrs={"class": "form-select"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),

            # Delivery address
            "delivery_address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_suburb": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_city": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_province": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_country": forms.TextInput(attrs={"class": "form-control"}),

            # Other
            "estimated_weekly_spend": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Friendly label override
        self.fields["registration_identifier"].label = "Registration number (optional)"

        # Defaults
        if not self.fields["country"].initial:
            self.fields["country"].initial = "South Africa"

        if not self.fields["delivery_country"].initial:
            self.fields["delivery_country"].initial = "South Africa"
class ClientFullForm(forms.ModelForm):
    # Use your Gauteng city list for a clean dropdown
    city = forms.ChoiceField(
        choices=[("", "— Select City —")] + GAUTENG_CITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    # Let users pick multiple categories
    categories = forms.ModelMultipleChoiceField(
        queryset=Client._meta.get_field("categories").remote_field.model.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select"})
    )

    class Meta:
        model = Client
        fields = [
            # Basics
            "name",
            "organization",
            "entity_type",  # ✅ ADDED (only change)
            "registration_identifier",
            "client_type",
            "price_type",

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

            # Delivery address (optional)
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_suburb",
            "delivery_city",
            "delivery_province",
            "delivery_postal_code",
            "delivery_country",

            # Other
            "estimated_weekly_spend",
            "categories",
            "notes",
        ]

        widgets = {
            # Basics
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "organization": forms.TextInput(attrs={"class": "form-control"}),

            "entity_type": forms.Select(attrs={"class": "form-select"}),  # ✅ ADDED

            "registration_identifier": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Registration number or SA ID (optional)"
            }),

            "client_type": forms.Select(attrs={"class": "form-select"}),
            "price_type": forms.Select(attrs={"class": "form-select"}),

            # Contacts
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "whatsapp": forms.TextInput(attrs={"class": "form-control"}),

            # Billing/Main address
            "address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "suburb": forms.TextInput(attrs={"class": "form-control"}),
            "province": forms.Select(attrs={"class": "form-select"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),

            # Delivery address
            "delivery_address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_suburb": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_city": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_province": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_country": forms.TextInput(attrs={"class": "form-control"}),

            # Other
            "estimated_weekly_spend": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Friendly label override
        self.fields["registration_identifier"].label = "Registration number (optional)"

        # ✅ Optional (nice label for entity_type)
        self.fields["entity_type"].label = "Entity type"

        # Defaults
        if not self.fields["country"].initial:
            self.fields["country"].initial = "South Africa"

        if not self.fields["delivery_country"].initial:
            self.fields["delivery_country"].initial = "South Africa"

class CustomerProfileForm(forms.ModelForm):
    """Links new User to a CustomerProfile. Allows choosing an existing Client OR creating a new one via ClientMiniForm."""
    client = forms.ModelChoiceField(
        queryset=Client.objects.all(),
        required=False,
        help_text="Select an existing client (for BUSINESS) or fill the Client tab to create one.",
        widget=forms.Select(attrs={"class": "form-select"})
    )

    class Meta:
        model = CustomerProfile
        fields = ["profile_type", "display_name", "phone", "client"]
        widgets = {
            "profile_type": forms.Select(attrs={"class": "form-select"}),
            "display_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            
        }