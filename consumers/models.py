from django.conf import settings
from django.db import models

class Consumer(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="consumer",
    )

    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)

    phone = models.CharField(max_length=50, blank=True)

    id_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional SA ID number (future verification / credit)."
    )

    date_of_birth = models.DateField(null=True, blank=True)

    is_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
