from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()


@receiver(post_save, sender=User)
def sync_user_to_dummy(sender, instance, created, **kwargs):
    """
    Sync user from DEFAULT DB → DUMMY DB
    """

    # 🔥 ONLY SYNC IF SAVED IN DEFAULT
    if instance._state.db != "default":
        return

    print("\n===== USER SYNC TRIGGERED =====")
    print(f"User: {instance.email}")
    print(f"DB: {instance._state.db}")
    print("===============================\n")

    # 🔍 CHECK IF USER EXISTS IN DUMMY
    user_dummy = User.objects.using("dummy").filter(id=instance.id).first()

    if user_dummy:
        print("Updating existing user in DUMMY")

        user_dummy.username = instance.username
        user_dummy.email = instance.email
        user_dummy.password = instance.password
        user_dummy.is_active = instance.is_active
        user_dummy.is_staff = instance.is_staff
        user_dummy.is_superuser = instance.is_superuser

        user_dummy.save(using="dummy")

    else:
        print("Creating new user in DUMMY")

        User.objects.using("dummy").create(
            id=instance.id,  # 🔥 VERY IMPORTANT
            username=instance.username,
            email=instance.email,
            password=instance.password,
            is_active=instance.is_active,
            is_staff=instance.is_staff,
            is_superuser=instance.is_superuser,
        )