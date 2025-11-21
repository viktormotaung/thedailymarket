from __future__ import annotations

from celery import shared_task
from django.db.models import F, Q
from django.utils import timezone
from django.utils.timezone import localdate
from django.conf import settings
from django.core.mail import EmailMessage

from .models import Invoice

# If you added this model earlier, keep it. If not, the 05:00 task will still work
# without it by computing a fallback.
try:
    from .models import DailyOverdueSummary
except Exception:
    DailyOverdueSummary = None


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def flag_overdue_invoices() -> int:
    """
    Runs daily at 04:45 Africa/Johannesburg.

    Marks as overdue any invoice where:
      - due_date < today
      - status != 'overdue'
      - deposit_paid < amount_due

    Also writes a DailyOverdueSummary (if model exists) so the 05:00 email can
    report 'new_overdue' and 'total_overdue'.
    """
    today = localdate()
    now = timezone.localtime()

    to_update_qs = Invoice.objects.filter(
        Q(due_date__lt=today) &
        ~Q(status="overdue") &
        Q(deposit_paid__lt=F("amount_due"))
    )
    new_overdue = to_update_qs.count()

    if new_overdue:
        to_update_qs.update(status="overdue", updated_at=now)

    total_overdue = Invoice.objects.filter(status="overdue").count()

    if DailyOverdueSummary is not None:
        DailyOverdueSummary.objects.update_or_create(
            run_date=today,
            defaults={"new_overdue": new_overdue, "total_overdue": total_overdue},
        )

    return new_overdue


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def email_overdue_summary(recipients: list[str] | None = None) -> bool:
    """
    Runs daily at 05:00 Africa/Johannesburg.
    Emails a short summary of 'new overdue' & 'total overdue' for today.
    """
    if recipients is None:
        recipients = ["you@example.com"]

    today = localdate()

    # Prefer the stored summary, otherwise compute a safe fallback.
    new_overdue = 0
    total_overdue = Invoice.objects.filter(status="overdue").count()

    if DailyOverdueSummary is not None:
        try:
            s = DailyOverdueSummary.objects.get(run_date=today)
            new_overdue = s.new_overdue
            total_overdue = s.total_overdue
        except DailyOverdueSummary.DoesNotExist:
            pass

    subject = f"Overdue Payments Summary — {today.isoformat()}"
    body = (
        f"Good day,\n\n"
        f"At 5am {today.isoformat()} there were {new_overdue} new overdue payments.\n"
        f"Total overdue payments are {total_overdue}.\n\n"
        f"Thank you"
    )

    email = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)
    email.send(fail_silently=False)
    return True
