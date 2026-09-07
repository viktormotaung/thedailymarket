
from django.contrib import admin, messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html
from django.utils import timezone

from .models import JobApplication, DailyTaskSchedule


# ============================================================
# JOB APPLICATIONS
# ============================================================

@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):

    list_display = (
        "first_name",
        "surname",
        "age",
        "gender",
        "race",
        "territory",
        "current_location",
        "application_status",
        "overall_rating",
        "submitted_at",
    )

    list_editable = (
        "application_status",
        "overall_rating",
    )

    list_filter = (
        "territory",
        "application_status",
        "gender",
        "race",
        "comfortable_performance_environment",
        "has_drivers_license",
        "has_vehicle_access",
        "submitted_at",
    )

    search_fields = (
        "first_name",
        "surname",
        "email",
        "phone_number",
        "whatsapp_number",
        "current_location",
        "territory_understanding",
        "potential_client_types",
    )

    ordering = (
        "-overall_rating",
        "-submitted_at",
    )

    list_per_page = 25
    date_hierarchy = "submitted_at"

    readonly_fields = (
        "submitted_at",
        "updated_at",
    )

    fieldsets = (
        ("Application Status", {
            "fields": (
                "application_status",
                "overall_rating",
                "evaluator_notes",
            )
        }),

        ("Territory", {
            "fields": (
                "territory",
            )
        }),

        ("Basic Personal Information", {
            "fields": (
                "first_name",
                "surname",
                "age",
                "race",
                "gender",
                "phone_number",
                "whatsapp_number",
                "email",
                "current_location",
                "year_matriculated",
                "qualifications",
                "current_employment_status",
                "availability_to_start",
            )
        }),

        ("Transport & Resources", {
            "fields": (
                "has_drivers_license",
                "has_vehicle_access",
                "has_smartphone",
            )
        }),

        ("Territory & Commercial Thinking", {
            "fields": (
                "territory_understanding",
                "potential_client_types",
                "first_30_day_strategy",
            )
        }),

        ("Sales & Problem Solving", {
            "fields": (
                "cheaper_supplier_response",
                "client_retention_strategy",
                "target_pressure_response",
            )
        }),

        ("Leadership & Accountability", {
            "fields": (
                "leadership_experience",
                "unsupervised_problem_solving",
                "performance_environment_understanding",
            )
        }),

        ("Startup & Culture Fit", {
            "fields": (
                "startup_interest_reason",
                "comfortable_performance_environment",
                "motivation",
            )
        }),

        ("Optional Video Submission", {
            "fields": (
                "introduction_video_link",
            )
        }),

        ("Internal Scoring", {
            "fields": (
                "territory_fit_score",
                "communication_score",
                "commercial_thinking_score",
                "leadership_potential_score",
                "startup_fit_score",
            )
        }),

        ("System Fields", {
            "fields": (
                "submitted_at",
                "updated_at",
            )
        }),
    )


# ============================================================
# DAILY TASK QUEUE
# ============================================================

