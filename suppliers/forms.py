# suppliers/forms.py
from django import forms
from .models import Supplier


class SupplierForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Route coordinate labels
        self.fields["delivery_lat"].label = "Route Latitude"
        self.fields["delivery_lng"].label = "Route Longitude"

        # Route coordinate help text
        route_help = (
            "Used as the starting location when generating delivery routes. "
            "Leave blank if the supplier's location has not yet been captured."
        )

        self.fields["delivery_lat"].help_text = route_help
        self.fields["delivery_lng"].help_text = route_help

    class Meta:
        model = Supplier

        # Exclude auto / system-managed fields
        exclude = (
            "logo_cropping",
            "created_at",
            "updated_at",
        )

        widgets = {

            # --- Identity / links ---
            "code": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "name": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "categories": forms.SelectMultiple(attrs={
                "class": "form-select"
            }),

            # --- Flags ---
            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input"
            }),

            # Render Boolean as dropdown Yes/No
            "visible": forms.Select(
                choices=((True, "Yes"), (False, "No")),
                attrs={"class": "form-select"}
            ),

            # --- Ownership / terms ---
            "account_manager": forms.Select(attrs={
                "class": "form-select"
            }),
            "payment_terms": forms.Select(attrs={
                "class": "form-select"
            }),

            # --- Contact ---
            "contact_person": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control"
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "whatsapp": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "website": forms.URLInput(attrs={
                "class": "form-control"
            }),

            # --- Address ---
            "address_line1": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "address_line2": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "city": forms.TextInput(attrs={
                "class": "form-control"
            }),

            # Province (choices from model)
            "province": forms.Select(attrs={
                "class": "form-select"
            }),

            "postal_code": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "country": forms.TextInput(attrs={
                "class": "form-control"
            }),

            # --- Route Coordinates ---
            "delivery_lat": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.000001",
                "placeholder": "Latitude (e.g. -26.204103)",
            }),

            "delivery_lng": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.000001",
                "placeholder": "Longitude (e.g. 28.047305)",
            }),

            # --- Compliance ---
            "vat_number": forms.TextInput(attrs={
                "class": "form-control"
            }),
            "company_reg_number": forms.TextInput(attrs={
                "class": "form-control"
            }),

            # --- Files ---
            "logo": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*"
            }),

            "contract_file": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": ".pdf,.doc,.docx,.png,.jpg,.jpeg"
            }),

            # --- Notes ---
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4
            }),
        }

