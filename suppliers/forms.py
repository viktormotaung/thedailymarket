# suppliers/forms.py
from django import forms
from .models import Supplier

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = "__all__"
        widgets = {
            # --- Identity / links ---
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "categories": forms.SelectMultiple(attrs={"class": "form-select"}),

            # --- Flags ---
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            # Render Boolean as a dropdown Yes/No (default False = No)
            "visible": forms.Select(
                choices=((True, "Yes"), (False, "No")),
                attrs={"class": "form-select"}
            ),

            # --- Ownership / terms ---
            "account_manager": forms.Select(attrs={"class": "form-select"}),
            "payment_terms": forms.Select(attrs={"class": "form-select"}),

            # --- Contact ---
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "whatsapp": forms.TextInput(attrs={"class": "form-control"}),
            "website": forms.URLInput(attrs={"class": "form-control"}),

            # --- Address ---
            "address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "province": forms.TextInput(attrs={"class": "form-control"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),

            # --- Compliance ---
            "vat_number": forms.TextInput(attrs={"class": "form-control"}),
            "company_reg_number": forms.TextInput(attrs={"class": "form-control"}),

            # --- Files ---
            # Logo/image upload
            "logo": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
            # Contract file upload (allow common doc types)
            "contract_file": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": ".pdf,.doc,.docx,.png,.jpg,.jpeg"}
            ),

            # --- Notes ---
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
