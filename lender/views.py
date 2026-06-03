# lender/views.py
from decimal import Decimal, InvalidOperation
from datetime import timedelta, date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from credit.models import (
    Funder, FunderAllocation, FunderWeekSummary, FunderMember, FunderMovement
)
from django.contrib.auth import get_user_model

User = get_user_model()

def _movement_kind(value: str) -> str:
    """
    Map friendly strings to your model enum/choices if they exist.
    Falls back to raw strings 'topup'/'payout'.
    """
    value = (value or "").lower()
    if value == "topup":
        return getattr(FunderMovement, "TOPUP", "topup")
    if value in ("withdraw", "payout"):
        return getattr(FunderMovement, "PAYOUT", "payout")
    return value or getattr(FunderMovement, "TOPUP", "topup")


def _ensure_membership(request, funder: Funder) -> bool:
    """Allow if user is an active member of this funder or is_staff (checks BOTH DBs)."""
    if request.user.is_staff:
        return True

    return (
        FunderMember.objects.using("default")
        .filter(user=request.user, funder=funder, is_active=True)
        .exists()
        or
        FunderMember.objects.using("dummy")
        .filter(user=request.user, funder=funder, is_active=True)
        .exists()
    )


@login_required
def funder_dashboard(request):

    print("\n================ START DASHBOARD ================\n")

    from django.db.models import Sum, Count
    from django.db.models.functions import Coalesce
    from credit.models import FunderProfit

    # 🔹 STEP 0 — MAP USER ACROSS DBS
    dummy_user = User.objects.using("dummy").filter(
        username__iexact=request.user.username
    ).first()

    print("===== USER MAPPING =====")
    print(f"Default User: {request.user.username} | ID: {request.user.id}")
    print(f"Dummy User ID: {getattr(dummy_user, 'id', None)}")
    print("========================\n")

    # 🔍 EXTRA DEBUG
    print("===== DUMMY USER CHECK =====")
    all_dummy_users = list(
        User.objects.using("dummy")
        .filter(username__iexact=request.user.username)
        .values("id", "username")
    )
    print("Dummy users found:", all_dummy_users)
    print("============================\n")

    # 🔹 STEP 1 — GET MEMBERSHIPS
    dummy_memberships = []

    if dummy_user:
        dummy_memberships = list(
            FunderMember.objects.using("dummy")
            .filter(user=dummy_user, is_active=True)
            .select_related("funder")
        )

        print("===== DUMMY MEMBERSHIPS =====")
        for m in dummy_memberships:
            print(f"[DUMMY] Funder: {m.funder.name} | ID: {m.funder.id}")
        print("==============================\n")
    else:
        print("❌ No dummy user found\n")

    default_memberships = list(
        FunderMember.objects.using("default")
        .filter(user=request.user, is_active=True)
        .select_related("funder")
    )

    print("===== DEFAULT MEMBERSHIPS =====")
    for m in default_memberships:
        print(f"[DEFAULT] Funder: {m.funder.name} | ID: {m.funder.id}")
    print("===============================\n")

    # 🔥 PRIORITY: DUMMY FIRST
    if dummy_memberships:
        memberships = [(m, "dummy") for m in dummy_memberships]
        print("👉 USING DUMMY DB")
    else:
        memberships = [(m, "default") for m in default_memberships]
        print("👉 USING DEFAULT DB")

    print("===== FINAL MEMBERSHIPS =====")
    for m, membership_db in memberships:
        print(f"Funder: {m.funder.name} | ID: {m.funder.id} | DB: {membership_db}")
    print("=============================\n")

    if not memberships:
        print("❌ NO MEMBERSHIPS FOUND — REDIRECTING\n")
        return redirect(reverse("staff-dashboard"))

    # 🔹 STEP 2 — SELECT MEMBERSHIP
    qs_funder_id = request.GET.get("funder")
    selected = None

    if qs_funder_id:
        selected = next(
            ((m, membership_db) for m, membership_db in memberships if str(m.funder.id) == qs_funder_id),
            None
        )

    if selected:
        membership, db = selected
    else:
        membership, db = memberships[0]

    funder = membership.funder

    print("===== SELECTED =====")
    print(f"Selected Funder: {funder.name}")
    print(f"Selected Funder ID: {funder.id}")
    print(f"Selected DB: {db}")
    print(f"Funder object DB origin: {funder._state.db}")
    print("====================\n")

    # 🔹 STEP 3 — ALLOCATIONS
    print("===== ALLOCATION QUERY =====")
    print(f"Using DB: {db}")
    print("============================\n")

    allocations = (
        FunderAllocation.objects.using(db)
        .filter(funder__id=funder.id)
        .select_related("client")
        .order_by("client__name")
    )

    total_alloc = allocations.aggregate(
        s=Coalesce(Sum("amount"), Decimal("0.00"))
    )["s"] or Decimal("0.00")

    print(f"Allocations count: {allocations.count()}")
    print(f"Total Alloc: {total_alloc}\n")

    # 🔹 STEP 4 — WEEKLY DATA
    today = date.today()
    four_weeks_ago = today - timedelta(weeks=4)
    month_start = today.replace(day=1)

    latest_week = (
        FunderWeekSummary.objects.using(db)
        .filter(funder__id=funder.id)
        .order_by("-week_start")
        .first()
    )

    recent_weeks = list(
        FunderWeekSummary.objects.using(db)
        .filter(funder__id=funder.id, week_start__gte=four_weeks_ago)
        .order_by("week_start")
        .values(
            "week_start",
            "visible_utilization_total",
            "weekly_rate_pct_snapshot",
            "weekly_return",
        )
    )

    # 🔹 STEP 5 — PROFIT DATA
    recent_profits = (
        FunderProfit.objects.using(db)
        .filter(funder__id=funder.id)
        .select_related("week_summary")
        .order_by("-period_start", "-created_at")[:10]
    )

    pending_profit_total = (
        FunderProfit.objects.using(db)
        .filter(funder__id=funder.id, status="PENDING")
        .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        or Decimal("0.00")
    )

    reinvested_this_month = (
        FunderProfit.objects.using(db)
        .filter(
            funder__id=funder.id,
            status="REINVESTED",
            processed_at__date__gte=month_start,
            processed_at__date__lte=today,
        )
        .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        or Decimal("0.00")
    )

    paid_out_this_month = (
        FunderProfit.objects.using(db)
        .filter(
            funder__id=funder.id,
            status="PAID_OUT",
            processed_at__date__gte=month_start,
            processed_at__date__lte=today,
        )
        .aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        or Decimal("0.00")
    )

    # 🔹 STEP 6 — MOVEMENT DATA
    recent_movements = (
        FunderMovement.objects.using(db)
        .filter(funder__id=funder.id)
        .annotate(linked_profits_count=Count("profit_links", distinct=True))
        .order_by("-created_at", "-id")[:10]
    )

    print("===== FUNDER VALUES =====")
    print(f"Balance: {getattr(funder, 'balance', 'NO FIELD')}")
    print(f"Allocatable: {getattr(funder, 'allocatable_balance', 'NO FIELD')}")
    print(f"Pending Profit Total: {pending_profit_total}")
    print(f"Reinvested This Month: {reinvested_this_month}")
    print(f"Paid Out This Month: {paid_out_this_month}")
    print("==========================\n")

    print("================ END DASHBOARD ================\n")

    # 🔹 FINAL CONTEXT
    ctx = {
        "funder": funder,
        "allocations": allocations,
        "total_alloc": total_alloc,
        "allocatable": getattr(funder, "allocatable_balance", Decimal("0.00")),
        "latest_week": latest_week,
        "memberships": memberships,
        "recent_weeks": recent_weeks,
        "recent_profits": recent_profits,
        "recent_movements": recent_movements,
        "pending_profit_total": pending_profit_total,
        "reinvested_this_month": reinvested_this_month,
        "paid_out_this_month": paid_out_this_month,
        "mode": db,
    }

    return render(request, "lender/dashboard.html", ctx)



