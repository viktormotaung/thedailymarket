from django.contrib import admin, messages
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import path
from django.shortcuts import redirect
from django.utils.html import format_html
from .models import SalesJobApplication


@admin.register(SalesJobApplication)
class SalesJobApplicationAdmin(admin.ModelAdmin):

    # =========================
    # LIST VIEW (TABLE)
    # =========================
    list_display = (
        "first_name",
        "last_name",
        "province",
        "town_or_city",
        "overall_rating",
        "reviewed",
    )

    list_editable = (
        "overall_rating",
        "reviewed",
    )

    list_filter = (
        "province",
        "reviewed",
        "shortlisted",
        "overall_rating",
        "submitted_at",
    )

    search_fields = (
        "first_name",
        "last_name",
        "email",
        "town_or_city",
        "suburb",
    )

    ordering = ("-overall_rating", "-submitted_at")
    list_per_page = 25
    date_hierarchy = "submitted_at"
    readonly_fields = ("submitted_at",)

    # =========================================================
    # ADD CUSTOM BULK EMAIL BUTTON TO ADMIN LIST PAGE
    # =========================================================
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "run-bulk-email/",
                self.admin_site.admin_view(self.run_bulk_email),
                name="run_bulk_email",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["bulk_email_button"] = format_html(
            '<a class="button" '
            'style="background:#0a5c39;color:white;padding:8px 15px;'
            'border-radius:4px;text-decoration:none;margin-left:10px;" '
            'href="run-bulk-email/">Run Bulk Email (Auto by Rating)</a>'
        )
        return super().changelist_view(request, extra_context=extra_context)

    # =========================================================
    # BULK EMAIL LOGIC
    # =========================================================
    def run_bulk_email(self, request):

        applications = (
            SalesJobApplication.objects
            .exclude(overall_rating__isnull=True)
            .exclude(email__isnull=True)
            .exclude(email="")
        )

        invite_count = 0
        reject_count = 0

        for candidate in applications:

            # =========================
            # INTERVIEW INVITE (3–5)
            # =========================
            if candidate.overall_rating >= 3:

                ctx = {
                    "candidate": candidate,
                    "calendly_link": "https://calendly.com/victor-thedailymarket/the-daily-market-interview",
                }

                subject = "The Daily Market – Schedule Your 15-Minute Interview"

                text_body = render_to_string(
                    "email/interview_invite.txt",
                    ctx
                )

                html_body = render_to_string(
                    "email/interview_invite.html",
                    ctx
                )

                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[candidate.email],
                    headers={"Reply-To": settings.SUPPORT_EMAIL},
                )

                msg.attach_alternative(html_body, "text/html")
                msg.send(fail_silently=False)

                invite_count += 1

            # =========================
            # REJECTION EMAIL (1–2)
            # =========================
            elif candidate.overall_rating <= 2:

                ctx = {"candidate": candidate}

                subject = "The Daily Market – Update on Your Application"

                text_body = render_to_string(
                    "email/application_rejected.txt",
                    ctx
                )

                html_body = render_to_string(
                    "email/application_rejected.html",
                    ctx
                )

                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[candidate.email],
                    headers={"Reply-To": settings.SUPPORT_EMAIL},
                )

                msg.attach_alternative(html_body, "text/html")
                msg.send(fail_silently=False)

                reject_count += 1

        self.message_user(
            request,
            f"Bulk email complete. "
            f"{invite_count} interview invites sent, "
            f"{reject_count} rejection emails sent.",
            messages.SUCCESS,
        )

        return redirect("../")
