from decimal import Decimal
from django import forms
from credit.models import FunderMovement

class FunderMovementForm(forms.ModelForm):
    class Meta:
        model = FunderMovement
        fields = ["amount", "reference", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "reference": forms.TextInput(attrs={"placeholder": "e.g. ABSA deposit #123"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_amount(self):
        amt = self.cleaned_data.get("amount") or Decimal("0.00")
        if amt <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amt
