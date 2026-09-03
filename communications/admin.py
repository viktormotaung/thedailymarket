
from django.contrib import admin

from .models import (
    CommunicationLog,
    CommunicationDocs,
    WhatsAppMessage,
    EmailLog,
)


# ============================================================
# COMMUNICATION LOG
# ============================================================

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

    # IMPORTANT:
    # Do not use date_hierarchy until MySQL timezone tables
    # are correctly configured.
    # date_hierarchy = "created_at"

    list_per_page = 50


# ============================================================
# COMMUNICATION DOCUMENTS
# ============================================================

@admin.register(CommunicationDocs)
class CommunicationDocsAdmin(admin.ModelAdmin):

    list_display = [
        "id",
        "filename",
        "communication",
        "communication_channel",
        "recipient_name",
        "recipient_contact",
        "created_at",
    ]

    list_filter = [
        "communication__channel",
        "created_at",
    ]

    search_fields = [
        "filename",
        "communication__recipient_name",
        "communication__recipient_contact",
        "communication__subject",
    ]

    readonly_fields = [
        "created_at",
    ]

    ordering = [
        "-created_at",
    ]

    list_per_page = 50

    fieldsets = (
        (
            "Document",
            {
                "fields": (
                    "filename",
                    "file",
                )
            },
        ),
        (
            "Communication",
            {
                "fields": (
                    "communication",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_at",
                )
            },
        ),
    )

    @admin.display(
        description="Channel"
    )
    def communication_channel(self, obj):
        return obj.communication.channel

    @admin.display(
        description="Recipient"
    )
    def recipient_name(self, obj):
        return obj.communication.recipient_name

    @admin.display(
        description="Contact"
    )
    def recipient_contact(self, obj):
        return obj.communication.recipient_contact


# ============================================================
# WHATSAPP MESSAGE
# ============================================================

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


# ============================================================
# EMAIL LOG
# ============================================================

@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):

    list_display = [
        "id",
        "created_at",
        "recipient",
        "subject",
        "status",
    ]

    list_filter = [
        "status",
        "created_at",
    ]

    search_fields = [
        "recipient",
        "subject",
        "error_message",
    ]

    readonly_fields = [
        "created_at",
    ]

    ordering = [
        "-created_at",
    ]

    list_per_page = 50

    fieldsets = (
        (
            "Email",
            {
                "fields": (
                    "recipient",
                    "subject",
                    "status",
                    "error_message",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_at",
                )
            },
        ),
    )


