# transactions/forms.py
from django import forms
from .models import Transaction  # <-- don't import Invoice from here

class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ["client", "invoice", "transaction_type", "amount", "reference", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, client_id=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Tidy dropdowns
        self.fields["client"].queryset = (
            self.fields["client"].queryset.order_by("name")
        )

        inv_qs = (
            self.fields["invoice"]
            .queryset.select_related("client", "order")
            .order_by("-created_at")
        )
        if client_id:
            inv_qs = inv_qs.filter(client_id=client_id)

        self.fields["invoice"].queryset = inv_qs

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        invoice = cleaned.get("invoice")
        if invoice and client and invoice.client_id != client.id:
            self.add_error("invoice", "Selected invoice does not belong to the chosen client.")
        return cleaned
