from django.contrib.contenttypes.models import ContentType

from tasks.models import Task
from profiles.models import Department


def create_order_verification_task(order):

    accounts_department = Department.objects.get(
        name__iexact="Accounts"


    )

    if Task.objects.filter(
        task_type=Task.TaskType.ORDER_FOLLOW_UP,
        content_type=ContentType.objects.get_for_model(order),
        object_id=order.pk,
    ).exists():
        return

    Task.objects.create(
        title=f"Verify Stock for Order #{order.pk}",

        description=(
            "Verify stock availability and ensure all "
            "ordered items can be fulfilled before approval."
        ),

        priority=Task.Priority.URGENT,
        status=Task.Status.PENDING,

        task_type=Task.TaskType.ORDER_FOLLOW_UP,
        source=Task.Source.SYSTEM,

        department=accounts_department,

        created_by=order.created_by,

        content_type=ContentType.objects.get_for_model(order),
        object_id=order.pk,
    )