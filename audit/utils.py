from __future__ import annotations
from typing import Any, Optional
from django.contrib.contenttypes.models import ContentType
from .models import AuditEvent

def _get_ip(request) -> Optional[str]:
    if not request:
        return None
    xfwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if xfwd:
        return xfwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def log_event(
    *,
    request,
    action: str,
    obj: Any = None,
    reason: str = "",
    auth_verified: bool = False,
    auth_method: str = "",
    before_snapshot: dict | None = None,
    after_snapshot: dict | None = None,
    extra: dict | None = None,
) -> AuditEvent:
    user = getattr(request, "user", None)
    actor_name = ""
    actor_email = ""
    if user and user.is_authenticated:
        # Keep light denormed copies for easy querying later
        actor_name = getattr(user, "get_full_name", lambda: "")() or user.get_username()
        actor_email = getattr(user, "email", "") or ""

    ct = None
    obj_id = ""
    obj_repr = ""
    if obj is not None:
        ct = ContentType.objects.get_for_model(obj.__class__)
        obj_id = str(getattr(obj, "pk", "")) or ""
        obj_repr = str(obj)

    return AuditEvent.objects.create(
        actor=user if (user and user.is_authenticated) else None,
        actor_name=actor_name,
        actor_email=actor_email,
        ip_address=_get_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") if request else "") or "",
        action=action,
        content_type=ct,
        object_id=obj_id,
        object_repr=obj_repr[:200],
        reason=reason or "",
        auth_verified=auth_verified,
        auth_method=auth_method or "",
        before_snapshot=before_snapshot or {},
        after_snapshot=after_snapshot or {},
        extra=extra or {},
    )
