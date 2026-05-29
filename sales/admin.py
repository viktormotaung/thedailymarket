from django.contrib import admin, messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html

from .models import JobApplication


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):

    list_display = (
        "first_name",
        "surname",
        "age",
        "gender",
        "race",
        "territory",
        "current_location",
        "application_status",
        "overall_rating",
        "submitted_at",
    )

    list_editable = (
        "application_status",
        "overall_rating",
    )

    list_filter = (
        "territory",
        "application_status",
        "gender",
        "race",
        "comfortable_performance_environment",
        "has_drivers_license",
        "has_vehicle_access",
        "submitted_at",
    )

    search_fields = (
        "first_name",
        "surname",
        "email",
        "phone_number",
        "whatsapp_number",
        "current_location",
        "territory_understanding",
        "potential_client_types",
    )

    ordering = (
        "-overall_rating",
        "-submitted_at",
    )

    list_per_page = 25
    date_hierarchy = "submitted_at"

    readonly_fields = (
        "submitted_at",
        "updated_at",
    )

    fieldsets = (
        ("Application Status", {
            "fields": (
                "application_status",
                "overall_rating",
                "evaluator_notes",
            )
        }),

        ("Territory", {
            "fields": (
                "territory",
            )
        }),

        ("Basic Personal Information", {
            "fields": (
                "first_name",
                "surname",
                "age",
                "race",
                "gender",
                "phone_number",
                "whatsapp_number",
                "email",
                "current_location",
                "year_matriculated",
                "qualifications",
                "current_employment_status",
                "availability_to_start",
            )
        }),

        ("Transport & Resources", {
            "fields": (
                "has_drivers_license",
                "has_vehicle_access",
                "has_smartphone",
            )
        }),

        ("Territory & Commercial Thinking", {
            "fields": (
                "territory_understanding",
                "potential_client_types",
                "first_30_day_strategy",
            )
        }),

        ("Sales & Problem Solving", {
            "fields": (
                "cheaper_supplier_response",
                "client_retention_strategy",
                "target_pressure_response",
            )
        }),

        ("Leadership & Accountability", {
            "fields": (
                "leadership_experience",
                "unsupervised_problem_solving",
                "performance_environment_understanding",
            )
        }),

        ("Startup & Culture Fit", {
            "fields": (
                "startup_interest_reason",
                "comfortable_performance_environment",
                "motivation",
            )
        }),

        ("Optional Video Submission", {
            "fields": (
                "introduction_video_link",
            )
        }),

        ("Internal Scoring", {
            "fields": (
                "territory_fit_score",
                "communication_score",
                "commercial_thinking_score",
                "leadership_potential_score",
                "startup_fit_score",
            )
        }),

        ("System Fields", {
            "fields": (
                "submitted_at",
                "updated_at",
            )
        }),
    )