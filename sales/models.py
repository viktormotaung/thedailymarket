from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db import transaction





class JobApplication(models.Model):

    RACE_CHOICES = [
        ("AFRICAN", "African / Black"),
        ("COLOURED", "Coloured"),
        ("INDIAN", "Indian / Asian"),
        ("WHITE", "White"),
        ("OTHER", "Other"),
        ("PREFER_NOT_TO_SAY", "Prefer Not To Say"),
    ]

    GENDER_CHOICES = [
        ("MALE", "Male"),
        ("FEMALE", "Female"),
        ("OTHER", "Other"),
        ("PREFER_NOT_TO_SAY", "Prefer Not To Say"),
    ]

    # =========================================================
    # TERRITORY
    # =========================================================

    TERRITORY_CHOICES = [
        ("SOUTH_WEST", "South / West"),
        ("NORTH_CENTRAL", "North / Central"),
    ]

    territory = models.CharField(
        max_length=30,
        choices=TERRITORY_CHOICES,
    )

    # =========================================================
    # BASIC PERSONAL INFORMATION
    # =========================================================

    first_name = models.CharField(max_length=100)

    surname = models.CharField(max_length=100)

    age = models.PositiveIntegerField()

    # =========================================================
    # DEMOGRAPHICS
    # =========================================================

    

    race = models.CharField(
        max_length=30,
        choices=RACE_CHOICES,
        blank=True,
    )

    gender = models.CharField(
        max_length=30,
        choices=GENDER_CHOICES,
        blank=True,
    )
    
    phone_number = models.CharField(
        max_length=30,
    )

    whatsapp_number = models.CharField(
        max_length=30,
        blank=True,
    )

    email = models.EmailField()

    current_location = models.CharField(
        max_length=255,
        help_text="Current suburb / township / area where applicant lives",
    )

    year_matriculated = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    qualifications = models.TextField(
        blank=True,
        help_text="Qualifications, certificates or courses completed",
    )

    current_employment_status = models.CharField(
        max_length=255,
        blank=True,
    )

    availability_to_start = models.CharField(
        max_length=100,
        help_text="Example: Immediately, 2 weeks, 1 month",
    )

    # =========================================================
    # TRANSPORT & RESOURCES
    # =========================================================

    has_drivers_license = models.BooleanField(
        default=False,
    )

    has_vehicle_access = models.BooleanField(
        default=False,
    )

    has_smartphone = models.BooleanField(
        default=True,
    )

    # =========================================================
    # TERRITORY & COMMERCIAL THINKING
    # =========================================================

    territory_understanding = models.TextField(
        help_text=(
            "Name areas, trader zones or business hubs "
            "within your territory where you believe "
            "The Daily Market could find clients."
        )
    )

    potential_client_types = models.TextField(
        help_text=(
            "What type of businesses or traders do you think "
            "would benefit most from The Daily Market?"
        )
    )

    first_30_day_strategy = models.TextField(
        help_text=(
            "If you had to secure 10 recurring clients "
            "within 30 days, what would your approach be?"
        )
    )

    # =========================================================
    # SALES & PROBLEM SOLVING
    # =========================================================

    cheaper_supplier_response = models.TextField(
        help_text=(
            "A client says another supplier is cheaper "
            "than The Daily Market. What would you do?"
        )
    )

    client_retention_strategy = models.TextField(
        help_text=(
            "A client buys once and never orders again. "
            "How would you handle this situation?"
        )
    )

    target_pressure_response = models.TextField(
        help_text=(
            "You have not reached your target and only "
            "7 days remain in the month. What would you do?"
        )
    )

    # =========================================================
    # LEADERSHIP & ACCOUNTABILITY
    # =========================================================

    leadership_experience = models.TextField(
        blank=True,
        help_text=(
            "Have you ever managed people, coordinated "
            "a group or led a project? Explain."
        )
    )

    unsupervised_problem_solving = models.TextField(
        help_text=(
            "Describe a difficult problem you solved "
            "without supervision."
        )
    )

    performance_environment_understanding = models.TextField(
        help_text=(
            "What makes someone successful in a "
            "performance-based environment?"
        )
    )

    # =========================================================
    # STARTUP & CULTURE FIT
    # =========================================================

    startup_interest_reason = models.TextField(
        help_text=(
            "Why do you want to join a growing startup "
            "business instead of a traditional company?"
        )
    )

    comfortable_performance_environment = models.BooleanField(
        default=True,
    )

    motivation = models.TextField(
        help_text=(
            "What motivates you most: "
            "income, growth opportunity, leadership, "
            "building something meaningful, or something else?"
        )
    )

    # =========================================================
    # OPTIONAL VIDEO SUBMISSION
    # =========================================================

    introduction_video_link = models.URLField(
        blank=True,
        help_text=(
            "Optional: Link to a short introduction video "
            "(Google Drive, YouTube, Dropbox, etc.)"
        )
    )

    # =========================================================
    # APPLICATION STATUS
    # =========================================================

    APPLICATION_STATUS_CHOICES = [
        ("NEW", "New"),
        ("UNDER_REVIEW", "Under Review"),
        ("SHORTLISTED", "Shortlisted"),
        ("INTERVIEW", "Interview"),
        ("FIELD_TEST", "Field Test"),
        ("REJECTED", "Rejected"),
        ("APPROVED", "Approved"),
    ]

    application_status = models.CharField(
        max_length=30,
        choices=APPLICATION_STATUS_CHOICES,
        default="NEW",
    )

    # =========================================================
    # INTERNAL SCORING
    # =========================================================

    SCORE_CHOICES = [
        (1, "1 - Very Weak"),
        (2, "2 - Weak"),
        (3, "3 - Average"),
        (4, "4 - Strong"),
        (5, "5 - Exceptional"),
    ]

    territory_fit_score = models.IntegerField(
        choices=SCORE_CHOICES,
        null=True,
        blank=True,
    )

    communication_score = models.IntegerField(
        choices=SCORE_CHOICES,
        null=True,
        blank=True,
    )

    commercial_thinking_score = models.IntegerField(
        choices=SCORE_CHOICES,
        null=True,
        blank=True,
    )

    leadership_potential_score = models.IntegerField(
        choices=SCORE_CHOICES,
        null=True,
        blank=True,
    )

    startup_fit_score = models.IntegerField(
        choices=SCORE_CHOICES,
        null=True,
        blank=True,
    )

    overall_rating = models.IntegerField(
        choices=SCORE_CHOICES,
        null=True,
        blank=True,
    )

    evaluator_notes = models.TextField(
        blank=True,
    )

    # =========================================================
    # SYSTEM FIELDS
    # =========================================================

    submitted_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # =========================================================
    # META
    # =========================================================

    class Meta:
        ordering = ["-submitted_at"]

    # =========================================================
    # STRING REPRESENTATION
    # =========================================================

    def __str__(self):
        return f"{self.first_name} {self.surname}"
    


