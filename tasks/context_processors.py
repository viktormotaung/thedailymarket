# tasks/context_processors.py
# tasks/context_processors.py
from django.db.utils import OperationalError, ProgrammingError

from tasks.models import Notification


def notification_context(request):
    if not request.user.is_authenticated:
        return {}

    try:
        user = request.user

        individual_qs = Notification.objects.filter(
            scope=Notification.Scope.INDIVIDUAL,
            recipient=user,
        )

        staff = getattr(user, "staff_profile", None)
        department_qs = Notification.objects.none()

        if staff and staff.status == "active" and staff.departments:
            department_qs = Notification.objects.filter(
                scope=Notification.Scope.DEPARTMENT,
                department=staff.departments,
            )

        notifications = (
            (individual_qs | department_qs)
            .order_by("-created_at")
            .distinct()[:10]
        )

        unread_count = (
            individual_qs.filter(is_opened=False).count()
            + department_qs.filter(is_opened=False).count()
        )

        ticket_count = (
            individual_qs.filter(
                notification_type=Notification.NotificationType.TICKET,
                is_opened=False,
            ).count()
            + department_qs.filter(
                notification_type=Notification.NotificationType.TICKET,
                is_opened=False,
            ).count()
        )

        task_count = (
            individual_qs.filter(
                notification_type=Notification.NotificationType.TASK,
                is_opened=False,
            ).count()
            + department_qs.filter(
                notification_type=Notification.NotificationType.TASK,
                is_opened=False,
            ).count()
        )

        return {
            "nav_notifications": notifications,
            "nav_unread_notifications_count": unread_count,
            "nav_unopened_ticket_count": ticket_count,
            "nav_unopened_task_count": task_count,
        }

    except (ProgrammingError, OperationalError):
        return {
            "nav_notifications": [],
            "nav_unread_notifications_count": 0,
            "nav_unopened_ticket_count": 0,
            "nav_unopened_task_count": 0,
        }