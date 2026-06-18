from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.timezone import now

from clients.models import Client
from .models import Transaction, BusinessBalance
from .forms import TransactionForm
from .models import Transaction, BusinessBalance
from django.db.models.functions import Coalesce

from django.utils.crypto import constant_time_compare
from django.db import transaction as db_transaction

from .models import Transaction
from audit.utils import log_event
from profiles.models import StaffProfile
from django.http import JsonResponse
from invoices.models import Invoice
from django.utils.timezone import now, make_aware
from datetime import datetime, timedelta, time, date

DAY_OPTIONS = (7, 14, 30, 60)


def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url='/portal/client/login/')



DAY_OPTIONS = [7, 14, 30, 60, 90]  # wherever you keep this

@login_required
@staff_required
def transaction_list(request):
    # --- days param (validated) ---
    raw = request.GET.get("days", "7")
    try:
        days = int(raw)
    except ValueError:
        days = 7
    if days not in DAY_OPTIONS:
        days = 7

    # --- base dates ---
    end_date = now().date()
    start_date = end_date - timedelta(days=days)

    # --- optional explicit overrides ---
    if request.GET.get("start"):
        try:
            start_date = date.fromisoformat(request.GET["start"])
        except ValueError:
            pass

    if request.GET.get("end"):
        try:
            end_date = date.fromisoformat(request.GET["end"])
        except ValueError:
            pass

    # --- convert to timezone-aware datetimes (MySQL safe) ---
    start_dt = make_aware(datetime.combine(start_date, time.min))
    end_dt = make_aware(datetime.combine(end_date, time.max))

    # --- base queryset ---
    qs = (
        Transaction.objects
        .select_related("client", "invoice")
        .filter(created_at__gte=start_dt, created_at__lte=end_dt)
    )

    # --- optional filters ---
    client_id = request.GET.get("client")
    if client_id and client_id.isdigit():
        qs = qs.filter(client_id=int(client_id))

    tx_type = request.GET.get("type")
    if tx_type:
        qs = qs.filter(transaction_type=tx_type)

    # --- KPIs: In / Out / Net ---
    CREDIT_TYPES = ("payment", "credit_repayment", "credit_issue", "refund")

    total_in = qs.aggregate(
        v=Coalesce(
            Sum("amount", filter=Q(transaction_type__in=CREDIT_TYPES)),
            Decimal("0.00")
        )
    )["v"]

    total_out = qs.aggregate(
        v=Coalesce(
            Sum("amount", filter=~Q(transaction_type__in=CREDIT_TYPES)),
            Decimal("0.00")
        )
    )["v"]

    net_total = (total_in or Decimal("0.00")) - (total_out or Decimal("0.00"))

    # --- context ---
    context = {
        "DAY_OPTIONS": DAY_OPTIONS,
        "days": days,
        "start_date": start_date,
        "end_date": end_date,
        "total_in": total_in,
        "total_out": total_out,
        "net_total": net_total,
        "transactions": qs.order_by("-created_at", "-id"),
        "clients": Client.objects.order_by("name").only("id", "name"),
        "type_choices": Transaction.TRANSACTION_TYPES,
        "request": request,  # needed for filters / hidden inputs
    }

    return render(request, "transactions/transaction_list.html", context)

@login_required
@staff_required
def ajax_invoices_by_client(request):
    """
    Returns invoices for a client as:
      {"results": [{"id": <pk>, "text": "INV-123 · 2025-02-01 · Paid · DueNow R..., Paid R..., Rem R..."}]}
    """
    client_id = request.GET.get("client_id")
    results = []

    if client_id:
        qs = (
            Invoice.objects
            .filter(client_id=client_id)
            .order_by("-created_at")
            .only("id", "invoice_date", "status", "amount_due", "deposit_paid")
        )[:200]

        for inv in qs:
            due_now = inv.amount_due or Decimal("0.00")
            paid = inv.deposit_paid or Decimal("0.00")
            remaining = max(due_now - paid, Decimal("0.00"))
            label = (
                f"INV-{inv.id} · {inv.invoice_date or ''} · {inv.get_status_display()} "
                f"· DueNow R{due_now:.2f} · Paid R{paid:.2f} · Rem R{remaining:.2f}"
            )
            results.append({"id": inv.id, "text": label})

    return JsonResponse({"results": results})


