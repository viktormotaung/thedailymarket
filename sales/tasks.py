from datetime import datetime, time, timedelta
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.db import IntegrityError

from profiles.models import SalesRepProfile
from clients.models import Lead, Prospect, Client
from invoices.models import Invoice
from communications.models import CommunicationLog

from .models import DailyTaskSchedule


logger = logging.getLogger(__name__)


# ============================================================================
# SHARED HELPERS
# ============================================================================

def _report_day():
    """Return the current reporting date and its timezone-aware boundaries."""
    now = timezone.localtime(timezone.now())
    report_date = now.date()

    day_start = timezone.make_aware(
        datetime.combine(report_date, time.min),
        timezone.get_current_timezone(),
    )
    day_end = day_start + timedelta(days=1)

    return now, report_date, day_start, day_end


def _daily_counts(user_ids, report_date, day_start, day_end):
    """Return daily sales counts for the supplied users."""
    if user_ids:
        lead_count = Lead.objects.filter(
            assigned_to_id__in=user_ids,
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).count()

        prospect_count = Prospect.objects.filter(
            owner_id__in=user_ids,
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).count()

        client_count = Client.objects.filter(
            account_manager_id__in=user_ids,
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).count()

        invoice_count = Invoice.objects.filter(
            client__account_manager_id__in=user_ids,
            invoice_date=report_date,
        ).count()
    else:
        lead_count = 0
        prospect_count = 0
        client_count = 0
        invoice_count = 0

    return {
        "lead_count": lead_count,
        "prospect_count": prospect_count,
        "client_count": client_count,
        "invoice_count": invoice_count,
    }


def _send_email(
    *,
    subject,
    text_message,
    html_message,
    recipient,
    recipient_name=None,
):
    """
    Send one email and create/update a CommunicationLog record.

    A CommunicationLog record is created BEFORE the email is sent so that
    every attempted email has an audit trail. Successful sends are marked
    SENT; provider/send failures are marked FAILED and the exception is
    re-raised so the caller can handle that recipient without stopping the
    rest of the report run.
    """

    communication_log = CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=recipient_name,
        recipient_contact=recipient,
        subject=subject,
        message=text_message,
        provider="Postmark",
    )

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[recipient],
        )

        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)

        communication_log.status = CommunicationLog.STATUS_SENT
        communication_log.sent_at = timezone.now()
        communication_log.save(
            update_fields=[
                "status",
                "sent_at",
            ]
        )

    except Exception as exc:
        communication_log.status = CommunicationLog.STATUS_FAILED
        communication_log.failed_at = timezone.now()
        communication_log.error_message = f"{type(exc).__name__}: {exc}"
        communication_log.save(
            update_fields=[
                "status",
                "failed_at",
                "error_message",
            ]
        )

        raise


# ============================================================================
# SUPERVISOR REPORTS
# ============================================================================

