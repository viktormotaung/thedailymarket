
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from communications.models import CommunicationLog


def send_new_ticket_email(ticket, recipient_email):

    subject = (
        f"[New Ticket #{ticket.pk}] "
        f"{ticket.title}"
    )

    ticket_url = (
        f"https://thedailymarket.co.za"
        f"/portal/staff/tasks/tickets/{ticket.pk}/"
    )

    message = f"""
A new ticket has been created.

Ticket Number:
#{ticket.pk}

Department:
{ticket.get_department_display()}

Subject:
{ticket.title}

View Ticket:
{ticket_url}
"""

    log = CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=ticket.get_department_display(),
        recipient_contact=recipient_email,
        subject=subject,
        message=message,
        provider="Postmark",
        related_model="Ticket",
        related_object_id=ticket.pk,
    )

    try:

        result = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient_email],
            fail_silently=False,
        )

        log.status = CommunicationLog.STATUS_SENT
        log.sent_at = timezone.now()

        log.save(
            update_fields=[
                "status",
                "sent_at",
            ]
        )

        print(
            f"Email sent successfully "
            f"to {recipient_email}. "
            f"Result={result}"
        )

        return True

    except Exception as e:

        log.status = CommunicationLog.STATUS_FAILED
        log.failed_at = timezone.now()
        log.error_message = str(e)

        log.save(
            update_fields=[
                "status",
                "failed_at",
                "error_message",
            ]
        )

        print(
            f"Email FAILED "
            f"to {recipient_email}: {e}"
        )

        return False
    


def send_new_task_email(task, recipient_email):

    subject = (
        f"[New Task #{task.pk}] "
        f"{task.title}"
    )

    task_url = (
        f"https://thedailymarket.co.za"
        f"/portal/staff/tasks/tasks/{task.pk}/"
    )

    assignee = (
        task.assigned_to.get_full_name()
        if task.assigned_to
        else "Department"
    )

    message = f"""
A new task has been assigned.

Task Number:
#{task.pk}

Department:
{task.get_department_display()}

Assigned To:
{assignee}

Subject:
{task.title}

Priority:
{task.get_priority_display()}

View Task:
{task_url}
"""

    log = CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=assignee,
        recipient_contact=recipient_email,
        subject=subject,
        message=message,
        provider="Postmark",
        related_model="Task",
        related_object_id=task.pk,
    )

    try:

        result = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient_email],
            fail_silently=False,
        )

        log.status = CommunicationLog.STATUS_SENT
        log.sent_at = timezone.now()

        log.save(
            update_fields=[
                "status",
                "sent_at",
            ]
        )

        print(
            f"Task email sent successfully "
            f"to {recipient_email}. "
            f"Result={result}"
        )

        return True

    except Exception as e:

        log.status = CommunicationLog.STATUS_FAILED
        log.failed_at = timezone.now()
        log.error_message = str(e)

        log.save(
            update_fields=[
                "status",
                "failed_at",
                "error_message",
            ]
        )

        print(
            f"Task email FAILED "
            f"to {recipient_email}: {e}"
        )

        return False
    
