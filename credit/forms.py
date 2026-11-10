from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory

from clients.models import Client
from credit.models import (
    CreditAccount,
    Funder,
    FunderAllocation,
    FunderMember,
    FunderMovement,
)


class CreditEditForm(forms.Form):
    """
    Staff form for maintaining a client's TradeAssist buying-power settings.

    Field names are intentionally retained for compatibility with the existing
    credit_edit view and database models.
    """

    funder = forms.ModelChoiceField(
        queryset=Funder.objects.order_by("name"),
        required=False,
        empty_label="— None —",
        label="Funding source (optional)",
    )

    account_type = forms.ChoiceField(
        choices=Client.ACCOUNT_TYPES,
        label="Buying-power arrangement",
    )

    # Buying-power status is owned by CreditAccount, not Client.
    # Keep the existing field name for compatibility with credit_edit views.
    credit_status = forms.ChoiceField(
        choices=CreditAccount.STATUS_CHOICES,
        label="Buying-power status",
    )

    payment_term = forms.ChoiceField(
        choices=CreditAccount.TERM_CHOICES,
        label="Settlement term",
    )

    credit_deposit_pct = forms.ChoiceField(
        choices=CreditAccount.DEPOSIT_CHOICES,
        label="Upfront contribution (%)",
    )

    credit_limit = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        label="Buying-power limit (R)",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "0",
                "step": "0.01",
                "inputmode": "decimal",
            }
        ),
    )

    note = forms.CharField(
        label="Change note (optional)",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif not isinstance(field.widget, forms.CheckboxInput):
                existing = field.widget.attrs.get("class", "")
                field.widget.attrs["class"] = (
                    f"{existing} form-control".strip()
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
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Funder name",
                }
            ),
            "weekly_rate_pct": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "max": "0",
                    "readonly": "readonly",
                    "value": "0",
                }
            ),
            "balance": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Initial fund amount",
                }
            ),
        }

    def clean_weekly_rate_pct(self):
        """
        TradeAssist does not charge interest or a weekly rate.

        Keep the legacy database field for compatibility, but reject any
        non-zero value submitted through this form.
        """
        rate = self.cleaned_data.get("weekly_rate_pct")
        if rate is None:
            return Decimal("0.00")

        if Decimal(rate) != Decimal("0.00"):
            raise forms.ValidationError(
                "TradeAssist funders must have a 0% weekly rate. "
                "Interest and weekly charges are not permitted."
            )

        return Decimal("0.00")


class FunderAllocationForm(forms.ModelForm):
    class Meta:
        model = FunderAllocation
        fields = ["client", "amount"]
        widgets = {
            "client": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),
        }


class FunderMemberForm(forms.ModelForm):
    class Meta:
        model = FunderMember
        fields = ["user", "role", "is_active"]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }


FunderMemberFormSet = inlineformset_factory(
    Funder,
    FunderMember,
    form=FunderMemberForm,
    extra=1,
    can_delete=True,
)


FunderAllocationFormSet = inlineformset_factory(
    Funder,
    FunderAllocation,
    form=FunderAllocationForm,
    extra=1,
    can_delete=True,
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
            "kind": forms.Select(
                attrs={"class": "form-select"}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0.01",
                    "placeholder": "Amount",
                }
            ),
            "reference": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Bank reference / transfer ref",
                }
            ),
            "note": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional notes",
                }
            ),
        }