def send_daily_supervisor_sales_reports():
    """
    Send one daily sales report to EVERY active user whose SalesRepProfile
    has the Supervisor role.

    Supervisor report scope:
        - Only reps assigned to that supervisor are included.
        - If the supervisor has no reps, the supervisor STILL receives a
          report showing zero activity.
        - A supervisor never receives another supervisor's team data.

    Manager users are deliberately excluded here when they also have the
    Supervisor role. Managers receive the separate management report.

    Representative daily emails are not sent by this task.
    """

    now, report_date, day_start, day_end = _report_day()

    emails_sent = 0
    recipients_failed = []
    supervisors_found = 0

    # A Manager takes precedence over Supervisor when a user has both roles.
    supervisors = (
        SalesRepProfile.objects
        .filter(
            roles__name="Supervisor",
            user__is_active=True,
        )
        .exclude(
            roles__name="Manager",
        )
        .select_related(
            "user",
            "staff_profile",
            "supervisor",
        )
        .prefetch_related("roles")
        .distinct()
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username",
        )
    )

    for supervisor_profile in supervisors:
        supervisors_found += 1
        supervisor_user = supervisor_profile.user

        if not supervisor_user.email:
            recipients_failed.append({
                "recipient": supervisor_user.get_username(),
                "email": "",
                "error": "Supervisor has no email address.",
            })
            continue

        # IMPORTANT: use the supervisor relationship to determine the team.
        # This naturally produces an empty team when the supervisor has no reps.
        team_profiles = list(
            SalesRepProfile.objects
            .filter(
                supervisor=supervisor_profile.staff_profile,
                user__is_active=True,
            )
            .exclude(
                user_id=supervisor_user.id,
            )
            .select_related(
                "user",
                "staff_profile",
                "supervisor",
            )
            .order_by(
                "user__first_name",
                "user__last_name",
                "user__username",
            )
        )

        team_user_ids = [
            profile.user_id
            for profile in team_profiles
            if profile.user_id
        ]

        counts = _daily_counts(
            team_user_ids,
            report_date,
            day_start,
            day_end,
        )

        summary = {
            "rep_count": len(team_profiles),
            "lead_count": counts["lead_count"],
            "prospect_count": counts["prospect_count"],
            "client_count": counts["client_count"],
            "invoice_count": counts["invoice_count"],
        }

        rep_summaries = []

        for rep_profile in team_profiles:
            rep_user_id = rep_profile.user_id
            rep_counts = _daily_counts(
                [rep_user_id],
                report_date,
                day_start,
                day_end,
            )

            rep_summaries.append({
                "rep": rep_profile.user,
                "rep_profile": rep_profile,
                "lead_count": rep_counts["lead_count"],
                "prospect_count": rep_counts["prospect_count"],
                "client_count": rep_counts["client_count"],
                "invoice_count": rep_counts["invoice_count"],
            })

        context = {
            "supervisor": supervisor_user,
            "supervisor_profile": supervisor_profile,
            "supervisor_staff_profile": supervisor_profile.staff_profile,
            "report_date": report_date,
            "report_datetime": now,
            "team_profiles": team_profiles,
            "rep_summaries": rep_summaries,
            "summary": summary,
        }

        try:
            html_message = render_to_string(
                "email/daily_supervisor_sales.html",
                context,
            )

            supervisor_name = (
                supervisor_user.get_full_name()
                or supervisor_user.get_username()
                or "Supervisor"
            )

            text_message = (
                f"Good evening {supervisor_name},\n\n"
                f"Here is your daily sales summary for "
                f"{report_date.strftime('%d %B %Y')}.\n\n"
                f"DAILY SALES SUMMARY\n"
                f"Your Reps: {summary['rep_count']}\n"
                f"New Leads: {summary['lead_count']}\n"
                f"New Prospects: {summary['prospect_count']}\n"
                f"New Clients: {summary['client_count']}\n"
                f"Invoices Issued: {summary['invoice_count']}\n\n"
                f"This report was generated automatically "
                f"by The Daily Market."
            )

            _send_email(
                subject=(
                    "Daily Sales Summary — "
                    f"{report_date.strftime('%d %b %Y')}"
                ),
                text_message=text_message,
                html_message=html_message,
                recipient=supervisor_user.email,
                recipient_name=supervisor_name,
            )

            emails_sent += 1

        except Exception as exc:
            logger.exception(
                "Daily supervisor report failed for %s (%s)",
                supervisor_user.get_username(),
                supervisor_user.email,
            )
            recipients_failed.append({
                "recipient": supervisor_user.get_username(),
                "email": supervisor_user.email,
                "error": f"{type(exc).__name__}: {exc}",
            })
            # IMPORTANT: continue to the next supervisor.

    return {
        "date": str(report_date),
        "supervisors_found": supervisors_found,
        "emails_sent": emails_sent,
        "recipients_failed": recipients_failed,
    }


# ============================================================================
# MANAGER REPORTS
# ============================================================================

