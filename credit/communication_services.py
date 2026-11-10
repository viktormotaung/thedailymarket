"""
Trade Assist communication services.

All outbound email sent by this module is written to CommunicationLog before
delivery and updated to SENT or FAILED after the email backend responds.
"""
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.timezone import now

from clients.models import Client
from communications.models import CommunicationLog

logger = logging.getLogger(__name__)


def send_tracked_email(
    *,
    recipient_email,
    recipient_name="",
    subject,
    text_body,
    html_body=None,
    related_object=None,
    sent_by=None,
    reply_to=None,
    provider="Django email backend",
    using=None,
):
    """
    Create a CommunicationLog entry for every attempted email.

    A pending row is created before delivery. It is then updated to SENT or
    FAILED. If no recipient address is available, a failed log is still
    created so the missing communication is visible to staff.
    """
    db = using or "default"
    recipient = (recipient_email or "").strip()
    related_fields = {}
    if related_object is not None:
        related_fields = {
            "related_model": related_object._meta.object_name,
            "related_object_id": related_object.pk,
        }

    log = CommunicationLog.objects.using(db).create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=(recipient_name or "")[:255] or None,
        recipient_contact=recipient or "unavailable",
        subject=(subject or "")[:255] or None,
        message=text_body or "",
        provider=provider,
        sent_by=sent_by,
        **related_fields,
    )

    if not recipient:
        log.status = CommunicationLog.STATUS_FAILED
        log.error_message = "No recipient email address was available."
        log.failed_at = now()
        log.save(
            using=db,
            update_fields=["status", "error_message", "failed_at", "updated_at"],
        )
        logger.warning("Email communication #%s was not sent: no recipient.", log.pk)
        return log

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
            headers={"Reply-To": reply_to} if reply_to else None,
        )
        if html_body:
            email.attach_alternative(html_body, "text/html")

        sent_count = email.send(fail_silently=False)
        if not sent_count:
            raise RuntimeError("The configured email backend did not send the message.")

        log.status = CommunicationLog.STATUS_SENT
        log.sent_at = now()
        log.provider = provider
        log.provider_response = {"sent_count": sent_count}
        log.save(
            using=db,
            update_fields=[
                "status", "sent_at", "provider", "provider_response", "updated_at"
            ],
        )
        logger.info(
            "Email sent and logged as CommunicationLog #%s to %s.",
            log.pk,
            recipient,
        )
    except Exception as exc:
        logger.exception(
            "Email communication #%s failed for %s.", log.pk, recipient
        )
        log.status = CommunicationLog.STATUS_FAILED
        log.error_message = str(exc)
        log.failed_at = now()
        log.save(
            using=db,
            update_fields=["status", "error_message", "failed_at", "updated_at"],
        )

    return log


