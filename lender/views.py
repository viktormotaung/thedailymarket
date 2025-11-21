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
    """Allow if user is an active member of this funder or is_staff."""
    if request.user.is_staff:
        return True
    return FunderMember.objects.filter(
        user=request.user, funder=funder, is_active=True
    ).exists()

@login_required
def funder_dashboard(request):
    memberships = (
        FunderMember.objects
        .filter(user=request.user, is_active=True)
        .select_related("funder")
    )
    if not memberships.exists():
        return redirect(reverse("staff-dashboard"))

    qs_funder_id = request.GET.get("funder")
    if qs_funder_id:
        current = memberships.filter(funder_id=qs_funder_id).first()
        funder = current.funder if current else memberships.first().funder
    else:
        funder = memberships.first().funder

    allocations = (
        FunderAllocation.objects
        .filter(funder=funder)
        .select_related("client")
        .order_by("client__name")
    )
    total_alloc = allocations.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")

    latest_week = (
        FunderWeekSummary.objects
        .filter(funder=funder)
        .order_by("-week_start")
        .first()
    )

    today = date.today()
    four_weeks_ago = today - timedelta(weeks=4)
    recent_weeks = list(
        FunderWeekSummary.objects
        .filter(funder=funder, week_start__gte=four_weeks_ago)
        .order_by("week_start")
        .values(
            "week_start",
            "visible_utilization_total",
            "weekly_rate_pct_snapshot",
            "weekly_return",
        )
    )

    ctx = {
        "funder": funder,
        "allocations": allocations,
        "total_alloc": total_alloc,
        "allocatable": getattr(funder, "allocatable_balance", Decimal("0.00")),
        "latest_week": latest_week,
        "memberships": memberships,
        "recent_weeks": recent_weeks,
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