def send_daily_manager_sales_reports():
    """
    Send one daily management report to EVERY active user whose
    SalesRepProfile has the Manager role.

    Manager scope:
        - All daily leads.
        - All daily prospects.
        - All daily clients.
        - All invoices issued today.
        - A per-sales-user activity breakdown.

    This report is NOT restricted by supervisor/team relationship.
    """

    now, report_date, day_start, day_end = _report_day()

    emails_sent = 0
    recipients_failed = []
    managers_found = 0

    managers = (
        SalesRepProfile.objects
        .filter(
            roles__name="Manager",
            user__is_active=True,
        )
        .select_related(
            "user",
            "staff_profile",
            "supervisor",
        )
        .prefetch_related("roles")
        .distinct()
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username",
        )
    )

    # Everything means all active sales profiles, not just profiles
    # assigned to one supervisor.
    all_sales_profiles = list(
        SalesRepProfile.objects
        .filter(
            user__is_active=True,
        )
        .select_related(
            "user",
            "staff_profile",
            "supervisor",
        )
        .prefetch_related("roles")
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username",
        )
    )

    all_user_ids = [
        profile.user_id
        for profile in all_sales_profiles
        if profile.user_id
    ]

    overall_counts = _daily_counts(
        all_user_ids,
        report_date,
        day_start,
        day_end,
    )

    # Build the management breakdown once; every manager receives the same
    # company-wide report.
    user_summaries = []

    for profile in all_sales_profiles:
        user_counts = _daily_counts(
            [profile.user_id],
            report_date,
            day_start,
            day_end,
        )

        role_names = sorted({
            role.name
            for role in profile.roles.all()
        })

        user_summaries.append({
            "user": profile.user,
            "profile": profile,
            "roles": ", ".join(role_names) if role_names else "—",
            "lead_count": user_counts["lead_count"],
            "prospect_count": user_counts["prospect_count"],
            "client_count": user_counts["client_count"],
            "invoice_count": user_counts["invoice_count"],
        })

    for manager_profile in managers:
        managers_found += 1
        manager_user = manager_profile.user

        if not manager_user.email:
            recipients_failed.append({
                "recipient": manager_user.get_username(),
                "email": "",
                "error": "Manager has no email address.",
            })
            continue

        manager_name = (
            manager_user.get_full_name()
            or manager_user.get_username()
            or "Manager"
        )

        subject = (
            "Daily Sales Management Report — "
            f"{report_date.strftime('%d %b %Y')}"
        )

        text_lines = [
            "The Daily Market",
            "Daily Sales Management Report",
            "",
            f"Good evening {manager_name},",
            "",
            f"Company-wide sales activity for {report_date.strftime('%d %B %Y')}:",
            "",
            f"Active Sales Users: {len(all_sales_profiles)}",
            f"New Leads: {overall_counts['lead_count']}",
            f"New Prospects: {overall_counts['prospect_count']}",
            f"New Clients: {overall_counts['client_count']}",
            f"Invoices Issued: {overall_counts['invoice_count']}",
            "",
            "ACTIVITY BY SALES USER",
        ]

        for row in user_summaries:
            user_name = (
                row["user"].get_full_name()
                or row["user"].get_username()
            )
            text_lines.extend([
                "",
                f"{user_name} ({row['roles']})",
                f"  Leads: {row['lead_count']}",
                f"  Prospects: {row['prospect_count']}",
                f"  Clients: {row['client_count']}",
                f"  Invoices: {row['invoice_count']}",
            ])

        text_lines.extend([
            "",
            "This report was generated automatically by The Daily Market.",
        ])

        text_message = "\n".join(text_lines)

        # Inline HTML keeps the management report independent from the
        # supervisor-specific email template.
        rows_html = "".join(
            f"<tr>"
            f"<td style='padding:8px;border:1px solid #ddd;'>{row['user'].get_full_name() or row['user'].get_username()}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;'>{row['roles']}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;text-align:center;'>{row['lead_count']}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;text-align:center;'>{row['prospect_count']}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;text-align:center;'>{row['client_count']}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;text-align:center;'>{row['invoice_count']}</td>"
            f"</tr>"
            for row in user_summaries
        )

        html_message = f"""
        <html>
        <body style='font-family:Arial,sans-serif;color:#222;'>
            <h2>The Daily Market</h2>
            <h3>Daily Sales Management Report</h3>
            <p>Good evening {manager_name},</p>
            <p>Company-wide sales activity for <strong>{report_date.strftime('%d %B %Y')}</strong>:</p>

            <table style='border-collapse:collapse;margin-bottom:24px;'>
                <tr>
                    <td style='padding:8px;border:1px solid #ddd;'><strong>Active Sales Users</strong></td>
                    <td style='padding:8px;border:1px solid #ddd;'>{len(all_sales_profiles)}</td>
                </tr>
                <tr>
                    <td style='padding:8px;border:1px solid #ddd;'><strong>New Leads</strong></td>
                    <td style='padding:8px;border:1px solid #ddd;'>{overall_counts['lead_count']}</td>
                </tr>
                <tr>
                    <td style='padding:8px;border:1px solid #ddd;'><strong>New Prospects</strong></td>
                    <td style='padding:8px;border:1px solid #ddd;'>{overall_counts['prospect_count']}</td>
                </tr>
                <tr>
                    <td style='padding:8px;border:1px solid #ddd;'><strong>New Clients</strong></td>
                    <td style='padding:8px;border:1px solid #ddd;'>{overall_counts['client_count']}</td>
                </tr>
                <tr>
                    <td style='padding:8px;border:1px solid #ddd;'><strong>Invoices Issued</strong></td>
                    <td style='padding:8px;border:1px solid #ddd;'>{overall_counts['invoice_count']}</td>
                </tr>
            </table>

            <h3>Activity by Sales User</h3>
            <table style='border-collapse:collapse;width:100%;'>
                <thead>
                    <tr>
                        <th style='padding:8px;border:1px solid #ddd;text-align:left;'>User</th>
                        <th style='padding:8px;border:1px solid #ddd;text-align:left;'>Roles</th>
                        <th style='padding:8px;border:1px solid #ddd;'>Leads</th>
                        <th style='padding:8px;border:1px solid #ddd;'>Prospects</th>
                        <th style='padding:8px;border:1px solid #ddd;'>Clients</th>
                        <th style='padding:8px;border:1px solid #ddd;'>Invoices</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>

            <p>This report was generated automatically by The Daily Market.</p>
        </body>
        </html>
        """

        try:
            _send_email(
                subject=subject,
                text_message=text_message,
                html_message=html_message,
                recipient=manager_user.email,
                recipient_name=manager_name,
            )
            emails_sent += 1

        except Exception as exc:
            logger.exception(
                "Daily management report failed for %s (%s)",
                manager_user.get_username(),
                manager_user.email,
            )
            recipients_failed.append({
                "recipient": manager_user.get_username(),
                "email": manager_user.email,
                "error": f"{type(exc).__name__}: {exc}",
            })
            # IMPORTANT: continue to the next manager.

    return {
        "date": str(report_date),
        "managers_found": managers_found,
        "emails_sent": emails_sent,
        "recipients_failed": recipients_failed,
    }