@login_required
def top_up(request):
    """
    Create a TOP-UP movement for a funder.
    GET: render form (prefilled from ?funder=).
    POST: validate + create FunderMovement, redirect to funder dashboard.
    """
    funder_id = request.GET.get("funder") or request.POST.get("funder")
    funder = get_object_or_404(Funder, id=funder_id) if funder_id else None
    if not funder:
        messages.error(request, "Missing funder.")
        return redirect(reverse("funder-dashboard"))

    if not _ensure_membership(request, funder):
        messages.error(request, "You do not have access to this funder.")
        return redirect(reverse("funder-dashboard"))

    if request.method == "POST":
        amount_raw = request.POST.get("amount", "").strip()
        reference = (request.POST.get("reference") or "").strip()
        note = (request.POST.get("note") or "").strip()
        try:
            amount = Decimal(amount_raw)
        except (InvalidOperation, TypeError):
            messages.error(request, "Please enter a valid amount.")
            return redirect(f"{reverse('top-up')}?funder={funder.id}")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect(f"{reverse('top-up')}?funder={funder.id}")

        kind = _movement_kind("topup")
        # Create the movement; assume model/signal updates balance
        FunderMovement.objects.create(
            funder=funder, kind=kind, amount=amount,
            reference=reference or "Top-up", note=note
        )
        messages.success(request, f"Top-up of R{amount:.2f} captured for {funder.name}.")
        return redirect(f"{reverse('funder-dashboard')}?funder={funder.id}")

    # GET
    ctx = {
        "funder": funder,
        "page_title": f"Top up · {funder.name}",
        "kind": _movement_kind("topup"),
        "action_url": reverse("top-up"),
        "submit_label": "Top up",
        "submit_icon": "bi-plus-circle",
        "accent_btn": "btn-success",
    }
    return render(request, "lender/top_up.html", ctx)

