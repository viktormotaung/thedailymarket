from django.contrib.auth import get_user_model


def create_user_in_both_databases(**data):
    User = get_user_model()

    password = data.pop("password", None)

    # 🔹 Create in default DB
    user_default = User.objects.using("default").create(**data)

    if password:
        user_default.set_password(password)
        user_default.save(using="default")

    # 🔹 Create in dummy DB (same ID)
    user_dummy = User.objects.using("dummy").create(
        id=user_default.id,
        **data
    )

    if password:
        user_dummy.set_password(password)
        user_dummy.save(using="dummy")

    return user_default