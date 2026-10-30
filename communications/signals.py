from io import BytesIO
import logging

from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

from xhtml2pdf import pisa

from clients.models import Client
from communications.models import CommunicationLog, CommunicationDocs
from communications.services.smsportal import send_sms


logger = logging.getLogger(__name__)


# ============================================================
# CLIENT PRE-SAVE
# ============================================================

@receiver(pre_save, sender=Client)
def client_pre_save(sender, instance, **kwargs):
    """
    Determine whether this Client is changing to ACTIVE.
    """

    instance._activation_trigger = False

    # --------------------------------------------------
    # New Client
    # --------------------------------------------------

    if not instance.pk:
        # A newly-created ACTIVE client should also trigger
        # the welcome SMS and welcome email.
        if instance.status == "ACTIVE":
            instance._activation_trigger = True

        return

    # --------------------------------------------------
    # Existing Client
    # --------------------------------------------------

    old_status = (
        sender.objects
        .filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )

    # Trigger only when the Client changes from a
    # non-ACTIVE status to ACTIVE.
    if old_status != "ACTIVE" and instance.status == "ACTIVE":
        instance._activation_trigger = True


# ============================================================
# CLIENT POST-SAVE
# ============================================================

@receiver(post_save, sender=Client)
def client_post_save(sender, instance, created, **kwargs):
    """
    Send the Client activation SMS and welcome email after
    the Client has successfully been saved.

    The HTML email and PDF attachment are both generated from
    the same rendered welcome.html template.

    The template contains:
        1. An email layout, shown in normal screen rendering.
        2. A PDF layout, shown by the template's print CSS.

    The generated PDF is:
        1. Attached to the welcome email.
        2. Saved in CommunicationDocs.
        3. Linked to the welcome email CommunicationLog.
    """

    # --------------------------------------------------
    # Check whether activation communications should be sent
    # --------------------------------------------------

    if not getattr(instance, "_activation_trigger", False):
        return

    # --------------------------------------------------
    # Customer name
    # --------------------------------------------------

    customer_name = (
        instance.contact_person.strip()
        if instance.contact_person
        else instance.name.strip()
    )

    # --------------------------------------------------
    # Account Manager name
    # --------------------------------------------------

    if (
        instance.account_manager
        and instance.account_manager.first_name
    ):
        account_manager_name = (
            instance.account_manager.first_name.strip()
        )
    else:
        account_manager_name = "your Account Manager"

    # ==================================================
    # WELCOME SMS
    # ==================================================


    if instance.phone:

        sms_message = (
            f"Welcome to The Daily Market!\n\n"
            f"Dear {customer_name},\n\n"
            f"Your customer profile is now active.\n\n"
            f"A welcome email has been sent to you.\n\n"
            f"Customer Code: {instance.client_number}\n\n"
            f"You can now stock up for your kitchen.\n\n"
            f"Your Account Manager is {account_manager_name}.\n\n"
            f"Please contact {account_manager_name} to place orders "
            f"or enquire about products.\n\n"
            f"For urgent queries, please contact 087 265 5488.\n\n"
            f"Thank you for choosing The Daily Market."
        )

        try:
            send_sms(
                to=instance.phone,
                message=sms_message,
                client=instance,
            )
        except Exception:
            logger.exception(
                "Welcome SMS sending failed for Client ID %s",
                instance.pk,
            )
            raise
    # ==================================================
    # WELCOME EMAIL
    # ==================================================

    if not instance.email:
        return


    email_subject = "Welcome to The Daily Market"

    # --------------------------------------------------
    # Context available to both HTML and TXT templates
    # --------------------------------------------------

    email_context = {
        "client": instance,
        "customer_name": customer_name,
        "account_manager_name": account_manager_name,
    }

    # --------------------------------------------------
    # Render plain-text email
    # --------------------------------------------------

    try:
        text_content = render_to_string(
            "emails/client/welcome.txt",
            email_context,
        )
    except Exception:
        logger.exception(
            "Welcome plain-text email template rendering failed for Client ID %s",
            instance.pk,
        )
        raise

    # --------------------------------------------------
    # Render HTML email
    # --------------------------------------------------

    try:
        html_content = render_to_string(
            "emails/client/welcome.html",
            email_context,
        )
    except Exception:
        logger.exception(
            "Welcome HTML email template rendering failed for Client ID %s",
            instance.pk,
        )
        raise

    # ==================================================
    # FROM EMAIL
    # ==================================================

    default_from_email = getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        "The Daily Market <accounts@thedailymarket.co.za>",
    )

    # Display sender as Accounts while retaining the
    # configured email address.
    if "<" in default_from_email and ">" in default_from_email:

        email_address = default_from_email[
            default_from_email.find("<") + 1:
            default_from_email.find(">")
        ]

        from_email = (
            f"The Daily Market Accounts <{email_address}>"
        )

    else:

        from_email = (
            f"The Daily Market Accounts <{default_from_email}>"
        )

    # ==================================================
    # CREATE EMAIL COMMUNICATION LOG
    # ==================================================


    email_log = CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=customer_name,
        recipient_contact=instance.email,
        subject=email_subject,
        message=text_content,
        related_model="Client",
        related_object_id=instance.pk,
        provider="Postmark",
    )

    # ==================================================
    # GENERATE WELCOME PDF FROM THE SAME HTML
    # ==================================================

    welcome_filename = f"Welcome, {customer_name}.pdf"

    # --------------------------------------------------
    # PDF GENERATION
    # --------------------------------------------------

    try:
        pdf_buffer = BytesIO()

        pdf_status = pisa.CreatePDF(
            src=html_content,
            dest=pdf_buffer,
            encoding="UTF-8",
        )

        if pdf_status.err:
            raise Exception(
                "xhtml2pdf reported an error while generating "
                "the welcome PDF."
            )

        welcome_pdf = pdf_buffer.getvalue()
        pdf_buffer.close()

        if not welcome_pdf:
            raise Exception(
                "xhtml2pdf generated an empty welcome PDF."
            )


    except Exception as exc:
        error_detail = (
            f"PDF generation failed ({type(exc).__name__}): {exc}"
        )

        logger.exception(
            "Welcome email PDF generation failed for Client ID %s",
            instance.pk,
        )

        email_log.status = CommunicationLog.STATUS_FAILED
        email_log.error_message = error_detail
        email_log.failed_at = timezone.now()
        email_log.provider_response = {
            "stage": "pdf_generation",
            "exception_type": type(exc).__name__,
            "exception": str(exc),
        }

        email_log.save(
            update_fields=[
                "status",
                "error_message",
                "failed_at",
                "provider_response",
                "updated_at",
            ]
        )

        return

    # ==================================================
    # SEND EMAIL
    # ==================================================

    try:
        email = EmailMultiAlternatives(
            subject=email_subject,
            body=text_content,
            from_email=from_email,
            to=[instance.email],
        )

        email.attach_alternative(
            html_content,
            "text/html",
        )

        email.attach(
            welcome_filename,
            welcome_pdf,
            "application/pdf",
        )


        # fail_silently=False is intentional: capture provider errors.
        sent_count = email.send(fail_silently=False)


    except Exception as exc:
        error_detail = (
            f"Email sending failed ({type(exc).__name__}): {exc}"
        )

        logger.exception(
            "Welcome email sending failed for Client ID %s to %s",
            instance.pk,
            instance.email,
        )

        email_log.status = CommunicationLog.STATUS_FAILED
        email_log.error_message = error_detail
        email_log.failed_at = timezone.now()
        email_log.provider_response = {
            "stage": "email_send",
            "exception_type": type(exc).__name__,
            "exception": str(exc),
            "recipient": instance.email,
        }

        email_log.save(
            update_fields=[
                "status",
                "error_message",
                "failed_at",
                "provider_response",
                "updated_at",
            ]
        )

        return

    # ==================================================
    # EMAIL SENT SUCCESSFULLY
    # ==================================================

    email_log.status = CommunicationLog.STATUS_SENT
    email_log.sent_at = timezone.now()
    email_log.error_message = None
    email_log.provider_response = {
        "stage": "email_sent",
        "recipient": instance.email,
        "pdf_attached": True,
    }

    email_log.save(
        update_fields=[
            "status",
            "sent_at",
            "error_message",
            "provider_response",
            "updated_at",
        ]
    )


    # ==================================================
    # SAVE PDF TO COMMUNICATIONDOCS
    # ==================================================
    # Archiving is deliberately separate from sending. If storage
    # fails, do not incorrectly mark an email that was sent as FAILED.

    try:
        communication_doc = CommunicationDocs(
            communication=email_log,
            filename=welcome_filename,
        )

        communication_doc.file.save(
            welcome_filename,
            ContentFile(welcome_pdf),
            save=True,
        )

    except Exception as exc:
        error_detail = (
            "Email was sent successfully, but saving the PDF to "
            f"CommunicationDocs failed ({type(exc).__name__}): {exc}"
        )

        logger.exception(
            "Welcome email was sent, but PDF archiving failed "
            "for Client ID %s",
            instance.pk,
        )

        email_log.error_message = error_detail
        email_log.provider_response = {
            "stage": "pdf_archive",
            "email_sent": True,
            "exception_type": type(exc).__name__,
            "exception": str(exc),
        }

        email_log.save(
            update_fields=[
                "error_message",
                "provider_response",
                "updated_at",
            ]
        )