@login_required
def withdraw(request):
    """
    Create a WITHDRAW/PAYOUT movement for a funder.
    """
    funder_id = request.GET.get("funder") or request.POST.get("funder")
    funder = get_object_or_404(Funder, id=funder_id) if funder_id else None
    if not funder:
        messages.error(request, "Missing funder.")
        return redirect(reverse("funder-dashboard"))

    if not _ensure_membership(request, funder):
        messages.error(request, "You do not have access to this funder.")
        return redirect(reverse("funder-dashboard"))

    if request.method == "POST":
        amount_raw = request.POST.get("amount", "").strip()
        reference = (request.POST.get("reference") or "").strip()
        note = (request.POST.get("note") or "").strip()
        try:
            amount = Decimal(amount_raw)
        except (InvalidOperation, TypeError):
            messages.error(request, "Please enter a valid amount.")
            return redirect(f"{reverse('withdraw')}?funder={funder.id}")

        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
            return redirect(f"{reverse('withdraw')}?funder={funder.id}")

        # Optional guard: don't allow withdrawing more than balance (comment out if model handles it)
        if getattr(funder, "balance", Decimal("0.00")) < amount:
            messages.error(request, "Insufficient balance for this withdrawal.")
            return redirect(f"{reverse('withdraw')}?funder={funder.id}")

        kind = _movement_kind("payout")
        FunderMovement.objects.create(
            funder=funder, kind=kind, amount=amount,
            reference=reference or "Withdrawal", note=note
        )
        messages.success(request, f"Withdrawal of R{amount:.2f} captured for {funder.name}.")
        return redirect(f"{reverse('funder-dashboard')}?funder={funder.id}")

    ctx = {
        "funder": funder,
        "page_title": f"Withdraw · {funder.name}",
        "kind": _movement_kind("payout"),
        "action_url": reverse("withdraw"),
        "submit_label": "Withdraw",
        "submit_icon": "bi-arrow-down-circle",
        "accent_btn": "btn-outline-danger",
    }
    return render(request, "lender/withdraw.html", ctx)

@login_required
def payfast_return(request):
    messages.success(request, "Thanks! If your payment completed, funds will reflect shortly.")
    # Keep user on same funder if possible
    fid = request.GET.get("custom_str1") or ""
    url = reverse("funder-dashboard")
    return redirect(f"{url}?funder={fid}" if fid else url)


@login_required
def payfast_cancel(request):
    messages.info(request, "Payment was cancelled.")
    fid = request.GET.get("custom_str1") or ""
    url = reverse("funder-dashboard")
    return redirect(f"{url}?funder={fid}" if fid else url)


