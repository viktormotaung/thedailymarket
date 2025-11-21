from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

class AuditEvent(models.Model):
    # Who/when
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_events"
    )
    actor_name = models.CharField(max_length=150, blank=True)
    actor_email = models.EmailField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    # What
    action = models.CharField(max_length=64)  # e.g. "order_delete"
    created_at = models.DateTimeField(auto_now_add=True)

    # Which object
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField(max_length=200, blank=True)

    # Why / auth
    reason = models.TextField(blank=True)
    auth_verified = models.BooleanField(default=False)
    auth_method = models.CharField(max_length=32, blank=True)  # e.g. "staff_code"

    # Snapshots & extra
    before_snapshot = models.JSONField(default=dict, blank=True)
    after_snapshot = models.JSONField(default=dict, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        who = self.actor_name or (self.actor.get_username() if self.actor else "unknown")
        return f"{self.action} by {who} @ {self.created_at:%Y-%m-%d %H:%M}"
