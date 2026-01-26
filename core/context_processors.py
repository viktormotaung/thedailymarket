import logging
from credit.models import FunderMember
from profiles.models import SalesRepProfile

logger = logging.getLogger(__name__)

def platform_access(request):
    if not request.user.is_authenticated:
        return {}

    user = request.user

    # -----------------------
    # Staff logic
    # -----------------------
    is_staff_user = user.is_staff
    staff_profile = getattr(user, "staff_profile", None)
    staff_status = (
        (getattr(staff_profile, "status", "") or "").upper()
        if staff_profile else None
    )

    can_staff_portal = bool(
        is_staff_user
        and staff_profile is not None
        and staff_status == "ACTIVE"
    )

    # -----------------------
    # Sales logic
    # -----------------------
    has_active_sales_rep = SalesRepProfile.objects.filter(
        user=user,
        status="active"
    ).exists()

    sales_flag_from_staff = bool(
        staff_profile is not None
        and getattr(staff_profile, "can_access_sales", False)
        and staff_status == "ACTIVE"
    )

    can_sales_portal = bool(
        has_active_sales_rep or sales_flag_from_staff
    )

    # -----------------------
    # Lender logic
    # -----------------------
    can_lender_portal = FunderMember.objects.filter(
        user=user,
        is_active=True
    ).exists()

    # -----------------------
    # Logistics (example – adjust if needed)
    # -----------------------
    can_logistics_portal = bool(
        staff_profile is not None
        and getattr(staff_profile, "can_access_logistics", False)
        and staff_status == "ACTIVE"
    )

    # -----------------------
    # DEBUG (temporary)
    # -----------------------
    logger.warning("=== PLATFORM ACCESS (context processor) ===")
    logger.warning(f"user: {user}")
    logger.warning(f"can_staff_portal: {can_staff_portal}")
    logger.warning(f"can_sales_portal: {can_sales_portal}")
    logger.warning(f"can_lender_portal: {can_lender_portal}")
    logger.warning(f"can_logistics_portal: {can_logistics_portal}")

    return {
        "can_staff_portal": can_staff_portal,
        "can_sales_portal": can_sales_portal,
        "can_lender_portal": can_lender_portal,
        "can_logistics_portal": can_logistics_portal,
    }


# core/context_processors.py
def access_flags(request):
    user = request.user
    can_write = False

    if user.is_authenticated:
        # 🚫 View Only ALWAYS wins
        if user.groups.filter(name="View Only").exists():
            can_write = False
        else:
            can_write = True

    return {
        "can_write": can_write
    }