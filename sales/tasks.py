from datetime import datetime, time, timedelta


from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from profiles.models import SalesRepProfile
from clients.models import Lead, Prospect, Client
from invoices.models import Invoice

from django.db import IntegrityError
from .models import DailyTaskSchedule



def send_daily_supervisor_sales_reports():
    """
    Send a daily sales activity summary to each supervisor.

    The report covers ONE calendar day only.

    Daily metrics:
        1. Sales Reps
        2. New Leads
        3. New Prospects
        4. New Clients
        5. Invoices Issued

    The supervisor hierarchy is determined by:

        SalesRepProfile.supervisor -> StaffProfile

    No role-code filtering is used.

    The report does NOT show individual lead, prospect or client
    records. It only provides counts.
    """

    # =============================================================
    # REPORT DATE
    # =============================================================

    now = timezone.localtime(timezone.now())
    report_date = now.date()

    # Start/end of the report day in the configured local timezone.
    day_start = timezone.make_aware(
        datetime.combine(report_date, time.min)
    )

    day_end = day_start + timedelta(days=1)

    emails_sent = 0
    supervisors_skipped = 0

    # =============================================================
    # FIND SUPERVISORS FROM THE ACTUAL SUPERVISOR RELATIONSHIP
    # =============================================================
    #
    # SalesRepProfile.supervisor points to StaffProfile.
    #
    # We first find all StaffProfiles that are being used as
    # supervisors by active sales profiles.
    #
    # =============================================================

    supervisor_staff_profiles = {}

    sales_profiles_with_supervisors = (
        SalesRepProfile.objects
        .filter(
            supervisor__isnull=False,
            user__is_active=True,
        )
        .select_related(
            "user",
            "staff_profile",
            "supervisor",
        )
    )

    for sales_profile in sales_profiles_with_supervisors:
        supervisor_staff_profile = sales_profile.supervisor

        if supervisor_staff_profile:
            supervisor_staff_profiles[
                supervisor_staff_profile.id
            ] = supervisor_staff_profile

    # =============================================================
    # PROCESS EACH SUPERVISOR
    # =============================================================

    for supervisor_staff_profile in supervisor_staff_profiles.values():

        # ---------------------------------------------------------
        # FIND THE SALES PROFILE FOR THE SUPERVISOR
        # ---------------------------------------------------------

        supervisor_profile = (
            SalesRepProfile.objects
            .filter(
                staff_profile=supervisor_staff_profile,
                user__is_active=True,
            )
            .select_related(
                "user",
                "staff_profile",
            )
            .first()
        )

        if not supervisor_profile:
            supervisors_skipped += 1
            continue

        supervisor_user = supervisor_profile.user

        # ---------------------------------------------------------
        # SUPERVISOR MUST HAVE AN EMAIL
        # ---------------------------------------------------------

        if not supervisor_user.email:
            supervisors_skipped += 1
            continue

        # =========================================================
        # FIND THIS SUPERVISOR'S TEAM
        # =========================================================
        #
        # IMPORTANT:
        #
        # We use the supervisor relationship directly.
        #
        # This means:
        #
        #     profile.supervisor == supervisor_staff_profile
        #
        # No role-code filtering.
        #
        # The existing data also has Victor linked to himself,
        # therefore Victor remains part of his team where applicable.
        #
        # =========================================================

        team_profiles = list(
            SalesRepProfile.objects
            .filter(
                supervisor=supervisor_staff_profile,
                user__is_active=True,
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

        # ---------------------------------------------------------
        # TEAM USER IDS
        # ---------------------------------------------------------

        team_user_ids = [
            profile.user_id
            for profile in team_profiles
            if profile.user_id
        ]

        # =========================================================
        # DAILY LEADS
        # =========================================================
        #
        # Count only leads CREATED today.
        #
        # We do not care whether they are currently active,
        # converted, or disqualified.
        #
        # The question is:
        #
        #     How many new leads entered the system today?
        #
        # =========================================================

        daily_leads = (
            Lead.objects
            .filter(
                assigned_to_id__in=team_user_ids,
                created_at__gte=day_start,
                created_at__lt=day_end,
            )
        )

        daily_lead_count = daily_leads.count()

        # =========================================================
        # DAILY PROSPECTS
        # =========================================================
        #
        # Count only prospects CREATED today.
        #
        # We do not use current status because this is a daily
        # activity report, not a current pipeline snapshot.
        #
        # =========================================================

        daily_prospects = (
            Prospect.objects
            .filter(
                owner_id__in=team_user_ids,
                created_at__gte=day_start,
                created_at__lt=day_end,
            )
        )

        daily_prospect_count = daily_prospects.count()

        # =========================================================
        # DAILY CLIENTS
        # =========================================================
        #
        # Count only clients CREATED today.
        #
        # =========================================================

        daily_clients = (
            Client.objects
            .filter(
                account_manager_id__in=team_user_ids,
                created_at__gte=day_start,
                created_at__lt=day_end,
            )
        )

        daily_client_count = daily_clients.count()

        # =========================================================
        # DAILY INVOICES
        # =========================================================
        #
        # Invoice uses invoice_date as the date the invoice was
        # issued.
        #
        # We therefore count invoices issued today.
        #
        # This is deliberately NOT based on paid_date.
        #
        # =========================================================

        daily_invoices = (
            Invoice.objects
            .filter(
                client__account_manager_id__in=team_user_ids,
                invoice_date=report_date,
            )
        )

        daily_invoice_count = daily_invoices.count()

        # =========================================================
        # TEAM SUMMARY
        # =========================================================

        summary = {
            "rep_count": len(team_profiles),
            "lead_count": daily_lead_count,
            "prospect_count": daily_prospect_count,
            "client_count": daily_client_count,
            "invoice_count": daily_invoice_count,
        }

        # =========================================================
        # PER-REP DAILY SUMMARY
        # =========================================================

        rep_summaries = []

        for rep_profile in team_profiles:

            rep_user_id = rep_profile.user_id

            rep_lead_count = (
                Lead.objects
                .filter(
                    assigned_to_id=rep_user_id,
                    created_at__gte=day_start,
                    created_at__lt=day_end,
                )
                .count()
            )

            rep_prospect_count = (
                Prospect.objects
                .filter(
                    owner_id=rep_user_id,
                    created_at__gte=day_start,
                    created_at__lt=day_end,
                )
                .count()
            )

            rep_client_count = (
                Client.objects
                .filter(
                    account_manager_id=rep_user_id,
                    created_at__gte=day_start,
                    created_at__lt=day_end,
                )
                .count()
            )

            rep_invoice_count = (
                Invoice.objects
                .filter(
                    client__account_manager_id=rep_user_id,
                    invoice_date=report_date,
                )
                .count()
            )

            rep_summaries.append(
                {
                    "rep": rep_profile.user,
                    "rep_profile": rep_profile,
                    "lead_count": rep_lead_count,
                    "prospect_count": rep_prospect_count,
                    "client_count": rep_client_count,
                    "invoice_count": rep_invoice_count,
                }
            )

        # =========================================================
        # EMAIL CONTEXT
        # =========================================================

        context = {
            "supervisor": supervisor_user,
            "supervisor_profile": supervisor_profile,
            "supervisor_staff_profile": supervisor_staff_profile,

            "report_date": report_date,
            "report_datetime": now,

            "team_profiles": team_profiles,
            "rep_summaries": rep_summaries,

            "summary": summary,
        }

        # =========================================================
        # RENDER HTML EMAIL
        # =========================================================

        html_message = render_to_string(
            "email/daily_supervisor_sales.html",
            context,
        )

        # =========================================================
        # PLAIN-TEXT FALLBACK
        # =========================================================

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
            f"Sales Reps: {summary['rep_count']}\n"
            f"New Leads: {summary['lead_count']}\n"
            f"New Prospects: {summary['prospect_count']}\n"
            f"New Clients: {summary['client_count']}\n"
            f"Invoices Issued: {summary['invoice_count']}\n\n"
            f"This report was generated automatically "
            f"by The Daily Market."
        )

        # =========================================================
        # EMAIL SUBJECT
        # =========================================================

        subject = (
            "Daily Sales Summary — "
            f"{report_date.strftime('%d %b %Y')}"
        )

        # =========================================================
        # BUILD EMAIL
        # =========================================================

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=getattr(
                settings,
                "DEFAULT_FROM_EMAIL",
                None,
            ),
            to=[
                supervisor_user.email,
            ],
        )

        email.attach_alternative(
            html_message,
            "text/html",
        )

        # =========================================================
        # SEND EMAIL
        # =========================================================

        email.send(
            fail_silently=False,
        )

        emails_sent += 1

    # =============================================================
    # RETURN TASK RESULT
    # =============================================================

    return {
        "date": str(report_date),
        "supervisors_found": len(
            supervisor_staff_profiles
        ),
        "emails_sent": emails_sent,
        "supervisors_skipped": supervisors_skipped,
    }



