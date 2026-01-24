# seshibo_site/middleware.py
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

# 👇 groups that should NEVER be auto-logged out
EXEMPT_SESSION_GROUPS = {"Master", "Master logistics"}


class LastSeenMiddleware:
    """
    Update last_seen_at on the user's StaffProfile or CustomerProfile
    once per request. Uses queryset.update() to avoid loading/saving model.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return response

        now = timezone.now()

        try:
            staff_profile = getattr(user, "staff_profile")
        except ObjectDoesNotExist:
            staff_profile = None

        if staff_profile:
            staff_profile.__class__.objects.filter(
                pk=staff_profile.pk
            ).update(last_seen_at=now)
            return response

        try:
            customer_profile = getattr(user, "customer_profile")
        except ObjectDoesNotExist:
            customer_profile = None

        if customer_profile:
            customer_profile.__class__.objects.filter(
                pk=customer_profile.pk
            ).update(last_seen_at=now)

        return response


class ShortSessionForPortalMiddleware:
    """
    Apply a short sliding session expiry to portal users
    EXCEPT users in privileged groups (Master / Master logistics).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return response

        # Only apply to portal routes
        if not request.path.startswith("/portal/"):
            return response

        # 🔐 Skip timeout for exempt groups
        user_groups = set(
            user.groups.values_list("name", flat=True)
        )

        if user.is_superuser or user_groups.intersection(EXEMPT_SESSION_GROUPS):
            return response  # unlimited / normal session

        # ⏱ Apply sliding expiry (5 minutes)
        request.session.set_expiry(300)

        return response