@login_required
@staff_required
def transaction_create(request):
    """
    Render/process 'Record Transaction'.
    The invoice dropdown is filtered to the selected client for both GET and POST.
    """
    if request.method == "POST":
        form = TransactionForm(request.POST)

        # Ensure invoice field validates against the chosen client
        client_id = request.POST.get("client") or None
        form.fields["invoice"].queryset = (
            Invoice.objects.filter(client_id=client_id).order_by("-created_at")
            if client_id else Invoice.objects.none()
        )

        if form.is_valid():
            tx: Transaction = form.save()  # model .save() updates balances and invoice snapshots
            messages.success(request, "Transaction recorded successfully.")
            return redirect(reverse("staff-transactions"))
    else:
        # Optional preselect: ?client=<id>
        client_id = request.GET.get("client") or None
        form = TransactionForm(initial={"client": client_id} if client_id else None)
        form.fields["invoice"].queryset = (
            Invoice.objects.filter(client_id=client_id).order_by("-created_at")
            if client_id else Invoice.objects.none()
        )

    return render(request, "transactions/transaction_create.html", {"form": form})

@login_required
@staff_required
def transaction_edit(request, pk):
    # You can flesh this out later; placeholder keeps route alive.
    return render(request, 'transactions/transaction_edit.html')


@login_required
@staff_required
def transaction_view(request, pk):
    """
    Detail page for a single transaction.
    Shows signed delta, business ledger pre/post, and client ledger post (and pre for convenience).
    """
    tx = get_object_or_404(
        Transaction.objects.select_related("client", "invoice"),
        pk=pk
    )

    # Signed movement for this transaction (credit = +, debit = -)
    signed_delta = BusinessBalance.signed_amount(tx.transaction_type, tx.amount)

    # Business ledger snapshot BEFORE this txn:
    pre_business_balance = (tx.balance or Decimal("0.00")) - signed_delta

    # Client ledger snapshot BEFORE this txn (useful for display/debug)
    pre_client_balance = (tx.client_balance or Decimal("0.00")) - signed_delta

    context = {
        "tx": tx,
        "client": tx.client,
        "invoice": tx.invoice,
        "signed_delta": signed_delta,
        "pre_balance": pre_business_balance,       # used in your template
        "pre_client_balance": pre_client_balance,  # available if you want to show it
    }
    return render(request, "transactions/transaction_view.html", context)

@login_required
@staff_required
def transaction_delete(request, pk):
    """
    Deletes a transaction after verifying the logged-in staff member's auth code.
    Logs an audit event (with before snapshot) and then deletes.
    """
    tx = get_object_or_404(
        Transaction.objects.select_related("client", "invoice"),
        pk=pk
    )

    if request.method == "POST":
        auth_code = (request.POST.get("auth_code") or "").strip()
        reason    = (request.POST.get("reason") or "").strip()

        # Ensure the user has a StaffProfile + code
        try:
            profile = request.user.staff_profile
        except StaffProfile.DoesNotExist:
            messages.error(request, "You don’t have a staff profile yet. Please set your staff auth code first.")
            return redirect("staff-profile")

        if not (profile.employee_auth_code or "").strip():
            messages.error(request, "No staff auth code found on your profile. Please set it first.")
            return redirect("staff-profile")

        # Constant-time compare
        if not auth_code or not constant_time_compare(auth_code, profile.employee_auth_code):
            messages.error(request, "Invalid staff auth code. Transaction was not deleted.")
            return redirect("transaction-view", pk=pk)

        # Capture snapshot BEFORE deletion
        before = {
            "id": tx.id,
            "client_id": tx.client_id,
            "invoice_id": tx.invoice_id,
            "type": tx.transaction_type,
            "amount": str(tx.amount),
            "balance": str(tx.balance),
            "client_balance": str(getattr(tx, "client_balance", Decimal("0.00"))),
            "reference": tx.reference,
        }
        client_id = tx.client_id

        with db_transaction.atomic():
            # Try to log audit (don't block delete on logging errors)
            try:
                log_event(
                    request=request,
                    action="transaction.delete",
                    obj=tx,  # content type & id taken from this instance
                    reason=reason,
                    auth_verified=True,
                    auth_method="staff_code",
                    before_snapshot=before,
                    after_snapshot={"deleted": True},
                    extra={"redirect_client_id": client_id},
                )
            except Exception:
                pass

            # Perform deletion (your model's delete() handles ledger/invoice adjustments)
            tx.delete()

        messages.success(request, f"Transaction #{pk} deleted.")
    # Redirect to list (filtered by client) after POST, or if GET fallthrough
        return redirect(f"{reverse('staff-transactions')}?client={client_id}")

    # GET -> simple confirmation page (if someone opens the URL directly)
    return render(request, "transactions/transaction_confirm_delete.html", {"tx": tx})


@login_required
@staff_required
def staff_finance_dashboard(request):
    return render(request, "transactions/staff_finance_dashboard.html")
