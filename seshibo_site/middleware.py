# seshibo_site/middleware.py
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

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

        # Prefer staff profile if present; otherwise customer profile.
        # Use safe access to avoid RelatedObjectDoesNotExist blowing up.
        try:
            staff_profile = getattr(user, "staff_profile")
        except ObjectDoesNotExist:
            staff_profile = None

        if staff_profile:
            staff_profile.__class__.objects.filter(pk=staff_profile.pk).update(last_seen_at=now)
            return response

        try:
            customer_profile = getattr(user, "customer_profile")
        except ObjectDoesNotExist:
            customer_profile = None

        if customer_profile:
            customer_profile.__class__.objects.filter(pk=customer_profile.pk).update(last_seen_at=now)

        return response


class ShortSessionForPortalMiddleware:
    """
    For portal routes (adjust prefix), use a 5-minute sliding session expiry.
    Requires SESSION_COOKIE_AGE >= 300 and/or explicit set_expiry here.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated and request.path.startswith("/portal/"):
            request.session.set_expiry(300)  # 5 minutes
        return response
