from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from sales.models import DailyTaskSchedule
from sales.tasks import (
    send_daily_supervisor_sales_reports,
    send_daily_manager_sales_reports,
)


TASK_FUNCTIONS = {
    "send_daily_supervisor_sales_reports": send_daily_supervisor_sales_reports,
    "send_daily_manager_sales_reports": send_daily_manager_sales_reports,
}


class Command(BaseCommand):
    help = "Process pending daily tasks from the database queue."

    def handle(self, *args, **options):
        now = timezone.now()

        processed = 0
        completed = 0
        failed = 0

        while True:
            task = None

            with transaction.atomic():
                # Find the next pending task that is due.
                task = (
                    DailyTaskSchedule.objects
                    .select_for_update(skip_locked=True)
                    .filter(
                        status=DailyTaskSchedule.STATUS_PENDING,
                        run_at__lte=now,
                    )
                    .order_by("run_at", "id")
                    .first()
                )

                if not task:
                    break

                # Mark the task as running before executing it.
                task.status = DailyTaskSchedule.STATUS_RUNNING
                task.attempts += 1
                task.started_at = timezone.now()
                task.error_message = ""
                task.save(
                    update_fields=[
                        "status",
                        "attempts",
                        "started_at",
                        "error_message",
                    ]
                )

            processed += 1

            self.stdout.write(
                f"Running task: {task.task_name} "
                f"(ID: {task.id})"
            )

            # Resolve the actual Python function for this task.
            task_function = TASK_FUNCTIONS.get(task.task_name)

            if not task_function:
                error_message = (
                    f"Unknown task: {task.task_name}"
                )

                DailyTaskSchedule.objects.filter(
                    pk=task.pk
                ).update(
                    status=DailyTaskSchedule.STATUS_FAILED,
                    failed_at=timezone.now(),
                    error_message=error_message,
                )

                failed += 1

                self.stdout.write(
                    self.style.ERROR(
                        f"FAILED: {error_message}"
                    )
                )

                continue

            try:
                # Execute the task.
                task_function()

                # Mark the task as completed.
                DailyTaskSchedule.objects.filter(
                    pk=task.pk
                ).update(
                    status=DailyTaskSchedule.STATUS_COMPLETED,
                    executed_at=timezone.now(),
                    error_message="",
                )

                completed += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"COMPLETED: {task.task_name}"
                    )
                )

            except Exception as exc:
                error_message = str(exc)

                DailyTaskSchedule.objects.filter(
                    pk=task.pk
                ).update(
                    status=DailyTaskSchedule.STATUS_FAILED,
                    failed_at=timezone.now(),
                    error_message=error_message,
                )

                failed += 1

                self.stdout.write(
                    self.style.ERROR(
                        f"FAILED: {task.task_name} - {error_message}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            f"Processed: {processed}"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed: {completed}"
            )
        )
        self.stdout.write(
            self.style.ERROR(
                f"Failed: {failed}"
            )
        )