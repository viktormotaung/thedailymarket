from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from sales.models import DailyTaskSchedule
from sales.tasks import (
    send_daily_supervisor_sales_reports,
    send_daily_rep_sales_reports,
)


TASK_FUNCTIONS = {
    "send_daily_supervisor_sales_reports": send_daily_supervisor_sales_reports,
    "send_daily_rep_sales_reports": send_daily_rep_sales_reports,
}


class Command(BaseCommand):
    help = "Process pending Daily Market database queue tasks."

    def handle(self, *args, **options):

        now = timezone.now()

        self.stdout.write(
            f"Checking task queue at {timezone.localtime(now)}"
        )

        # ---------------------------------------------------------
        # Find tasks that are due.
        # ---------------------------------------------------------

        pending_tasks = DailyTaskSchedule.objects.filter(
            status=DailyTaskSchedule.STATUS_PENDING,
            run_at__lte=now,
        ).order_by(
            "run_at",
            "id",
        )

        processed = 0
        completed = 0
        failed = 0

        for schedule_id in pending_tasks.values_list(
            "id",
            flat=True,
        ):

            # -----------------------------------------------------
            # Lock this queue record before processing it.
            # -----------------------------------------------------

            with transaction.atomic():

                try:
                    schedule = (
                        DailyTaskSchedule.objects
                        .select_for_update()
                        .get(
                            id=schedule_id,
                            status=DailyTaskSchedule.STATUS_PENDING,
                        )
                    )
                except DailyTaskSchedule.DoesNotExist:
                    continue

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

            # -----------------------------------------------------
            # Find the actual Python function.
            # -----------------------------------------------------

            task_function = TASK_FUNCTIONS.get(
                schedule.task_name
            )

            if task_function is None:

                error_message = (
                    f"Unknown queue task: "
                    f"{schedule.task_name}"
                )

                DailyTaskSchedule.objects.filter(
                    id=schedule.id
                ).update(
                    status=DailyTaskSchedule.STATUS_FAILED,
                    failed_at=timezone.now(),
                    error_message=error_message,
                )

                self.stdout.write(
                    self.style.ERROR(
                        error_message
                    )
                )

                failed += 1
                processed += 1
                continue

            # -----------------------------------------------------
            # Execute the task.
            # -----------------------------------------------------

            self.stdout.write(
                f"Running: {schedule.task_name}"
            )

            try:

                task_function()

                # -------------------------------------------------
                # Mark as completed.
                # -------------------------------------------------

                DailyTaskSchedule.objects.filter(
                    id=schedule.id
                ).update(
                    status=DailyTaskSchedule.STATUS_COMPLETED,
                    executed_at=timezone.now(),
                    error_message=None,
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Completed: {schedule.task_name}"
                    )
                )

                completed += 1

            except Exception as exc:

                error_message = (
                    f"{type(exc).__name__}: {exc}"
                )

                DailyTaskSchedule.objects.filter(
                    id=schedule.id
                ).update(
                    status=DailyTaskSchedule.STATUS_FAILED,
                    failed_at=timezone.now(),
                    error_message=error_message,
                )

                self.stdout.write(
                    self.style.ERROR(
                        f"FAILED: {schedule.task_name}"
                    )
                )

                self.stdout.write(
                    self.style.ERROR(
                        error_message
                    )
                )

                failed += 1

            processed += 1

        # ---------------------------------------------------------
        # Summary
        # ---------------------------------------------------------

        self.stdout.write("")
        self.stdout.write("Task queue processing complete.")
        self.stdout.write(f"Processed: {processed}")
        self.stdout.write(f"Completed: {completed}")
        self.stdout.write(f"Failed: {failed}")