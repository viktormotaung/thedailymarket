from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=get_user_model())
def sync_user_to_dummy(sender, instance, created, **kwargs):
    """
    🔥 AUTO-SYNC USER FROM DEFAULT → DUMMY
    """

    # Only act if saved in default DB
    if instance._state.db != "default":
        return

    User = get_user_model()

    try:
        existing = User.objects.using("dummy").filter(pk=instance.pk).first()

        if existing:
            # 🔁 UPDATE EXISTING USER
            existing.username = instance.username
            existing.email = instance.email
            existing.password = instance.password
            existing.is_active = instance.is_active
            existing.is_staff = instance.is_staff
            existing.is_superuser = instance.is_superuser

            existing.save(using="dummy")

            print(f"🔁 Synced existing user to dummy: {instance.email}")

        else:
            # 🆕 CREATE NEW USER IN DUMMY
            User.objects.using("dummy").create(
                id=instance.id,  # 🔥 CRITICAL: same ID
                username=instance.username,
                email=instance.email,
                password=instance.password,
                is_active=instance.is_active,
                is_staff=instance.is_staff,
                is_superuser=instance.is_superuser,
            )

            print(f"✅ Created user in dummy: {instance.email}")

    except Exception as e:
        print(f"❌ User sync failed: {e}")