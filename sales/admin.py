from django.contrib import admin
from .models import SalesJobApplication


@admin.register(SalesJobApplication)
class SalesJobApplicationAdmin(admin.ModelAdmin):
    # =========================
    # LIST VIEW (TABLE)
    # =========================
    list_display = (
        "first_name",
        "last_name",
        "email",
        "province",
        "town_or_city",
        "availability_to_start",
        "has_drivers_license",
        "has_vehicle_access",
        "reviewed",
        "shortlisted",
        "submitted_at",
    )

    list_filter = (
        "province",
        "has_drivers_license",
        "has_vehicle_access",
        "has_laptop_or_tablet",
        "comfortable_township_clients",
        "comfortable_suburban_clients",
        "comfortable_remote_work",
        "comfortable_startup_environment",
        "reviewed",
        "shortlisted",
        "submitted_at",
    )

    search_fields = (
        "first_name",
        "last_name",
        "email",
        "nationality",
        "town_or_city",
        "suburb",
        "previous_workplaces",
        "current_job",
    )

    ordering = ("-submitted_at",)

    list_per_page = 25

    list_select_related = False
    date_hierarchy = "submitted_at"

    # =========================
    # DETAIL VIEW (FORM)
    # =========================
    readonly_fields = ("submitted_at",)

    fieldsets = (

        ("Basic Information", {
            "fields": (
                ("first_name", "last_name"),
                "email",
                "date_of_birth",
                "nationality",
                ("province", "town_or_city", "suburb"),
                "where_grew_up",
            )
        }),

        ("Sales Background", {
            "fields": (
                "sales_experience_summary",
                "previous_workplaces",
                "responsibilities",
                "lessons_learned",
            )
        }),

        ("Sales Thinking (Critical)", {
            "fields": (
                "client_identification_strategy",
                "pitching_strategy",
                "conversion_strategy",
                "client_management_strategy",
            )
        }),

        ("Resources & Tools", {
            "fields": (
                "resources_needed",
                ("has_drivers_license", "has_vehicle_access", "has_laptop_or_tablet"),
            )
        }),

        ("Work Style & Fit", {
            "fields": (
                "can_work_in_team",
                ("comfortable_township_clients", "comfortable_suburban_clients"),
                ("comfortable_remote_work", "comfortable_startup_environment"),
                "leadership_skills_description",
            )
        }),

        ("Current Status", {
            "fields": (
                "current_job",
                "availability_to_start",
            )
        }),

        ("Review & Shortlisting", {
            "fields": (
                ("reviewed", "shortlisted"),
                "submitted_at",
            )
        }),
    )

    # =========================
    # QUICK ACTIONS
    # =========================
    actions = (
        "mark_as_reviewed",
        "mark_as_shortlisted",
        "unmark_reviewed",
        "unmark_shortlisted",
    )

    @admin.action(description="Mark selected applications as reviewed")
    def mark_as_reviewed(self, request, queryset):
        queryset.update(reviewed=True)

    @admin.action(description="Remove reviewed flag")
    def unmark_reviewed(self, request, queryset):
        queryset.update(reviewed=False)

    @admin.action(description="Mark selected applications as shortlisted")
    def mark_as_shortlisted(self, request, queryset):
        queryset.update(shortlisted=True)

    @admin.action(description="Remove shortlisted flag")
    def unmark_shortlisted(self, request, queryset):
        queryset.update(shortlisted=False)
