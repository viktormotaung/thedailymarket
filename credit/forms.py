from decimal import Decimal
from django import forms
from clients.models import Client
from credit.models import Funder
from credit.models import CreditAccount


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