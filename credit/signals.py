"""
Credit account notification signals.

A notification is sent only when an existing CreditAccount.status value
changes. Creating a CreditAccount never sends a status email.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import CreditAccount

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=CreditAccount)
def capture_previous_credit_account_status(sender, instance, using, **kwargs):
    """
    Capture the persisted status before an existing account is saved.
    New accounts deliberately have no previous status.
    """
    instance._previous_status_for_notification = None

    if not instance.pk:
        return

    previous = (
        sender.objects.using(using)
        .filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )
    instance._previous_status_for_notification = previous


def _send_credit_status_email(account_id, previous_status, new_status, using):
    """
    Resolve the client's email address and send a plain-text status update.
    Re-fetch after commit so the email reflects the committed account state.
    """
    try:
        account = (
            CreditAccount.objects.using(using)
            .select_related("client", "funder")
            .get(pk=account_id)
        )

        # If another status transition occurred before this callback ran,
        # do not send a stale notification.
        if account.status != new_status:
            logger.info(
                "Skipping stale credit status email for account %s: "
                "expected %s, current status is %s.",
                account_id, new_status, account.status
            )
            return

        profile = (
            account.client.customer_profiles
            .select_related("user")
            .filter(user__email__gt="")
            .first()
        )
        user = getattr(profile, "user", None) if profile else None
        recipient = getattr(user, "email", None)

        if not recipient:
            logger.warning(
                "Credit account %s changed status %s -> %s, "
                "but no customer profile email address was found.",
                account_id, previous_status, new_status
            )
            return

        old_label = dict(CreditAccount.STATUS_CHOICES).get(
            previous_status, previous_status
        )
        new_label = account.get_status_display()
        client_name = str(account.client)

        subject = f"The Daily Market – Buying Power Account {new_label}"

        message = (
            f"Dear {user.get_full_name() or user.get_username()},\n\n"
            f"This is to inform you that the buying-power account for "
            f"{client_name} has changed status.\n\n"
            f"Previous status: {old_label}\n"
            f"New status: {new_label}\n"
            f"Buying-power limit: R{account.credit_limit:,.2f}\n"
            f"Outstanding usage: R{account.credit_used:,.2f}\n"
        )

        if account.status_reason:
            message += f"\nReason: {account.status_reason}\n"

        message += (
            "\nIf you have questions about this change, please contact "
            f"{getattr(settings, 'SUPPORT_EMAIL', 'support@thedailymarket.co.za')}.\n\n"
            "Regards,\nThe Daily Market"
        )

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )

        logger.info(
            "Credit status email sent for account %s: %s -> %s to %s.",
            account_id, previous_status, new_status, recipient
        )

    except Exception:
        logger.exception(
            "Failed to send credit status email for account %s (%s -> %s).",
            account_id, previous_status, new_status
        )


@receiver(post_save, sender=CreditAccount)
def notify_client_when_credit_account_status_changes(
    sender, instance, created, using, update_fields=None, **kwargs
):
    """
    Send one email after commit for a genuine status change on an existing
    account. Ignore creation and saves that did not persist the status field.
    """
    if created:
        return

    if update_fields is not None and "status" not in update_fields:
        return

    previous_status = getattr(
        instance, "_previous_status_for_notification", None
    )
    new_status = instance.status

    if not previous_status or previous_status == new_status:
        return

    transaction.on_commit(
        lambda: _send_credit_status_email(
            instance.pk, previous_status, new_status, using
        ),
        using=using,
    )