def send_daily_rep_sales_reports():
    """
    Send each active sales representative their own daily sales summary.

    Daily metrics:
        1. New Leads
        2. New Prospects
        3. New Clients
        4. Invoices Issued
        5. Total Activity

    The reporting day follows Africa/Johannesburg local time.
    """

    # ---------------------------------------------------------
    # CURRENT SOUTH AFRICAN DATE/TIME
    # ---------------------------------------------------------
    now = timezone.localtime(timezone.now())
    report_date = now.date()

    # ---------------------------------------------------------
    # DAY START / DAY END
    # ---------------------------------------------------------
    day_start = timezone.make_aware(
        datetime.combine(report_date, time.min)
    )

    day_end = day_start + timedelta(days=1)

    # ---------------------------------------------------------
    # GET ACTIVE SALES REPS
    # ---------------------------------------------------------
    sales_reps = (
        SalesRepProfile.objects
        .filter(
            status="active",
            user__is_active=True,
        )
        .select_related(
            "user",
            "staff_profile",
            "supervisor",
        )
        .prefetch_related("roles")
        .order_by("user__first_name", "user__last_name")
    )

    emails_sent = 0
    reps_skipped = 0

    # ---------------------------------------------------------
    # PROCESS EACH SALES REP
    # ---------------------------------------------------------
    for sales_rep in sales_reps:

        rep_user = sales_rep.user

        # -----------------------------------------------------
        # EMAIL VALIDATION
        # -----------------------------------------------------
        if not rep_user.email:
            reps_skipped += 1
            continue

        # -----------------------------------------------------
        # NEW LEADS TODAY
        # -----------------------------------------------------
        new_leads = Lead.objects.filter(
            assigned_to_id=rep_user.id,
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).count()

        # -----------------------------------------------------
        # NEW PROSPECTS TODAY
        # -----------------------------------------------------
        new_prospects = Prospect.objects.filter(
            owner_id=rep_user.id,
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).count()

        # -----------------------------------------------------
        # NEW CLIENTS TODAY
        # -----------------------------------------------------
        new_clients = Client.objects.filter(
            account_manager_id=rep_user.id,
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).count()

        # -----------------------------------------------------
        # INVOICES ISSUED TODAY
        # -----------------------------------------------------
        invoices_issued = Invoice.objects.filter(
            client__account_manager_id=rep_user.id,
            invoice_date=report_date,
        ).count()

        # -----------------------------------------------------
        # TOTAL DAILY ACTIVITY
        # -----------------------------------------------------
        total_activity = (
            new_leads
            + new_prospects
            + new_clients
            + invoices_issued
        )

        # -----------------------------------------------------
        # PREPARE SUMMARY
        # -----------------------------------------------------
        summary = {
            "new_leads": new_leads,
            "new_prospects": new_prospects,
            "new_clients": new_clients,
            "invoices_issued": invoices_issued,
            "total_activity": total_activity,
        }

        # -----------------------------------------------------
        # PIPELINE SUMMARY
        # -----------------------------------------------------
        pipeline = {
            "leads": new_leads,
            "prospects": new_prospects,
            "clients": new_clients,
        }

        # -----------------------------------------------------
        # TOMORROW'S FOCUS MESSAGE
        # -----------------------------------------------------
        if new_leads > 0 and new_prospects == 0:
            focus_message = (
                "Focus tomorrow on progressing your new leads "
                "into prospects."
            )

        elif new_prospects > 0 and new_clients == 0:
            focus_message = (
                "Focus tomorrow on converting your prospects "
                "into new clients."
            )

        elif new_clients > 0:
            focus_message = (
                "Good progress today. Keep building your pipeline "
                "and growing your client base."
            )

        elif total_activity == 0:
            focus_message = (
                "Focus tomorrow on building your pipeline through "
                "new leads, prospects and client opportunities."
            )

        else:
            focus_message = (
                "Keep building your pipeline and converting "
                "opportunities into clients."
            )

        # -----------------------------------------------------
        # EMAIL CONTEXT
        # -----------------------------------------------------
        context = {
            "rep": rep_user,
            "sales_rep": sales_rep,
            "report_date": report_date,
            "report_datetime": now,
            "summary": summary,
            "pipeline": pipeline,
            "focus_message": focus_message,
        }

        # -----------------------------------------------------
        # RENDER HTML EMAIL
        # -----------------------------------------------------
        html_message = render_to_string(
            "email/daily_rep_sales.html",
            context,
        )

        # -----------------------------------------------------
        # PLAIN TEXT FALLBACK
        # -----------------------------------------------------
        text_message = (
            f"The Daily Market\n"
            f"Daily Sales Summary\n\n"
            f"Good evening {rep_user.get_full_name() or rep_user.username},\n\n"
            f"Here is your sales activity for {report_date}.\n\n"
            f"New Leads: {new_leads}\n"
            f"New Prospects: {new_prospects}\n"
            f"New Clients: {new_clients}\n"
            f"Invoices Issued: {invoices_issued}\n"
            f"Total Activity: {total_activity}\n\n"
            f"Pipeline Today:\n"
            f"{new_leads} Leads -> "
            f"{new_prospects} Prospects -> "
            f"{new_clients} Clients\n\n"
            f"Tomorrow's Focus:\n"
            f"{focus_message}\n"
        )

        # -----------------------------------------------------
        # SEND EMAIL
        # -----------------------------------------------------
        subject = f"Daily Sales Summary — {report_date}"

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[rep_user.email],
        )

        email.attach_alternative(
            html_message,
            "text/html",
        )

        email.send()

        emails_sent += 1

    # ---------------------------------------------------------
    # TASK RESULT
    # ---------------------------------------------------------
    return {
        "date": str(report_date),
        "sales_reps_found": sales_reps.count(),
        "emails_sent": emails_sent,
        "reps_skipped": reps_skipped,
    }


def ensure_daily_sales_reports_queued():
    """
    Ensure today's daily sales reports exist in the Django database queue.

    This function does NOT execute the reports and does NOT use Celery.
    It only creates the database queue records if they do not already exist.
    """

    from datetime import datetime, time

    from django.db import IntegrityError
    from django.utils import timezone

    from .models import DailyTaskSchedule

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
        (
            "send_daily_supervisor_sales_reports",
            send_daily_supervisor_sales_reports,
        ),
        (
            "send_daily_rep_sales_reports",
            send_daily_rep_sales_reports,
        ),
    ]

    queued = []

    for task_name, task_function in tasks:

        # The explicit task name is used as the unique identifier
        # for the daily queue entry.

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
            # Another login may have created the same queue entry
            # at exactly the same time.
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


