from django.db import models

class SupplierLead(models.Model):
    PRODUCT_TYPES = [
        ("poultry_whole", "Poultry — Whole"),
        ("poultry_portions", "Poultry — Portions"),
        ("eggs", "Eggs"),
        ("produce", "Produce"),
        ("dairy", "Dairy"),
        ("dry", "Dry Goods / Staples"),
        ("other", "Other"),
    ]

    full_name = models.CharField(max_length=255)
    business_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=64)
    location = models.CharField(max_length=255)
    product_type = models.CharField(max_length=32, choices=PRODUCT_TYPES)
    weekly_capacity = models.CharField(max_length=128)  # keep free-text for “1000 birds / 500kg”
    packaging = models.CharField(max_length=255, blank=True)
    certification_file = models.FileField(upload_to="certificates/", blank=True, null=True)
    delivery = models.CharField(max_length=16, choices=[("deliver","Deliver"),("collect","Collect"),("either","Either")])
    message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, default="Pending")

    def __str__(self):
        return f"{self.business_name} ({self.full_name})"
