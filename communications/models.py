
from django.db import models
from django.conf import settings


class CommunicationLog(models.Model):

    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_EMAIL = "email"
    CHANNEL_SMS = "sms"

    CHANNEL_CHOICES = [
        (CHANNEL_WHATSAPP, "WhatsApp"),
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_SMS, "SMS"),
    ]

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_DELIVERED = "delivered"
    STATUS_READ = "read"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_READ, "Read"),
    ]

    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    recipient_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    recipient_contact = models.CharField(
        max_length=255,
    )

    subject = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    message = models.TextField(
        blank=True,
        null=True,
    )

    related_model = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    related_object_id = models.PositiveIntegerField(
        blank=True,
        null=True,
    )

    provider = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Example: Meta WhatsApp Cloud API, Postmark, SMS provider",
    )

    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    provider_response = models.JSONField(
        blank=True,
        null=True,
    )

    error_message = models.TextField(
        blank=True,
        null=True,
    )

    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="sent_communications",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    sent_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    delivered_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    read_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_channel_display()} to {self.recipient_contact} - {self.get_status_display()}"
