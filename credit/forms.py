from decimal import Decimal
from django import forms
from clients.models import Client
from credit.models import Funder, FunderMember, FunderAllocation, FunderMovement
from credit.models import CreditAccount
from django.forms import inlineformset_factory


class CreditEditForm(forms.Form):
    funder = forms.ModelChoiceField(
        queryset=Funder.objects.order_by("name"),
        required=False,
        empty_label="— None —",
        label="Funder (optional)",
    )

    account_type = forms.ChoiceField(
        choices=Client.ACCOUNT_TYPES,
        label="Account Type",
    )

    credit_status = forms.ChoiceField(
        choices=Client.CREDIT_STATUS,
        label="Credit Status",
    )

    # ✅ NEW
    payment_term = forms.ChoiceField(
        choices=CreditAccount.TERM_CHOICES,
        label="Payment Term",
    )

    # ✅ NEW
    credit_deposit_pct = forms.ChoiceField(
        choices=CreditAccount.DEPOSIT_CHOICES,
        label="Deposit Required (%)",
    )

    credit_limit = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        label="Credit Limit (R)",
    )

    note = forms.CharField(
        label="Change Note (optional)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Bootstrap styling (unchanged)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})
            else:
                classes = field.widget.attrs.get("class", "")
                field.widget.attrs.update(
                    {"class": (classes + " form-control").strip()}
                )


class FunderForm(forms.ModelForm):

    class Meta:
        model = Funder
        fields = [
            "name",
            "weekly_rate_pct",
            "balance",
        ]

        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Funder name",
            }),

            "weekly_rate_pct": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "placeholder": "Weekly rate %",
            }),

            "balance": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "placeholder": "Initial fund amount",
            }),
        }

class FunderAllocationForm(forms.ModelForm):

    class Meta:
        model = FunderAllocation
        fields = ["client", "amount"]

        widgets = {
            "client": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01"
            }),
        }


class FunderMemberForm(forms.ModelForm):

    class Meta:
        model = FunderMember
        fields = ["user", "role", "is_active"]

        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }



from django.forms import inlineformset_factory


FunderMemberFormSet = inlineformset_factory(
    Funder,
    FunderMember,
    form=FunderMemberForm,
    extra=1,
    can_delete=True
)

FunderAllocationFormSet = inlineformset_factory(
    Funder,
    FunderAllocation,
    form=FunderAllocationForm,
    extra=1,
    can_delete=True
)




class FunderMovementForm(forms.ModelForm):

    class Meta:
        model = FunderMovement
        fields = [
            "kind",
            "amount",
            "reference",
            "note",
        ]

        widgets = {
            "kind": forms.Select(attrs={
                "class": "form-select"
            }),

            "amount": forms.NumberInput(attrs={
                "class": "form-control",
                "step": "0.01",
                "placeholder": "Amount"
            }),

            "reference": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Bank reference / transfer ref"
            }),

            "note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Optional notes"
            }),
        }
