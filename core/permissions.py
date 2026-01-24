# core/permissions.py
from django.http import HttpResponseForbidden

def write_required(view_func):
    def _wrapped(request, *args, **kwargs):
        if not (
            request.user.is_superuser or
            (
                request.user.is_staff and
                not request.user.groups.filter(name="View Only").exists()
            )
        ):
            return HttpResponseForbidden("View-only access")
        return view_func(request, *args, **kwargs)
    return _wrapped