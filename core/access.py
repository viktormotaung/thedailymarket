def get_portal_access(user):
    if not user.is_authenticated:
        return {
            "can_staff_portal": False,
            "can_lender_portal": False,
            "can_sales_portal": False,
            "can_logistics_portal": False,
        }

    # ---- Staff ----
    staff_profile = getattr(user, "staff_profile", None)
    staff_status = (getattr(staff_profile, "status", "") or "").upper()

    can_staff_portal = bool(
        user.is_staff and staff_profile and staff_status == "ACTIVE"
    )

    # ---- Sales ----
    has_active_sales_rep = SalesRepProfile.objects.filter(
        user=user, status="active"
    ).exists()

    sales_from_staff = bool(
        staff_profile
        and getattr(staff_profile, "can_access_sales", False)
        and staff_status == "ACTIVE"
    )

    can_sales_portal = bool(has_active_sales_rep or sales_from_staff)

    # ---- Lender ----
    can_lender_portal = FunderMember.objects.filter(
        user=user, is_active=True
    ).exists()

    # ---- Logistics (future-safe) ----
    can_logistics_portal = LogisticsProfile.objects.filter(
        user=user, status="active"
    ).exists()

    return {
        "can_staff_portal": can_staff_portal,
        "can_lender_portal": can_lender_portal,
        "can_sales_portal": can_sales_portal,
        "can_logistics_portal": can_logistics_portal,
    }