@csrf_exempt
def payfast_notify(request):
    """
    ITN handler (server-to-server). Minimal flow:
    - Verify signature
    - If payment_status == 'COMPLETE', create a TOPUP movement on the referenced funder.
    NOTE: For production you should also verify the source IPs and validate the data with
    the /eng/query/validate endpoint. Add those steps before crediting funds.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid")

    posted = {k: request.POST.get(k, "") for k in request.POST.keys()}

    # 1) Verify signature
    received_sig = posted.get("signature", "")
    data_for_sig = {k: v for k, v in posted.items() if k != "signature"}
    calc_sig = _build_signature(data_for_sig, getattr(settings, "PAYFAST_PASSPHRASE", ""))
    if received_sig.lower() != calc_sig.lower():
        return HttpResponseBadRequest("Invalid signature")

    # 2) (Recommended) Verify source IPs and use PF validate endpoint here.

    # 3) Process success
    status = posted.get("payment_status", "")
    amount = Decimal(posted.get("amount_gross") or posted.get("amount", "0") or "0")
    funder_id = posted.get("custom_str1")
    ref = posted.get("m_payment_id") or posted.get("pf_payment_id")

    if status.upper() == "COMPLETE" and funder_id:
        try:
            funder = Funder.objects.get(id=funder_id)
            # Idempotency: don't double-insert same ref
            exists = FunderMovement.objects.filter(funder=funder, reference=ref).exists()
            if not exists:
                FunderMovement.objects.create(
                    funder=funder,
                    kind=getattr(FunderMovement, "TOPUP", "topup"),
                    amount=amount,
                    reference=ref or "payfast",
                    note="PayFast top-up",
                )
        except Funder.DoesNotExist:
            # ignore if unknown
            pass

    return HttpResponse("OK")


def build_funder_report_context(request):
    from calendar import monthrange
    from datetime import date
    from decimal import Decimal

    from django.db.models import Sum
    from django.db.models.functions import Coalesce

    from credit.models import (
        Funder,
        FunderAllocation,
        FunderWeekSummary,
        FunderMember,
    )

    today = date.today()
    year_raw = request.GET.get("year")

    try:
        selected_year = int(year_raw) if year_raw else today.year
    except ValueError:
        selected_year = today.year

    dummy_user = User.objects.using("dummy").filter(
        username__iexact=request.user.username
    ).first()

    funder_options = []

    if request.user.is_staff:
        db = request.GET.get("mode") or "dummy"

        if db not in ["default", "dummy"]:
            db = "dummy"

        funders = (
            Funder.objects.using(db)
            .all()
            .order_by("name")
        )

        funder_options = [
            {
                "id": f.id,
                "name": f.name,
                "db": db,
            }
            for f in funders
        ]

    else:
        dummy_memberships = []

        if dummy_user:
            dummy_memberships = list(
                FunderMember.objects.using("dummy")
                .filter(user=dummy_user, is_active=True)
                .select_related("funder")
            )

        default_memberships = list(
            FunderMember.objects.using("default")
            .filter(user=request.user, is_active=True)
            .select_related("funder")
        )

        if dummy_memberships:
            db = "dummy"
            memberships = dummy_memberships
        else:
            db = "default"
            memberships = default_memberships

        if not memberships:
            return None, "No funder access found."

        funder_options = [
            {
                "id": m.funder.id,
                "name": m.funder.name,
                "db": db,
            }
            for m in memberships
        ]

    selected_funder_id = request.GET.get("funder")

    if selected_funder_id:
        funder = (
            Funder.objects.using(db)
            .filter(id=selected_funder_id)
            .first()
        )
    else:
        first_option = funder_options[0] if funder_options else None

        funder = (
            Funder.objects.using(db)
            .filter(id=first_option["id"])
            .first()
            if first_option
            else None
        )

    if not funder:
        return None, "No funder found."

    allocations = (
        FunderAllocation.objects.using(db)
        .filter(funder_id=funder.id)
        .select_related("client")
        .order_by("client__name")
    )

    total_allocated = allocations.aggregate(
        total=Coalesce(Sum("amount"), Decimal("0.00"))
    )["total"] or Decimal("0.00")

    monthly_rows = []

    annual_raw_usage = Decimal("0.00")
    annual_visible_usage = Decimal("0.00")
    annual_return = Decimal("0.00")

    for month in range(1, 13):
        month_start = date(selected_year, month, 1)
        month_end = date(
            selected_year,
            month,
            monthrange(selected_year, month)[1],
        )

        weeks = (
            FunderWeekSummary.objects.using(db)
            .filter(
                funder_id=funder.id,
                week_start__gte=month_start,
                week_start__lte=month_end,
            )
        )

        totals = weeks.aggregate(
            raw_usage=Coalesce(
                Sum("raw_weekly_usage"),
                Decimal("0.00"),
            ),
            visible_usage=Coalesce(
                Sum("visible_utilization_total"),
                Decimal("0.00"),
            ),
            return_generated=Coalesce(
                Sum("weekly_return"),
                Decimal("0.00"),
            ),
        )

        raw_usage = totals["raw_usage"] or Decimal("0.00")
        visible_usage = totals["visible_usage"] or Decimal("0.00")
        return_generated = totals["return_generated"] or Decimal("0.00")

        utilization_pct = Decimal("0.00")
        utilization_multiple = Decimal("0.00")
        average_working_rate = Decimal("0.00")

        if total_allocated > 0:
            utilization_pct = (
                visible_usage / total_allocated
            ) * Decimal("100")

            utilization_multiple = (
                visible_usage / total_allocated
            )

        if visible_usage > 0:
            average_working_rate = (
                return_generated / visible_usage
            ) * Decimal("100")

        monthly_rows.append({
            "month": month_start,
            "raw_usage": raw_usage,
            "visible_usage": visible_usage,
            "return_generated": return_generated,
            "utilization_pct": utilization_pct,
            "utilization_multiple": utilization_multiple,
            "average_working_rate": average_working_rate,
        })

        annual_raw_usage += raw_usage
        annual_visible_usage += visible_usage
        annual_return += return_generated

    annual_utilization_pct = Decimal("0.00")
    annual_utilization_multiple = Decimal("0.00")
    annual_average_working_rate = Decimal("0.00")

    if total_allocated > 0:
        annual_utilization_pct = (
            annual_visible_usage / total_allocated
        ) * Decimal("100")

        annual_utilization_multiple = (
            annual_visible_usage / total_allocated
        )

    if annual_visible_usage > 0:
        annual_average_working_rate = (
            annual_return / annual_visible_usage
        ) * Decimal("100")

    # --------------------------------------------------
    # Growth and projection calculations
    # --------------------------------------------------
    growth_percentage = Decimal("0.00")
    current_capital_value = total_allocated
    monthly_avg_return = Decimal("0.00")
    projected_year_end_return = Decimal("0.00")
    projected_year_end_capital = total_allocated
    projected_growth_pct = Decimal("0.00")

    active_months = len([
        row for row in monthly_rows
        if row["return_generated"] > 0
    ])

    if total_allocated > 0:
        growth_percentage = (
            annual_return / total_allocated
        ) * Decimal("100")

        current_capital_value = (
            total_allocated + annual_return
        )

        if active_months > 0:
            monthly_avg_return = (
                annual_return / Decimal(active_months)
            )

            projected_year_end_return = (
                monthly_avg_return * Decimal("12")
            )

            projected_year_end_capital = (
                total_allocated + projected_year_end_return
            )

            projected_growth_pct = (
                projected_year_end_return / total_allocated
            ) * Decimal("100")

    # --------------------------------------------------
    # Strongest month
    # --------------------------------------------------
    strongest_month = None

    active_rows = [
        row for row in monthly_rows
        if row["return_generated"] > 0
    ]

    if active_rows:
        strongest_month = max(
            active_rows,
            key=lambda row: row["return_generated"],
        )

    # --------------------------------------------------
    # Executive written report
    # --------------------------------------------------
    if strongest_month:
        strongest_month_text = (
            f"{strongest_month['month'].strftime('%B %Y')} represented "
            f"the strongest performance month, with capped utilization of "
            f"R{strongest_month['visible_usage']:,.2f} and return generated "
            f"of R{strongest_month['return_generated']:,.2f}."
        )
    else:
        strongest_month_text = (
            "No active return-generating month was recorded during this period."
        )

    executive_summary = (
        f"During the {selected_year} reporting period, {funder.name} "
        f"allocated R{total_allocated:,.2f} in operational capital into "
        f"The Daily Market credit ecosystem.\n\n"

        f"To date, the allocated capital has generated total capped utilization "
        f"activity of R{annual_visible_usage:,.2f}, representing a capital "
        f"movement multiple of approximately {annual_utilization_multiple:.2f}x "
        f"against the original allocated amount.\n\n"

        f"The deployed capital generated total returns of R{annual_return:,.2f} "
        f"at an average working rate of {annual_average_working_rate:.2f}%.\n\n"

        f"Based on the original allocated capital amount of R{total_allocated:,.2f}, "
        f"the current generated return represents approximately "
        f"{growth_percentage:.2f}% growth on the original capital deployed. "
        f"This results in an estimated current capital value of approximately "
        f"R{current_capital_value:,.2f}, before any withdrawals, reallocations, "
        f"or reinvestment adjustments.\n\n"

        f"{strongest_month_text}\n\n"

        f"Based on the current operational performance trend and average monthly "
        f"return generation observed during the active reporting period, projected "
        f"annualized returns are estimated at approximately "
        f"R{projected_year_end_return:,.2f} by year-end, provided current utilization "
        f"levels and working rates remain consistent.\n\n"

        f"Under the current operational trajectory, the projected year-end capital "
        f"value is estimated to reach approximately "
        f"R{projected_year_end_capital:,.2f}, representing projected annual growth "
        f"of approximately {projected_growth_pct:.2f}% relative to the original "
        f"capital allocation.\n\n"

        f"Overall, the reporting period demonstrates capital deployment, utilization "
        f"turnover, and return generation within The Daily Market operational credit "
        f"environment."
    )

    context = {
        "funder": funder,
        "funder_options": funder_options,
        "selected_funder_id": str(funder.id),
        "selected_year": selected_year,
        "mode": db,

        "allocations": allocations,
        "total_allocated": total_allocated,

        "monthly_rows": monthly_rows,

        "annual_raw_usage": annual_raw_usage,
        "annual_visible_usage": annual_visible_usage,
        "annual_return": annual_return,
        "annual_utilization_pct": annual_utilization_pct,
        "annual_utilization_multiple": annual_utilization_multiple,
        "annual_average_working_rate": annual_average_working_rate,

        "growth_percentage": growth_percentage,
        "current_capital_value": current_capital_value,
        "active_months": active_months,
        "monthly_avg_return": monthly_avg_return,
        "projected_year_end_return": projected_year_end_return,
        "projected_year_end_capital": projected_year_end_capital,
        "projected_growth_pct": projected_growth_pct,
        "strongest_month": strongest_month,
        "executive_summary": executive_summary,
    }

    return context, None


@login_required
def funder_report(request):
    context, error = build_funder_report_context(request)

    if error:
        messages.error(request, error)
        return redirect(reverse("funder-dashboard"))

    return render(
        request,
        "lender/funder_report.html",
        context,
    )


@login_required
def funder_report_pdf(request):
    from io import BytesIO

    from django.http import HttpResponse
    from django.template.loader import get_template

    from xhtml2pdf import pisa

    context, error = build_funder_report_context(request)

    if error:
        messages.error(request, error)
        return redirect(reverse("funder-dashboard"))

    template = get_template(
        "lender/pdf/funder_report_pdf.html"
    )

    html = template.render(context)

    result = BytesIO()

    pdf = pisa.pisaDocument(
        BytesIO(html.encode("UTF-8")),
        result,
    )

    if pdf.err:
        return HttpResponse(
            "Error generating PDF",
            status=500,
        )

    safe_funder_name = (
        str(context["funder"].name)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    filename = (
        f"{safe_funder_name}"
        f"_report_"
        f"{context['selected_year']}.pdf"
    )

    response = HttpResponse(
        result.getvalue(),
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'attachment; filename="{filename}"'
    )

    return response