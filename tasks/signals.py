# tasks/signals.py

@receiver(post_save, sender=Ticket)
def ticket_created(sender, instance, created, **kwargs):

    if created:
        notify_department_new_ticket.delay(instance.pk)