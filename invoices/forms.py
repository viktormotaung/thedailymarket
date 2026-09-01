from django import forms
from invoices.models import MonthlyTarget

class MonthlyTargetForm(forms.ModelForm):
    class Meta:
        model = MonthlyTarget
        fields = ["month", "year", "quarter", "territory", "monthly_target"]

        widgets = {
            "month": forms.Select(attrs={"class": "form-select"}),
            "year": forms.Select(attrs={"class": "form-select"}),
            "quarter": forms.Select(attrs={"class": "form-select"}),
            "territory": forms.Select(attrs={"class": "form-select"}),
            "monthly_target": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Enter target amount"
            }),
        }