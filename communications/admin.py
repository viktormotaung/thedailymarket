from django.contrib import admin

from .models import CommunicationLog, WhatsAppMessage


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
        "delivered_at",
        "read_at",
        "failed_at",
    ]

    list_filter = [
        "channel",
        "status",
        "provider",
        "whatsapp_pricing_category",
        "whatsapp_pricing_type",
        "whatsapp_billable",
        "created_at",
        "sent_at",
        "delivered_at",
        "read_at",
        "failed_at",
    ]

    search_fields = [
        "recipient_name",
        "recipient_contact",
        "subject",
        "provider_message_id",
        "message",
        "related_model",
        "related_object_id",
        "whatsapp_phone_number_id",
        "whatsapp_display_phone_number",
        "whatsapp_recipient_id",
        "whatsapp_conversation_id",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "sent_at",
        "delivered_at",
        "read_at",
        "failed_at",
        "provider_response",
        "provider_status_payload",
    ]

    ordering = [
        "-created_at",
    ]

    date_hierarchy = "created_at"

    list_per_page = 50

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
            "Linked Object",
            {
                "fields": (
                    "related_model",
                    "related_object_id",
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
                    "provider_status_payload",
                    "error_message",
                )
            },
        ),
        (
            "WhatsApp Tracking",
            {
                "fields": (
                    "whatsapp_phone_number_id",
                    "whatsapp_display_phone_number",
                    "whatsapp_recipient_id",
                    "whatsapp_conversation_id",
                    "whatsapp_pricing_category",
                    "whatsapp_pricing_type",
                    "whatsapp_billable",
                )
            },
        ),
        (
            "Audit / Timing",
            {
                "fields": (
                    "sent_by",
                    "created_at",
                    "updated_at",
                    "sent_at",
                    "delivered_at",
                    "read_at",
                    "failed_at",
                )
            },
        ),
    )


@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):

    list_display = [
        "id",
        "message_type",
        "template_name",
        "status",
        "recipient",
        "whatsapp_message_id",
        "invoice",
        "quotation",
        "created_at",
        "updated_at",
    ]

    list_filter = [
        "message_type",
        "template_name",
        "status",
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "recipient",
        "template_name",
        "whatsapp_message_id",
        "invoice__id",
        "quotation__id",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "response_payload",
    ]

    ordering = [
        "-created_at",
    ]

    date_hierarchy = "created_at"

    list_per_page = 50

    fieldsets = (
        (
            "WhatsApp Message",
            {
                "fields": (
                    "message_type",
                    "template_name",
                    "status",
                    "recipient",
                    "whatsapp_message_id",
                )
            },
        ),
        (
            "Linked Records",
            {
                "fields": (
                    "invoice",
                    "quotation",
                )
            },
        ),
        (
            "Provider Response",
            {
                "fields": (
                    "response_payload",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )