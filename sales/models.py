from django.db import models


class SalesJobApplication(models.Model):
    # =========================
    # BASIC PERSONAL INFO
    # =========================
    INTERVIEW_STATUS_CHOICES = [
        ("NONE", "Not Invited"),
        ("INVITED", "Invited to Interview"),
        ("BOOKED", "Interview Booked"),
        ("COMPLETED", "Interview Completed"),
    ]

    interview_status = models.CharField(
        max_length=20,
        choices=INTERVIEW_STATUS_CHOICES,
        default="NONE"
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    email = models.EmailField(
        max_length=254,
        help_text="Primary contact email address"
    )

    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=100)

    province = models.CharField(max_length=100)
    suburb = models.CharField(max_length=150)
    town_or_city = models.CharField(max_length=150)

    where_grew_up = models.CharField(
        max_length=255,
        help_text="Town / area where the applicant grew up",
    )

    # =========================
    # SALES BACKGROUND
    # =========================
    sales_experience_summary = models.TextField(
        help_text="Overall sales experience summary"
    )

    previous_workplaces = models.TextField(
        help_text="Places they have worked before"
    )

    responsibilities = models.TextField(
        help_text="Key responsibilities held in previous roles"
    )

    lessons_learned = models.TextField(
        help_text="What they learned from previous roles"
    )

    # =========================
    # SALES THINKING (VERY IMPORTANT)
    # =========================
    client_identification_strategy = models.TextField(
        help_text="How they would identify potential clients"
    )

    pitching_strategy = models.TextField(
        help_text="How they would pitch FMCG products"
    )

    conversion_strategy = models.TextField(
        help_text="How they convert prospects into customers"
    )

    client_management_strategy = models.TextField(
        help_text="How they manage and retain clients"
    )

    # =========================
    # RESOURCES & TOOLS
    # =========================
    resources_needed = models.TextField(
        help_text="Resources they believe they need to perform well"
    )

    has_drivers_license = models.BooleanField(default=False)
    has_vehicle_access = models.BooleanField(default=False)
    has_laptop_or_tablet = models.BooleanField(default=False)

    # =========================
    # WORK STYLE & FIT
    # =========================
    can_work_in_team = models.BooleanField(default=True)

    leadership_skills_description = models.TextField(
        help_text="Leadership experience or skills",
        blank=True,
    )

    comfortable_township_clients = models.BooleanField(default=False)
    comfortable_suburban_clients = models.BooleanField(default=False)

    comfortable_remote_work = models.BooleanField(default=False)
    comfortable_startup_environment = models.BooleanField(default=False)

    # =========================
    # CURRENT STATUS
    # =========================
    current_job = models.CharField(
        max_length=255,
        blank=True,
        help_text="Current job, if any",
    )

    availability_to_start = models.CharField(
        max_length=100,
        help_text="How soon they can start (e.g. immediately, 2 weeks)",
    )

    # =========================
    # SYSTEM FIELDS
    # =========================
    submitted_at = models.DateTimeField(auto_now_add=True)

    reviewed = models.BooleanField(default=False)
    shortlisted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