def send_credit_status_email(
    *,
    client_id,
    previous_status,
    new_status,
    sent_by=None,
    using=None,
):
    """
    Send the existing branded Trade Assist status email and log the attempt.

    Used for both manual Client.credit_status changes and formal
    CreditApproval activation.
    """
    db = using or "default"
    client = Client.objects.using(db).filter(pk=client_id).first()
    if client is None:
        logger.error(
            "Cannot send Trade Assist status email: client %s does not exist.",
            client_id,
        )
        return None

    # Resolve the customer's primary email from the linked profile first,
    # then fall back to the email stored directly on Client.
    customer_profile = (
        client.customer_profiles.using(db)
        .select_related("user")
        .filter(user__email__gt="")
        .first()
    )
    user = getattr(customer_profile, "user", None)
    recipient_email = (
        getattr(user, "email", None)
        or getattr(client, "email", None)
        or ""
    )
    recipient_name = (
        user.get_short_name()
        if user and hasattr(user, "get_short_name")
        else ""
    ) or getattr(client, "contact_person", None) or client.name or "there"

    account = getattr(client, "credit_account", None)
    zero = Decimal("0.00")
    credit_limit = account.credit_limit if account else zero
    outstanding_balance = account.credit_used if account else zero
    available_buying_power = max(zero, credit_limit - outstanding_balance)

    status_key = (new_status or "").strip().lower().replace(" ", "_")
    template_by_status = {
        "pending": "email/credit/status_pending.html",
        "active": "email/credit/status_active.html",
        "overdue": "email/credit/status_overdue.html",
        "suspended": "email/credit/status_suspended.html",
        "closed": "email/credit/status_closed.html",
    }
    subject_by_status = {
        "pending": "Trade Assist account under review – The Daily Market",
        "active": "Your Trade Assist buying power is active – The Daily Market",
        "overdue": "Action required: Trade Assist settlement overdue",
        "suspended": "Trade Assist account suspended – The Daily Market",
        "closed": "Trade Assist account closure confirmation – The Daily Market",
    }

    if status_key not in template_by_status:
        logger.warning(
            "Trade Assist status email not sent for client %s: unsupported status %r.",
            client_id,
            new_status,
        )
        return None

    buying_power_available = status_key == "active"
    contribution_pct = (
        getattr(account, "credit_deposit_pct", None)
        if account else None
    )
    if contribution_pct is None:
        contribution_pct = Decimal("100.00")

    term = getattr(account, "payment_term", None) if account else None
    payment_term_label = {
        "0D": "Prepaid",
        "1D": "1 day",
        "3D": "3 days",
        "7D": "7 days",
    }.get(term, term or "Not specified")

    account_manager = getattr(client, "account_manager", None)
    account_manager_name = ""
    if account_manager:
        account_manager_name = (
            getattr(account_manager, "get_full_name", lambda: "")()
            or getattr(account_manager, "first_name", "")
            or getattr(account_manager, "username", "")
        )

    support_email = getattr(
        settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"
    )
    previous_label = (previous_status or "UNSET").replace("_", " ").title()
    new_label = (new_status or "UNSET").replace("_", " ").title()

    context = {
        "client": client,
        "account": account,
        "customer_name": recipient_name,
        "previous_status": previous_label,
        "new_status": new_label,
        "credit_limit": credit_limit or zero,
        "outstanding_balance": outstanding_balance or zero,
        "available_buying_power": available_buying_power,
        "buying_power_available": buying_power_available,
        "contribution_pct": contribution_pct,
        "payment_term_label": payment_term_label,
        "account_manager_name": account_manager_name,
        "support_email": support_email,
    }

    subject = subject_by_status[status_key]
    text_body = (
        f"Hello {recipient_name},\n\n"
        f"Your Trade Assist account status has changed from "
        f"{previous_label} to {new_label}.\n\n"
        f"Approved buying power: R{credit_limit:,.2f}\n"
        f"Outstanding balance: R{outstanding_balance:,.2f}\n"
        f"Available buying power: "
        f"{f'R{available_buying_power:,.2f}' if buying_power_available else 'Unavailable'}\n"
        f"Your upfront contribution: {contribution_pct}%\n"
        f"Settlement term: {payment_term_label}\n\n"
        f"For assistance, contact {support_email} or call 087 265 5488.\n\n"
        "Regards,\nThe Daily Market Team"
    )

    try:
        html_body = render_to_string(template_by_status[status_key], context)
    except Exception as exc:
        # Still record the failed attempt in the communication log.
        logger.exception(
            "Could not render Trade Assist status email for client %s.", client_id
        )
        return _log_render_failure(
            client=client,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=subject,
            text_body=text_body,
            error=exc,
            sent_by=sent_by,
            using=db,
        )

    return send_tracked_email(
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        related_object=client,
        sent_by=sent_by,
        reply_to=support_email,
        using=db,
    )


def _log_render_failure(
    *, client, recipient_email, recipient_name, subject, text_body,
    error, sent_by=None, using=None
):
    """Persist a failed CommunicationLog if the HTML template cannot render."""
    db = using or "default"
    log = CommunicationLog.objects.using(db).create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_FAILED,
        recipient_name=(recipient_name or "")[:255] or None,
        recipient_contact=(recipient_email or "").strip() or "unavailable",
        subject=(subject or "")[:255] or None,
        message=text_body or "",
        related_model=client._meta.object_name,
        related_object_id=client.pk,
        provider="Django email backend",
        sent_by=sent_by,
        error_message=f"Email template rendering failed: {error}",
        failed_at=now(),
    )
    return log


def _customer_mobile(client, customer_profile=None, user=None):
    """Resolve a mobile number without assuming one specific profile schema."""
    candidates = []
    objects = [user, customer_profile, client]
    field_names = (
        "mobile_number", "phone_number", "mobile", "phone",
        "cellphone", "contact_number", "telephone",
    )
    for obj in objects:
        if obj is None:
            continue
        for field_name in field_names:
            value = getattr(obj, field_name, None)
            if value:
                candidates.append(str(value).strip())
    return next((value for value in candidates if value), "")


