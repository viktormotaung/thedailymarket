# portal/utils/access.py

from profiles.models import StaffProfile, SalesRepProfile, DriverProfile
from credit.models import FunderMember

def get_user_portal_access(user):

    is_staff_user = user.is_staff

    staff_profile = getattr(user, "staff_profile", None)
    staff_status = (getattr(staff_profile, "status", "") or "").upper()

    has_active_sales_rep = SalesRepProfile.objects.filter(
        user=user, status="active"
    ).exists()

    has_active_driver = DriverProfile.objects.filter(
        user=user, status="ACTIVE"
    ).exists()

    has_active_funder_membership = FunderMember.objects.filter(
        user=user, is_active=True
    ).exists()

    can_staff_portal = bool(
        is_staff_user and staff_profile and staff_status == "ACTIVE"
    )

    can_sales_portal = bool(
        has_active_sales_rep or (
            staff_profile and getattr(staff_profile, "can_access_sales", False)
        )
    )

    can_lender_portal = bool(has_active_funder_membership)
    can_logistics_portal = bool(has_active_driver)

    return {
        "can_staff_portal": can_staff_portal,
        "can_sales_portal": can_sales_portal,
        "can_lender_portal": can_lender_portal,
        "can_logistics_portal": can_logistics_portal,
    }