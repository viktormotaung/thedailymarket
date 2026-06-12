from django import forms
from .models import CustomerProfile
from django.contrib.auth import get_user_model
from .models import (
    SalesRepProfile,
    SalesRole,
    SalesOperator,
    StaffProfile,
    DriverProfile,
)


class PersonalProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = [
            "display_name",
            "phone",
        ]

        widgets = {
            "display_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "How we should address you",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. 082 123 4567",
            }),
        }







User = get_user_model()


class SalesRepProfileForm(forms.ModelForm):
    class Meta:
        model = SalesRepProfile

        fields = [
            "status",
            "sales_operator",
            "base_commission_pct",
            "bonus_commission_pct",
            "department",
            "roles",
            "supervisor",
            "notes",
        ]

        widgets = {
            "status": forms.Select(attrs={
                "class": "form-select",
            }),
            "sales_operator": forms.Select(attrs={
                "class": "form-select",
            }),
            "base_commission_pct": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
            }),
            "bonus_commission_pct": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
            }),
            "department": forms.TextInput(attrs={
                "class": "form-control",
                "readonly": "readonly",
            }),
            "roles": forms.CheckboxSelectMultiple(),
            "supervisor": forms.Select(attrs={
                "class": "form-select",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["department"].initial = "SALES"

        self.fields["sales_operator"].queryset = (
            SalesOperator.objects
            .filter(is_active=True)
            .order_by("name")
        )

        self.fields["roles"].queryset = (
            SalesRole.objects
            .all()
            .order_by("name")
        )

        self.fields["supervisor"].queryset = (
            User.objects
            .filter(is_staff=True)
            .order_by("first_name", "last_name", "username")
        )

        self.fields["sales_operator"].required = False
        self.fields["roles"].required = False
        self.fields["supervisor"].required = False
        self.fields["notes"].required = False

    def clean_department(self):
        return "SALES"
    


class DriverProfileForm(forms.ModelForm):
    class Meta:
        model = DriverProfile

        fields = [
            "status",
            "notes",
        ]

        widgets = {
            "status": forms.Select(attrs={
                "class": "form-select",
            }),

            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Internal notes...",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["notes"].required = False