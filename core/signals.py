
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model


User = get_user_model()


@receiver(post_save, sender=User)
def sync_user_to_dummy(sender, instance, created, **kwargs):
    """
    Sync user from DEFAULT DB → DUMMY DB.

    Rules:
    - Only users saved to the DEFAULT database are synchronized.
    - First try to find the corresponding user in DUMMY by ID.
    - If no user is found by ID, try to find an existing user by username.
    - If an existing user is found, update it.
    - Only create a new user in DUMMY if no matching user exists.
    """

    # ONLY SYNC IF SAVED IN DEFAULT
    if instance._state.db != "default":
        return

    print("\n===== USER SYNC TRIGGERED =====")
    print(f"User: {instance.email}")
    print(f"DB: {instance._state.db}")
    print("===============================\n")

    # ---------------------------------------------------------
    # 1. FIRST CHECK: DOES THE USER EXIST IN DUMMY BY ID?
    # ---------------------------------------------------------
    user_dummy = (
        User.objects
        .using("dummy")
        .filter(id=instance.id)
        .first()
    )

    # ---------------------------------------------------------
    # 2. SECOND CHECK: DOES THE USER EXIST BY USERNAME?
    # ---------------------------------------------------------
    if not user_dummy:
        user_dummy = (
            User.objects
            .using("dummy")
            .filter(username=instance.username)
            .first()
        )

    # ---------------------------------------------------------
    # 3. UPDATE EXISTING USER
    # ---------------------------------------------------------
    if user_dummy:
        print("Updating existing user in DUMMY")

        user_dummy.username = instance.username
        user_dummy.email = instance.email
        user_dummy.password = instance.password
        user_dummy.is_active = instance.is_active
        user_dummy.is_staff = instance.is_staff
        user_dummy.is_superuser = instance.is_superuser

        user_dummy.save(using="dummy")

        print(
            f"User synchronized successfully: "
            f"{instance.username}"
        )

    # ---------------------------------------------------------
    # 4. CREATE NEW USER
    # ---------------------------------------------------------
    else:
        print("Creating new user in DUMMY")

        User.objects.using("dummy").create(
            id=instance.id,
            username=instance.username,
            email=instance.email,
            password=instance.password,
            is_active=instance.is_active,
            is_staff=instance.is_staff,
            is_superuser=instance.is_superuser,
        )

        print(
            f"User created successfully in DUMMY: "
            f"{instance.username}"
        )