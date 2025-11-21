# C:\Seshibo Daily Market\seshibo_site\staff_portal\forms.py
from django import forms
from django.contrib.auth import get_user_model

from profiles.models import StaffProfile, CustomerProfile
from clients.models import Client

User = get_user_model()

class StaffProfileForm(forms.ModelForm):
    create_sales_profile = forms.BooleanField(
        label="Create / Link Sales Profile",
        required=False,
        help_text="If checked, a SalesRepProfile will be created or linked for this staff member.",
    )

    class Meta:
        model = StaffProfile
        fields = ["job_title", "phone", "status", "notes", "create_sales_profile"]

    def save(self, commit=True):
        obj: StaffProfile = super().save(commit=False)
        if commit:
            obj.save()

            # Create/link SalesRepProfile if requested
            if self.cleaned_data.get("create_sales_profile"):
                from .models import SalesRepProfile
                SalesRepProfile.objects.get_or_create(
                    user=obj.user,
                    defaults={
                        "department": "sales",
                        "status": obj.status,
                        "notes": obj.notes,
                    },
                )

        return obj


class UserBasicsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "is_active"]
        # If you want to show username as read-only:
        # widgets = {"username": forms.TextInput(attrs={"readonly": "readonly"})}


class CustomerProfileEditForm(forms.ModelForm):
    """
    Edit form for CustomerProfile.
    If profile_type == BUSINESS, client is required.
    """

    # Limit/organize clients. If you have a status field on Client, filter accordingly.
    client = forms.ModelChoiceField(
        queryset=Client.objects.all().order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="— Select client —",
        label="Linked Client (Business only)",
        help_text="Required when Profile Type is Business.",
    )

    class Meta:
        model = CustomerProfile
        fields = [
            "profile_type",
            "status",
            "display_name",
            "phone",
            "client",
            "company_name",
            "tax_number",
        ]
        widgets = {
            "profile_type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),  # style it
            "display_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "tax_number": forms.TextInput(attrs={"class": "form-control"}),
        }
        help_texts = {
            "display_name": "How we should address the customer on documents/communication.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Optional: If your Client model has an "ACTIVE" concept, filter here
        # self.fields["client"].queryset = Client.objects.filter(status="ACTIVE").order_by("name")

        # If instance is BUSINESS, show client as required in the UI (HTML level)
        profile_type_val = (
            self.data.get(self.add_prefix("profile_type"))
            if self.is_bound
            else (self.instance.profile_type if self.instance and self.instance.pk else None)
        )
        if profile_type_val == "BUSINESS":
            self.fields["client"].required = True

        # Optional: nicer labels for statuses (uses model choices by default).
        # If you want custom order, you can reorder here:
        # self.fields["status"].choices = [
        #     ("pending", "Pending"),
        #     ("active", "Active"),
        #     ("inactive", "Inactive"),
        # ]

    def clean(self):
        cleaned = super().clean()
        profile_type = cleaned.get("profile_type")
        client = cleaned.get("client")
        if profile_type == "BUSINESS" and not client:
            self.add_error("client", "Client is required when profile type is Business.")
        return cleaned