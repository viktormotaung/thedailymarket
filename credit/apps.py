from django.apps import AppConfig


class CreditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "credit"

    def ready(self):
        # Register CreditAccount status-change email notifications.
        from . import signals  # noqa: F401