@admin.register(DailyTaskSchedule)
class DailyTaskScheduleAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "date",
        "task_name",
        "run_at",
        "status_display",
        "attempts",
        "queued_at",
        "started_at",
        "executed_at",
        "failed_at",
    )

    list_filter = (
        "status",
        "date",
        "task_name",
    )

    search_fields = (
        "task_name",
        "error_message",
    )

    readonly_fields = (
        "queued_at",
        "started_at",
        "executed_at",
        "failed_at",
        "error_message",
    )

    ordering = (
        "-date",
        "run_at",
        "id",
    )

    list_per_page = 50

    actions = (
        "run_selected_tasks",
        "reset_failed_tasks",
    )

    def status_display(self, obj):
        """
        Display queue status with a simple visual indicator.
        """

        if obj.status == DailyTaskSchedule.STATUS_COMPLETED:
            return format_html(
                '<strong style="color: green;">✓ COMPLETED</strong>'
            )

        if obj.status == DailyTaskSchedule.STATUS_FAILED:
            return format_html(
                '<strong style="color: red;">✗ FAILED</strong>'
            )

        if obj.status == DailyTaskSchedule.STATUS_RUNNING:
            return format_html(
                '<strong style="color: #d97706;">● RUNNING</strong>'
            )

        return format_html(
            '<strong style="color: #2563eb;">● PENDING</strong>'
        )

    status_display.short_description = "Status"

    # ========================================================
    # ADMIN ACTION: RUN SELECTED TASKS
    # ========================================================

    @admin.action(description="Run selected queue tasks now")
    def run_selected_tasks(self, request, queryset):

        from sales.tasks import (
            send_daily_supervisor_sales_reports,
            send_daily_rep_sales_reports,
        )

        task_functions = {
            "send_daily_supervisor_sales_reports":
                send_daily_supervisor_sales_reports,

            "send_daily_rep_sales_reports":
                send_daily_rep_sales_reports,
        }

        processed = 0
        completed = 0
        failed = 0

        for schedule in queryset:

            task_function = task_functions.get(
                schedule.task_name
            )

            if task_function is None:

                schedule.status = (
                    DailyTaskSchedule.STATUS_FAILED
                )

                schedule.failed_at = timezone.now()

                schedule.error_message = (
                    f"Unknown queue task: "
                    f"{schedule.task_name}"
                )

                schedule.save(
                    update_fields=[
                        "status",
                        "failed_at",
                        "error_message",
                    ]
                )

                failed += 1
                processed += 1
                continue

            try:

                schedule.status = (
                    DailyTaskSchedule.STATUS_RUNNING
                )

                schedule.attempts += 1
                schedule.started_at = timezone.now()
                schedule.error_message = None

                schedule.save(
                    update_fields=[
                        "status",
                        "attempts",
                        "started_at",
                        "error_message",
                    ]
                )

                task_function()

                schedule.status = (
                    DailyTaskSchedule.STATUS_COMPLETED
                )

                schedule.executed_at = timezone.now()
                schedule.failed_at = None
                schedule.error_message = None

                schedule.save(
                    update_fields=[
                        "status",
                        "executed_at",
                        "failed_at",
                        "error_message",
                    ]
                )

                completed += 1

            except Exception as exc:

                schedule.status = (
                    DailyTaskSchedule.STATUS_FAILED
                )

                schedule.failed_at = timezone.now()

                schedule.error_message = (
                    f"{type(exc).__name__}: {exc}"
                )

                schedule.save(
                    update_fields=[
                        "status",
                        "failed_at",
                        "error_message",
                    ]
                )

                failed += 1

            processed += 1

        if completed:
            self.message_user(
                request,
                f"{completed} queue task(s) completed successfully.",
                messages.SUCCESS,
            )

        if failed:
            self.message_user(
                request,
                f"{failed} queue task(s) failed. "
                f"Check the task record for the error.",
                messages.ERROR,
            )

    # ========================================================
    # ADMIN ACTION: RESET FAILED TASKS
    # ========================================================

    @admin.action(description="Reset failed tasks to pending")
    def reset_failed_tasks(self, request, queryset):

        now = timezone.now()

        updated = queryset.filter(
            status=DailyTaskSchedule.STATUS_FAILED
        ).update(
            status=DailyTaskSchedule.STATUS_PENDING,
            run_at=now,
            failed_at=None,
            error_message=None,
        )

        if updated:
            self.message_user(
                request,
                f"{updated} failed task(s) reset to PENDING.",
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "No failed tasks were selected.",
                messages.WARNING,
            )

    # ========================================================
    # ADMIN URL: RUN QUEUE
    # ========================================================

    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [
            path(
                "run-queue/",
                self.admin_site.admin_view(
                    self.run_queue
                ),
                name="daily_task_schedule_run_queue",
            ),
        ]

        return custom_urls + urls

    def run_queue(self, request):
        """
        Run the same database queue processor used by
        Windows Task Scheduler.
        """

        from django.core.management import call_command

        try:

            call_command(
                "process_task_queue"
            )

            self.message_user(
                request,
                "Task queue processed successfully.",
                messages.SUCCESS,
            )

        except Exception as exc:

            self.message_user(
                request,
                f"Task queue processing failed: {exc}",
                messages.ERROR,
            )

        return redirect(
            "admin:sales_dailytaskschedule_changelist"
        )
