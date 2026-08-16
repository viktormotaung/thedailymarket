from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import core.signals

        from django.contrib.auth.models import User

        def user_str(self):
            full_name = f"{self.first_name} {self.last_name}".strip()
            return full_name if full_name else self.username

        User.__str__ = user_str