def platform_access(request):
    if not request.user.is_authenticated:
        return {}

    return {
        "can_staff_portal": request.user.has_perm("staff_portal.access_staff"),
        "can_sales_portal": request.user.has_perm("sales.access_sales"),
        "can_lender_portal": request.user.has_perm("lender.access_lender"),
        "can_logistics_portal": request.user.has_perm("logistics.access_logistics"),
    }

# core/context_processors.py

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