# ============================================================================
# DAILY QUEUE
# ============================================================================

def ensure_daily_sales_reports_queued():
    """
    Ensure today's supervisor and management reports exist in the queue.

    Representative reports are intentionally NOT queued at this stage.
    """

    now = timezone.localtime(timezone.now())
    today = now.date()

    # Today's scheduled execution time: 18:00 Johannesburg time.
    run_at = timezone.make_aware(
        datetime.combine(
            today,
            time(18, 0),
        ),
        timezone.get_current_timezone(),
    )

    tasks = [
        "send_daily_supervisor_sales_reports",
        "send_daily_manager_sales_reports",
    ]

    queued = []

    for task_name in tasks:
        try:
            schedule, created = DailyTaskSchedule.objects.get_or_create(
                date=today,
                task_name=task_name,
                defaults={
                    "run_at": run_at,
                    "status": DailyTaskSchedule.STATUS_PENDING,
                },
            )

        except IntegrityError:
            schedule = DailyTaskSchedule.objects.get(
                date=today,
                task_name=task_name,
            )
            created = False

        if created:
            queued.append({
                "task": task_name,
                "run_at": run_at.isoformat(),
                "status": schedule.status,
            })

    return {
        "queued": bool(queued),
        "date": str(today),
        "run_at": run_at.isoformat(),
        "tasks": queued,
    }
