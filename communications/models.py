from django.db import models
from django.conf import settings


class CommunicationLog(models.Model):

    # ==================================================
    # CHANNELS
    # ==================================================

    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_EMAIL = "email"
    CHANNEL_SMS = "sms"

    CHANNEL_CHOICES = [
        (CHANNEL_WHATSAPP, "WhatsApp"),
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_SMS, "SMS"),
    ]

    # ==================================================
    # STATUSES
    # ==================================================

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

    # ==================================================
    # BASIC MESSAGE INFO
    # ==================================================

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

    # ==================================================
    # RELATED OBJECT
    # Example:
    # related_model = "Invoice"
    # related_object_id = 17
    # ==================================================

    related_model = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    related_object_id = models.PositiveIntegerField(
        blank=True,
        null=True,
    )

    # ==================================================
    # PROVIDER INFO
    # ==================================================

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
        db_index=True,
    )

    provider_response = models.JSONField(
        blank=True,
        null=True,
    )

    provider_status_payload = models.JSONField(
        blank=True,
        null=True,
        help_text="Latest webhook/status payload from provider.",
    )

    error_message = models.TextField(
        blank=True,
        null=True,
    )

    # ==================================================
    # WHATSAPP-SPECIFIC TRACKING
    # ==================================================

    whatsapp_phone_number_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    whatsapp_display_phone_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )

    whatsapp_recipient_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    whatsapp_conversation_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    whatsapp_pricing_category = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    whatsapp_pricing_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    whatsapp_billable = models.BooleanField(
        blank=True,
        null=True,
    )

    # ==================================================
    # USER / TIME TRACKING
    # ==================================================

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

    failed_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["channel"]),
            models.Index(fields=["status"]),
            models.Index(fields=["related_model", "related_object_id"]),
            models.Index(fields=["provider_message_id"]),
            models.Index(fields=["recipient_contact"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.get_channel_display()} to "
            f"{self.recipient_contact} - "
            f"{self.get_status_display()}"
        )