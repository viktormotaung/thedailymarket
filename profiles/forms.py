from django import forms
from .models import CustomerProfile

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
