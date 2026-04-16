from django.db import models
from django.conf import settings
from decimal import Decimal

class Payment(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    PROVIDER_CHOICES = [
        ("ozow", "Ozow"),
    ]

    reference = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="ozow")

    client = models.ForeignKey("clients.Client", on_delete=models.SET_NULL, null=True, blank=True)
    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True)

    ozow_transaction_id = models.CharField(max_length=255, blank=True, null=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        should_apply_invoice_payment = False

        if self.pk:
            old = Payment.objects.filter(pk=self.pk).first()
            if old and old.status != "success" and self.status == "success":
                should_apply_invoice_payment = True
        else:
            if self.status == "success":
                should_apply_invoice_payment = True

        super().save(*args, **kwargs)

        # Trigger the same invoice payment flow when this payment becomes successful
        if should_apply_invoice_payment and self.invoice:
            self.invoice.record_payment(
                amount=self.amount,
                reference=self.reference,
                note=f"{self.provider.upper()} payment received",
                when=self.paid_at,
            )

    def __str__(self):
        return f"{self.reference} - {self.amount} - {self.status}"