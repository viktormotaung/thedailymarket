# credit/views.py
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import F, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.core.mail import EmailMultiAlternatives
from clients.models import Client
from transactions.models import Transaction   # ← ADD THIS
from .models import CreditAccount, CreditLog
from .forms import CreditEditForm
from django.db.models import F, Sum, Value, DecimalField, Q
from django.db.models import F, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from django.db import transaction

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render

from clients.models import Client
from .models import CreditAccount, CreditLog, CreditEntry
from .forms import CreditEditForm
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from profiles.models import CustomerProfile

import logging

logger = logging.getLogger(__name__)

def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")


@login_required
@staff_required
def credit_list(request):
    qs = (
        CreditAccount.objects
        .select_related("client")
        .annotate(
            available_amount=Coalesce(
                F("credit_limit") - F("credit_used"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .order_by("-updated_at", "client__name")
    )

    client_id = (request.GET.get("client") or "").strip()
    min_limit = (request.GET.get("min_limit") or "").strip()
    max_limit = (request.GET.get("max_limit") or "").strip()

    if client_id.isdigit():
        qs = qs.filter(client_id=int(client_id))

    def _to_decimal(v):
        try:
            return Decimal(v)
        except Exception:
            return None

    if min_limit:
        d = _to_decimal(min_limit)
        if d is not None:
            qs = qs.filter(credit_limit__gte=d)

    if max_limit:
        d = _to_decimal(max_limit)
        if d is not None:
            qs = qs.filter(credit_limit__lte=d)

    totals = qs.aggregate(
        total_limit=Coalesce(Sum("credit_limit"), Value(Decimal("0.00"))),
        total_used=Coalesce(Sum("credit_used"), Value(Decimal("0.00"))),
        total_available=Coalesce(Sum("available_amount"), Value(Decimal("0.00"))),
    )

    # Overall % used (guard against divide-by-zero)
    percent_used_total = Decimal("0.00")
    if totals["total_limit"] and totals["total_limit"] != Decimal("0.00"):
        percent_used_total = (totals["total_used"] / totals["total_limit"] * Decimal("100")).quantize(Decimal("0.01"))

    page = request.GET.get("page", 1)
    paginator = Paginator(qs, 25)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        "credit_accounts": page_obj.object_list,
        "page_obj": page_obj,
        "clients": Client.objects.order_by("name").only("id", "name"),
        "request": request,
        "total_limit": totals["total_limit"],
        "total_used": totals["total_used"],
        "total_available": totals["total_available"],
        "percent_used_total": percent_used_total,  # <-- add this
    }
    return render(request, "credit/credit_list.html", context)


@login_required
@staff_required
def credit_edit(request, client_id):
    # Base objects
    client = get_object_or_404(Client, pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)

    # Capture original state BEFORE POST
    original_credit_status = client.credit_status
    original_credit_status_norm = (original_credit_status or "").upper()
    prev_limit = account.credit_limit or Decimal("0.00")

    if request.method == "POST":
        form = CreditEditForm(request.POST)

        if form.is_valid():
            new_account_type = form.cleaned_data["account_type"]
            new_credit_status = form.cleaned_data["credit_status"]
            new_credit_status_norm = new_credit_status.upper()
            new_limit = form.cleaned_data["credit_limit"]
            note = form.cleaned_data.get("note") or ""
            new_funder = form.cleaned_data.get("funder")

            with transaction.atomic():

                # 1️⃣ Update CLIENT fields
                updates_client = []

                if client.account_type != new_account_type:
                    client.account_type = new_account_type
                    updates_client.append("account_type")

                if client.credit_status != new_credit_status:
                    client.credit_status = new_credit_status
                    updates_client.append("credit_status")

                if updates_client:
                    client.save(update_fields=updates_client)
                    print(f"[DEBUG] Client {client.id} updated fields: {updates_client}")

                # 2️⃣ Update CREDIT ACCOUNT funder
                updates_account = []
                if account.funder_id != (new_funder.pk if new_funder else None):
                    account.funder = new_funder
                    updates_account.append("funder")

                if updates_account:
                    account.save(update_fields=updates_account + ["updated_at"])
                    print(f"[DEBUG] CreditAccount {account.id} updated fields: {updates_account}")

                # 3️⃣ Update credit limit (audited path)
                if new_limit != prev_limit:
                    account.set_limit(
                        new_limit,
                        authorised_by=request.user,
                        note=note,
                    )
                    print(
                        f"[DEBUG] Credit limit changed from {prev_limit} to {new_limit}"
                    )

                # 4️⃣ EMAIL: resolve user via CreditAccount → Client → CustomerProfile
                credit_client = account.client

                customer_profile = (
                    credit_client.customer_profiles
                    .select_related("user")
                    .first()
                )

                user = getattr(customer_profile, "user", None)

                if (
                    user
                    and user.email
                    and original_credit_status_norm != "ACTIVE"
                    and new_credit_status_norm == "ACTIVE"
                ):
                    print(
                        f"[DEBUG] Sending credit active email to {user.email} "
                        f"(Client {credit_client.id})"
                    )
                    send_email_credit_active(credit_client, user)
                else:
                    print(
                        f"[DEBUG] Email not sent. "
                        f"user={bool(user)}, "
                        f"email={getattr(user, 'email', None)}, "
                        f"status_change={original_credit_status_norm}→{new_credit_status_norm}"
                    )

            messages.success(request, "Credit details updated.")
            return redirect("credit-view", client_id=client.id)

        messages.error(request, "Please correct the errors below.")

    else:
        form = CreditEditForm(initial={
            "account_type": client.account_type,
            "credit_status": client.credit_status,
            "credit_limit": account.credit_limit,
            "funder": account.funder_id,
            "note": "",
        })

    return render(
        request,
        "credit/credit_edit.html",
        {
            "client": client,
            "account": account,
            "form": form,
            "limit": account.credit_limit or Decimal("0.00"),
            "used": account.credit_used or Decimal("0.00"),
            "available": account.credit_available,
        },
    )


def send_email_credit_active(client, user):
    subject = "The Daily Market – Trade Assist Access Activated"

    ctx = {
        "user": user,
        "client": client,
        "credit_limit": client.credit_account.credit_limit or 0,
        "login_url": reverse("client-login"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
    }

    text_body = render_to_string("email/credit_active.txt", ctx)
    html_body = render_to_string("email/credit_active.html", ctx)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        headers={"Reply-To": ctx["support_email"]},
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

def send_email_credit_active(client, user):
    """
    Sends an email to the client when their credit account becomes active.
    """
    subject = "The Daily Market – Trade Assist Access Activated"

    ctx = {
        "user": user,
        "client": client,
        "credit_limit": client.credit_account.credit_limit or 0,
        "login_url": reverse("client-login"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
    }

    text_body = render_to_string("email/credit_active.txt", ctx)
    html_body = render_to_string("email/credit_active.html", ctx)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        headers={"Reply-To": ctx["support_email"]},
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


@login_required
@staff_required
def credit_client_view(request, client_id):
    client = get_object_or_404(Client.objects.select_related("credit_account"), pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)

    logs = account.logs.select_related("authorised_by").order_by("-created_at")

    # Credit-related transactions (legacy + current)
    tx_qs = (
        Transaction.objects
        .select_related("invoice")
        .filter(
            client=client,
            transaction_type__in=["credit_usage", "credit_repayment", "credit_issue", "adjustment"]
        )
        .order_by("-created_at", "-id")
    )

    # --- Account-level snapshots ---
    limit_ = account.credit_limit or Decimal("0.00")
    used_  = account.credit_used  or Decimal("0.00")
    avail_ = (limit_ - used_) if limit_ > 0 else Decimal("0.00")
    pct    = Decimal("0.00") if limit_ == 0 else (used_ / limit_) * Decimal("100")

    # --- Open credit exposure per invoice ---
    # Aggregate by invoice: total usage vs total repayment
    exposure_raw = (
        CreditEntry.objects
        .filter(
            credit_account=account,
            invoice__isnull=False,
        )
        .values(
            "invoice_id",
            "invoice__invoice_date",
            "invoice__due_date",
            "invoice__status",
        )
        .annotate(
            credit_used=Coalesce(
                Sum("amount", filter=Q(kind=CreditEntry.USAGE)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            credit_repaid=Coalesce(
                Sum("amount", filter=Q(kind=CreditEntry.REPAYMENT)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        )
    )

    open_invoices = []
    for row in exposure_raw:
        used = row["credit_used"] or Decimal("0.00")
        repaid = row["credit_repaid"] or Decimal("0.00")
        outstanding = used - repaid
        if outstanding > 0:
            open_invoices.append({
                "invoice_id": row["invoice_id"],
                "invoice_date": row["invoice__invoice_date"],
                "due_date": row["invoice__due_date"],
                "status": row["invoice__status"],
                "credit_used": used,
                "credit_repaid": repaid,
                "outstanding": outstanding,
            })

    open_credit_total = sum((row["outstanding"] for row in open_invoices), Decimal("0.00"))

    return render(request, "credit/credit_view.html", {
        "client": client,
        "account": account,
        "logs": logs,
        "transactions": tx_qs,

        "credit_limit": limit_,
        "credit_used": used_,
        "credit_available": avail_,
        "percent_used": pct.quantize(Decimal("0.01")),

        "open_invoices": open_invoices,
        "open_credit_total": open_credit_total,
    })

@login_required
@staff_required
def credit_record_repayment(request, client_id):
    """
    'Confirm Payment' from the Credit page:
    - Calculates total outstanding credit across all invoices for this client.
    - Records a single repayment CreditEntry for the full outstanding amount.
    (Later you can extend this to partial repayments or per-invoice selection.)
    """
    client = get_object_or_404(Client, pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)

    # Aggregate usage vs repayments across the whole account
    agg = (
        CreditEntry.objects
        .filter(credit_account=account)
        .aggregate(
            total_usage=Coalesce(
                Sum("amount", filter=Q(kind=CreditEntry.USAGE)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            total_repaid=Coalesce(
                Sum("amount", filter=Q(kind=CreditEntry.REPAYMENT)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        )
    )

    total_usage = agg["total_usage"] or Decimal("0.00")
    total_repaid = agg["total_repaid"] or Decimal("0.00")
    outstanding = total_usage - total_repaid

    if outstanding <= 0:
        messages.info(request, f"No outstanding credit to repay for {client}.")
        return redirect("credit-view", client_id=client.id)

    # Record one repayment against the account (not tied to a specific invoice)
    CreditEntry.record_repayment(
        client=client,
        amount=outstanding,
        invoice=None,
        transaction=None,
        reference=f"{client} credit repayment (auto)",
        note="Captured via Credit page 'Confirm Payment' (full outstanding).",
        when=None,
    )

    messages.success(
        request,
        f"Credit repayment of R{outstanding:.2f} recorded for {client}."
    )
    return redirect("credit-view", client_id=client.id)
