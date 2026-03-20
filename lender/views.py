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


def _get_db_for_funder(funder, default_memberships, dummy_memberships):
    """Determine which DB this funder belongs to."""
    if any(m.funder.id == funder.id for m in dummy_memberships):
        return "dummy"
    return "default"


@login_required
def funder_dashboard(request):
    # 🔹 STEP 1 — GET MEMBERSHIPS FROM BOTH DBS
    default_memberships = (
        FunderMember.objects.using("default")
        .filter(user=request.user, is_active=True)
        .select_related("funder")
    )

    dummy_memberships = (
        FunderMember.objects.using("dummy")
        .filter(user=request.user, is_active=True)
        .select_related("funder")
    )

    memberships = list(default_memberships) + list(dummy_memberships)

    if not memberships:
        return redirect(reverse("staff-dashboard"))

    has_default = default_memberships.exists()
    has_dummy = dummy_memberships.exists()

    # 🔹 STEP 2 — SELECT FUNDER
    qs_funder_id = request.GET.get("funder")

    all_funders = [m.funder for m in memberships]

    if qs_funder_id:
        funder = next((f for f in all_funders if str(f.id) == qs_funder_id), None)
        if not funder:
            funder = all_funders[0]
    else:
        funder = all_funders[0]

    # 🔹 STEP 3 — DETERMINE DB
    db = _get_db_for_funder(funder, default_memberships, dummy_memberships)

    # 🔹 OPTIONAL: COMBINED MODE
    combined_mode = request.GET.get("mode") == "combined" and has_default and has_dummy

    # 🔹 STEP 4 — ALLOCATIONS
    if combined_mode:
        allocations_default = (
            FunderAllocation.objects.using("default")
            .filter(funder=funder)
            .select_related("client")
        )

        allocations_dummy = (
            FunderAllocation.objects.using("dummy")
            .filter(funder=funder)
            .select_related("client")
        )

        allocations = list(allocations_default) + list(allocations_dummy)
        allocations = sorted(allocations, key=lambda x: x.client.name)

        total_alloc = sum(a.amount for a in allocations)

    else:
        allocations = (
            FunderAllocation.objects.using(db)
            .filter(funder=funder)
            .select_related("client")
            .order_by("client__name")
        )

        total_alloc = allocations.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

    # 🔹 STEP 5 — WEEKLY DATA
    today = date.today()
    four_weeks_ago = today - timedelta(weeks=4)

    if combined_mode:
        latest_week_default = (
            FunderWeekSummary.objects.using("default")
            .filter(funder=funder)
            .order_by("-week_start")
            .first()
        )

        latest_week_dummy = (
            FunderWeekSummary.objects.using("dummy")
            .filter(funder=funder)
            .order_by("-week_start")
            .first()
        )

        latest_week = latest_week_default or latest_week_dummy

        recent_default = list(
            FunderWeekSummary.objects.using("default")
            .filter(funder=funder, week_start__gte=four_weeks_ago)
            .values(
                "week_start",
                "visible_utilization_total",
                "weekly_rate_pct_snapshot",
                "weekly_return",
            )
        )

        recent_dummy = list(
            FunderWeekSummary.objects.using("dummy")
            .filter(funder=funder, week_start__gte=four_weeks_ago)
            .values(
                "week_start",
                "visible_utilization_total",
                "weekly_rate_pct_snapshot",
                "weekly_return",
            )
        )

        recent_weeks = sorted(
            recent_default + recent_dummy,
            key=lambda x: x["week_start"]
        )

    else:
        latest_week = (
            FunderWeekSummary.objects.using(db)
            .filter(funder=funder)
            .order_by("-week_start")
            .first()
        )

        recent_weeks = list(
            FunderWeekSummary.objects.using(db)
            .filter(funder=funder, week_start__gte=four_weeks_ago)
            .order_by("week_start")
            .values(
                "week_start",
                "visible_utilization_total",
                "weekly_rate_pct_snapshot",
                "weekly_return",
            )
        )

    # 🔹 FINAL CONTEXT
    ctx = {
        "funder": funder,
        "allocations": allocations,
        "total_alloc": total_alloc,
        "allocatable": getattr(funder, "allocatable_balance", Decimal("0.00")),
        "latest_week": latest_week,
        "memberships": memberships,
        "recent_weeks": recent_weeks,
        "mode": "combined" if combined_mode else db,
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