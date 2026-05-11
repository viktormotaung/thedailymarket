from django.contrib import admin

from .models import CommunicationLog


@admin.register(CommunicationLog)
class CommunicationLogAdmin(admin.ModelAdmin):

    list_display = [
        "id",
        "channel",
        "status",
        "recipient_name",
        "recipient_contact",
        "provider",
        "provider_message_id",
        "related_model",
        "related_object_id",
        "sent_by",
        "created_at",
        "sent_at",
    ]

    list_filter = [
        "channel",
        "status",
        "provider",
        "created_at",
        "sent_at",
        "delivered_at",
        "read_at",
    ]

    search_fields = [
        "recipient_name",
        "recipient_contact",
        "subject",
        "provider_message_id",
        "message",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "sent_at",
        "delivered_at",
        "read_at",
        "provider_response",
    ]

    ordering = [
        "-created_at",
    ]

    fieldsets = (

        (
            "Communication",
            {
                "fields": (
                    "channel",
                    "status",
                    "recipient_name",
                    "recipient_contact",
                    "subject",
                    "message",
                )
            },
        ),

        (
            "Provider Information",
            {
                "fields": (
                    "provider",
                    "provider_message_id",
                    "provider_response",
                    "error_message",
                )
            },
        ),

        (
            "Linked Object",
            {
                "fields": (
                    "related_model",
                    "related_object_id",
                )
            },
        ),

        (
            "Audit",
            {
                "fields": (
                    "sent_by",
                    "created_at",
                    "updated_at",
                    "sent_at",
                    "delivered_at",
                    "read_at",
                )
            },
        ),
    )