def send_tracked_sms(
    *,
    recipient_number,
    recipient_name="",
    message,
    related_object=None,
    sent_by=None,
    using=None,
):
    """
    Log every SMS attempt. A provider adapter must be configured through
    settings.TRADEASSIST_SMS_BACKEND as a dotted Python callable path.

    The callable receives (to=..., message=...) and must return either
    True or a dict containing provider response details. A missing adapter
    is recorded as FAILED; no SMS is falsely marked as sent.
    """
    from django.utils.module_loading import import_string

    db = using or "default"
    recipient = (recipient_number or "").strip()
    related_fields = {}
    if related_object is not None:
        related_fields = {
            "related_model": related_object._meta.object_name,
            "related_object_id": related_object.pk,
        }

    log = CommunicationLog.objects.using(db).create(
        channel=CommunicationLog.CHANNEL_SMS,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=(recipient_name or "")[:255] or None,
        recipient_contact=recipient or "unavailable",
        subject="TradeAssist account status update",
        message=message or "",
        provider="Unconfigured SMS provider",
        sent_by=sent_by,
        **related_fields,
    )

    try:
        backend_path = getattr(settings, "TRADEASSIST_SMS_BACKEND", "")
        if not backend_path:
            raise RuntimeError(
                "SMS gateway is not configured. Set TRADEASSIST_SMS_BACKEND "
                "to the dotted path of the SMS provider adapter."
            )
        if not recipient:
            raise RuntimeError("No customer mobile number was found.")

        backend = import_string(backend_path)
        response = backend(to=recipient, message=message)
        if response is False or response is None:
            raise RuntimeError("SMS provider did not confirm acceptance.")

        log.status = CommunicationLog.STATUS_SENT
        log.sent_at = now()
        log.provider = backend_path
        log.provider_response = response if isinstance(response, dict) else {
            "accepted": True
        }
        log.save(using=db, update_fields=[
            "status", "sent_at", "provider", "provider_response", "updated_at"
        ])
    except Exception as exc:
        log.status = CommunicationLog.STATUS_FAILED
        log.failed_at = now()
        log.error_message = str(exc)
        log.provider_response = {
            "provider_configured": bool(getattr(settings, "TRADEASSIST_SMS_BACKEND", "")),
            "exception_type": exc.__class__.__name__,
        }
        log.save(using=db, update_fields=[
            "status", "failed_at", "error_message", "provider_response", "updated_at"
        ])
        logger.warning("TradeAssist SMS #%s failed: %s", log.pk, exc)

    return log


def send_credit_status_notifications(
    *,
    client_id,
    previous_status,
    new_status,
    sent_by=None,
    using=None,
):
    """Send and independently log both email and SMS for a status transition."""
    db = using or "default"
    client = Client.objects.using(db).filter(pk=client_id).first()
    if client is None:
        logger.error("Cannot notify for missing TradeAssist client %s.", client_id)
        return {"email": None, "sms": None}

    # Email is attempted independently; an email failure must not block SMS.
    email_log = send_credit_status_email(
        client_id=client_id,
        previous_status=previous_status,
        new_status=new_status,
        sent_by=sent_by,
        using=db,
    )

    profile = (
        client.customer_profiles.using(db).select_related("user").first()
    )
    user = getattr(profile, "user", None)
    recipient_name = (
        user.get_short_name() if user and hasattr(user, "get_short_name") else ""
    ) or getattr(client, "contact_person", None) or client.name or "there"
    mobile = _customer_mobile(client, profile, user)

    account = getattr(client, "credit_account", None)
    limit = account.credit_limit if account else Decimal("0.00")
    status = (new_status or "").strip().upper()
    messages = {
        "PENDING": (
            "The Daily Market: Your TradeAssist application is Pending Approval. "
            "Please log into your Daily Market profile to view your account and "
            "any outstanding requirements. Contact your sales consultant for help."
        ),
        "ACTIVE": (
            f"The Daily Market: Your TradeAssist account is now ACTIVE! "
            f"Your approved buying power is R{limit:,.2f}. Please log into your "
            "Daily Market profile to view your account details. Contact your "
            "sales consultant to start utilising your buying power."
        ),
        "OVERDUE": (
            "The Daily Market: Your TradeAssist account is now OVERDUE. Please "
            "log into your Daily Market profile to review your outstanding balance "
            "and settlement details. Contact your sales consultant urgently."
        ),
        "SUSPENDED": (
            "The Daily Market: Your TradeAssist account has been SUSPENDED. "
            "Your buying power is temporarily unavailable. Please log into your "
            "Daily Market profile and contact your sales consultant for assistance."
        ),
        "CLOSED": (
            "The Daily Market: Your TradeAssist account has been CLOSED and your "
            "buying power is no longer active. Please log into your Daily Market "
            "profile to review your account history. Contact your sales consultant "
            "if you need assistance."
        ),
    }
    sms_log = None
    sms_text = messages.get(status)
    if sms_text:
        sms_log = send_tracked_sms(
            recipient_number=mobile,
            recipient_name=recipient_name,
            message=sms_text,
            related_object=client,
            sent_by=sent_by,
            using=db,
        )
    else:
        logger.warning("No TradeAssist SMS template exists for status %r.", new_status)

    return {"email": email_log, "sms": sms_log}
