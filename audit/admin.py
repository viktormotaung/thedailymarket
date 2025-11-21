from django.contrib import admin
from .models import AuditEvent

@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_name", "actor_email", "object_repr", "auth_verified")
    list_filter = ("action", "auth_verified", "created_at")
    search_fields = ("actor_name", "actor_email", "object_repr", "reason", "extra")
    readonly_fields = (
        "created_at", "actor", "actor_name", "actor_email", "ip_address", "user_agent",
        "action", "content_type", "object_id", "object_repr", "reason",
        "auth_verified", "auth_method", "before_snapshot", "after_snapshot", "extra"
    )
