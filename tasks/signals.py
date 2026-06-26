# tasks/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType

from .models import (
    Task,
    Ticket,
    Notification,
)



@receiver(post_save, sender=Ticket)
def create_ticket_notification(sender, instance, created, **kwargs):

    if not created:
        return

    if not instance.department:
        return

    Notification.objects.create(
        scope=Notification.Scope.DEPARTMENT,
        department=instance.department,
        notification_type=Notification.NotificationType.TICKET,
        content_type=ContentType.objects.get_for_model(instance),
        object_id=instance.pk,
    )


@receiver(post_save, sender=Task)
def create_task_notification(sender, instance, created, **kwargs):

    if not created:
        return

    content_type = ContentType.objects.get_for_model(instance)

    # Assigned to a specific person
    if instance.assigned_to:

        Notification.objects.create(
            scope=Notification.Scope.INDIVIDUAL,
            recipient=instance.assigned_to,
            notification_type=Notification.NotificationType.TASK,
            content_type=content_type,
            object_id=instance.pk,
        )

    # Department task
    elif instance.department:

        Notification.objects.create(
            scope=Notification.Scope.DEPARTMENT,
            department=instance.department,
            notification_type=Notification.NotificationType.TASK,
            content_type=content_type,
            object_id=instance.pk,
        )