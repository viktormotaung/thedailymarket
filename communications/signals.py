
from io import BytesIO

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

    The welcome email uses the welcome HTML template.

    The same rendered HTML is converted into a PDF.

    The PDF is:
        1. Attached to the welcome email.
        2. Saved in CommunicationDocs.
        3. Linked to the welcome email CommunicationLog.

    Duplicate welcome PDFs are prevented by checking whether
    a welcome document already exists for this Client.
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

        send_sms(
            to=instance.phone,
            message=sms_message,
            client=instance,
        )

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

    text_content = render_to_string(
        "emails/client/welcome.txt",
        email_context,
    )

    # --------------------------------------------------
    # Render HTML email
    # --------------------------------------------------

    html_content = render_to_string(
        "emails/client/welcome.html",
        email_context,
    )

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
    # WELCOME PDF
    # ==================================================

    welcome_filename = f"Welcome, {customer_name}.pdf"

    welcome_pdf = None
    existing_welcome_document = None

    # --------------------------------------------------
    # CHECK FOR EXISTING WELCOME DOCUMENT
    # --------------------------------------------------

    existing_welcome_document = (
        CommunicationDocs.objects
        .filter(
            communication__channel=CommunicationLog.CHANNEL_EMAIL,
            communication__related_model="Client",
            communication__related_object_id=instance.pk,
            filename__istartswith="Welcome,",
        )
        .order_by("-created_at")
        .first()
    )

    # ==================================================
    # REUSE EXISTING PDF
    # ==================================================

    if existing_welcome_document:

        try:

            existing_welcome_document.file.open("rb")

            welcome_pdf = (
                existing_welcome_document.file.read()
            )

            existing_welcome_document.file.close()

        except Exception as exc:

            email_log.status = CommunicationLog.STATUS_FAILED
            email_log.error_message = (
                f"Could not read existing welcome PDF: {exc}"
            )
            email_log.failed_at = timezone.now()

            email_log.save(
                update_fields=[
                    "status",
                    "error_message",
                    "failed_at",
                    "updated_at",
                ]
            )

            return

    # ==================================================
    # GENERATE PDF IF ONE DOES NOT EXIST
    # ==================================================

    if welcome_pdf is None:

        try:

            # ------------------------------------------
            # xhtml2pdf
            # ------------------------------------------

            pdf_buffer = BytesIO()

            pdf_status = pisa.CreatePDF(
                src=html_content,
                dest=pdf_buffer,
                encoding="UTF-8",
            )

            # xhtml2pdf reports PDF generation errors
            # through pdf_status.err rather than raising
            # an exception in all cases.
            if pdf_status.err:

                raise Exception(
                    "xhtml2pdf reported an error while "
                    "generating the welcome PDF."
                )

            welcome_pdf = pdf_buffer.getvalue()

            pdf_buffer.close()

            if not welcome_pdf:

                raise Exception(
                    "The generated welcome PDF is empty."
                )

        except Exception as exc:

            email_log.status = CommunicationLog.STATUS_FAILED
            email_log.error_message = (
                f"Welcome PDF generation failed: {exc}"
            )
            email_log.failed_at = timezone.now()

            email_log.save(
                update_fields=[
                    "status",
                    "error_message",
                    "failed_at",
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

        # --------------------------------------------------
        # HTML EMAIL
        # --------------------------------------------------

        email.attach_alternative(
            html_content,
            "text/html",
        )

        # --------------------------------------------------
        # ATTACH WELCOME PDF
        # --------------------------------------------------

        email.attach(
            welcome_filename,
            welcome_pdf,
            "application/pdf",
        )

        # --------------------------------------------------
        # SEND
        # --------------------------------------------------

        email.send(
            fail_silently=False,
        )

        # ==================================================
        # EMAIL SENT SUCCESSFULLY
        # ==================================================

        email_log.status = CommunicationLog.STATUS_SENT
        email_log.sent_at = timezone.now()
        email_log.error_message = None

        email_log.save(
            update_fields=[
                "status",
                "sent_at",
                "error_message",
                "updated_at",
            ]
        )

        # ==================================================
        # SAVE PDF TO COMMUNICATIONDOCS
        # ==================================================

        # Only create a CommunicationDocs record if one
        # does not already exist.

        if not existing_welcome_document:

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

        # --------------------------------------------------
        # Log email failure
        # --------------------------------------------------

        email_log.status = CommunicationLog.STATUS_FAILED
        email_log.error_message = str(exc)
        email_log.failed_at = timezone.now()

        email_log.save(
            update_fields=[
                "status",
                "error_message",
                "failed_at",
                "updated_at",
            ]
        )



