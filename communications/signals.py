from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from clients.models import Client
from communications.services.whatsapp import send_client_activation_whatsapp


@receiver(pre_save, sender=Client)
def client_pre_save(sender, instance, **kwargs):
    """
    Determine whether this Client is changing to ACTIVE.
    """

    instance._whatsapp_activation_trigger = False

    if not instance.pk:
        # A newly-created ACTIVE client should also trigger the welcome.
        if instance.status == "ACTIVE":
            instance._whatsapp_activation_trigger = True
        return

    old_status = (
        sender.objects
        .filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )

    if old_status != "ACTIVE" and instance.status == "ACTIVE":
        instance._whatsapp_activation_trigger = True


@receiver(post_save, sender=Client)
def client_post_save(sender, instance, created, **kwargs):
    """
    Send the activation WhatsApp after the Client has successfully
    been saved.
    """

    if not getattr(instance, "_whatsapp_activation_trigger", False):
        return

    send_client_activation_whatsapp(instance)