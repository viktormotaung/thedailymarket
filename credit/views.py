# credit/views.py
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.http import require_POST

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
from django.db.models import Sum
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
import hashlib
import urllib.parse

from decimal import Decimal, ROUND_HALF_UP

def r2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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

            # ✅ NEW FIELDS
            new_payment_term = form.cleaned_data["payment_term"]
            new_deposit_pct = form.cleaned_data["credit_deposit_pct"]

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
                    print(
                        f"[DEBUG] CreditAccount {account.id} updated fields: {updates_account}"
                    )

                # 2️⃣b Update payment rules (NEW)
                updates_rules = []

                if account.payment_term != new_payment_term:
                    account.payment_term = new_payment_term
                    updates_rules.append("payment_term")

                if account.credit_deposit_pct != new_deposit_pct:
                    account.credit_deposit_pct = new_deposit_pct
                    updates_rules.append("credit_deposit_pct")

                if updates_rules:
                    account.save(update_fields=updates_rules + ["updated_at"])
                    print(
                        f"[DEBUG] CreditAccount {account.id} updated rules: {updates_rules}"
                    )

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
            "payment_term": account.payment_term,
            "credit_deposit_pct": account.credit_deposit_pct,
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
    # ------------------------------------------------------------------
    # Client & Credit Account
    # ------------------------------------------------------------------
    client = get_object_or_404(
        Client.objects.select_related("credit_account"),
        pk=client_id
    )
    account, _ = CreditAccount.objects.get_or_create(client=client)

    # ------------------------------------------------------------------
    # Credit Logs (audit / ops)
    # ------------------------------------------------------------------
    logs = account.logs.select_related("authorised_by").order_by("-created_at")

    # ------------------------------------------------------------------
    # Legacy + current credit-related transactions (for reference only)
    # ------------------------------------------------------------------
    transactions = (
        Transaction.objects
        .select_related("invoice")
        .filter(
            client=client,
            transaction_type__in=[
                "credit_usage",
                "credit_repayment",
                "credit_issue",
                "adjustment",
            ],
        )
        .order_by("-created_at", "-id")
    )

    # ------------------------------------------------------------------
    # Account-level snapshots
    # ------------------------------------------------------------------
    credit_limit = account.credit_limit or Decimal("0.00")
    credit_used = account.credit_used or Decimal("0.00")
    credit_available = (
        credit_limit - credit_used if credit_limit > 0 else Decimal("0.00")
    )
    percent_used = (
        Decimal("0.00")
        if credit_limit == 0
        else (credit_used / credit_limit) * Decimal("100")
    )

    # ------------------------------------------------------------------
    # Open credit exposure per invoice
    # ------------------------------------------------------------------
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

    open_credit_total = credit_used  # authoritative snapshot

    # ------------------------------------------------------------------
    # Credit Ledger with Running Outstanding Balance
    # ------------------------------------------------------------------
    # Oldest → newest for correct running math
    credit_entries = list(
        account.entries
        .select_related("invoice", "transaction")
        .order_by("posted_at", "id")
    )

    running_balance = Decimal("0.00")

    for entry in credit_entries:
        # Outstanding balance logic (IMPORTANT)
        if entry.kind in [CreditEntry.USAGE, CreditEntry.ADJUSTMENT]:
            running_balance += entry.amount

        elif entry.kind in [CreditEntry.REPAYMENT, CreditEntry.WRITEOFF]:
            running_balance -= entry.amount

        # NOTE:
        # - ISSUE affects credit_limit only
        # - LIMIT_DECREASE affects credit_limit only
        # They MUST NOT touch outstanding balance

        entry.running_balance = running_balance

    # Latest entry first for UI
    credit_entries.reverse()

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    return render(
        request,
        "credit/credit_view.html",
        {
            "client": client,
            "account": account,
            "logs": logs,
            "transactions": transactions,

            "credit_limit": credit_limit,
            "credit_used": credit_used,
            "credit_available": credit_available,
            "percent_used": percent_used.quantize(Decimal("0.01")),

            "open_invoices": open_invoices,
            "open_credit_total": open_credit_total,

            # Ledger
            "credit_entries": credit_entries,
        },
    )


@login_required
@staff_required
@require_POST
def credit_confirm_payment(request, client_id):
    client = get_object_or_404(Client, pk=client_id)

    amount = Decimal(request.POST.get("amount", "0"))
    reference = request.POST.get("reference", "").strip()

    if amount <= 0:
        messages.error(request, "Amount must be greater than zero.")
        return redirect("credit-client-view", client_id=client.id)

    # Create the transaction (this will automatically create CreditEntry)
    tx = Transaction.objects.create(
        client=client,
        amount=amount,
        transaction_type="credit_repayment",
        reference=reference,
    )

    # Refresh CreditAccount to get updated credit_used
    ca = CreditAccount.objects.get(client=client)
    ca.refresh_from_db()

    # Print outcomes
    print("=== Credit Repayment Recorded ===")
    print(f"Transaction ID: {tx.id}")
    print(f"Client: {tx.client}")
    print(f"Amount: {tx.amount}")
    print(f"Transaction Type: {tx.transaction_type}")
    print(f"Business balance snapshot: {tx.balance}")
    print(f"Client balance snapshot: {tx.client_balance}")

    # Fetch the CreditEntry that was automatically created
    credit_entry = CreditEntry.objects.filter(
        credit_account__client_id=tx.client_id,  # <--- correct
        kind="repayment",
        amount=tx.amount,
    ).order_by("-posted_at").first()

    if credit_entry:
        print("--- Linked CreditEntry ---")
        print(f"CreditEntry ID: {credit_entry.id}")
        print(f"Kind: {credit_entry.kind}")
        print(f"Amount: {credit_entry.amount}")
        print(f"CreditAccount ID: {credit_entry.credit_account_id}")
        print(f"CreditAccount.credit_used: {credit_entry.credit_account.credit_used}")
        print(f"CreditAccount.credit_limit: {credit_entry.credit_account.credit_limit}")
    else:
        print("No CreditEntry linked!")

    messages.success(request, "Credit repayment recorded successfully.")
    return redirect("credit-view", client_id=client.id)

def generate_payfast_request(request, invoice_id):
    invoice = get_object_or_404(
        Invoice.objects.select_related("order", "order__client"),
        pk=invoice_id
    )

    data = [
        ("merchant_id", settings.PAYFAST_MERCHANT_ID),
        ("merchant_key", settings.PAYFAST_MERCHANT_KEY),
        ("return_url", "https://yourdomain.co.za/payfast/return/"),
        ("cancel_url", "https://yourdomain.co.za/payfast/cancel/"),
        ("notify_url", "https://yourdomain.co.za/payfast/itn/"),

        ("name_first", invoice.order.client.contact_person.split()[0]),
        ("name_last", invoice.order.client.contact_person.split()[-1]),
        ("email_address", invoice.order.client.email),

        ("m_payment_id", f"INV-{invoice.id}"),
        ("amount", f"{invoice.amount_due:.2f}"),
        ("item_name", f"Invoice #{invoice.id}"),
    ]

    signature = generate_payfast_signature(
        data=data,
        passphrase=settings.PAYFAST_PASSPHRASE
    )

    payfast_data = dict(data)
    payfast_data["signature"] = signature

    # Build the full PayFast URL
    from urllib.parse import urlencode
    payfast_link = f"{settings.PAYFAST_PROCESS_URL}?{urlencode(payfast_data)}"

    return JsonResponse({"payment_url": payfast_link})

def generate_payfast_signature(data, passphrase):
    parts = []

    for key, value in data:
        if value != "":
            parts.append(f"{key}={urllib.parse.quote_plus(str(value))}")

    param_string = "&".join(parts)

    if passphrase:
        param_string += "&passphrase=" + urllib.parse.quote_plus(passphrase)

    print("\nPAYFAST PARAM STRING (FINAL):")
    print(param_string)

    signature = hashlib.md5(param_string.encode("utf-8")).hexdigest()

    print("PAYFAST SIGNATURE:")
    print(signature)

    return signature


@login_required
@staff_required
def credit_send_request(request, client_id):
    client = get_object_or_404(Client, pk=client_id)

    if not client.email:
        return JsonResponse(
            {"success": False, "message": "Client has no email"},
            status=400
        )

    credit_account = get_object_or_404(CreditAccount, client=client)

    outstanding = credit_account.credit_used or Decimal("0.00")

    if outstanding <= 0:
        return JsonResponse(
            {"success": False, "message": "No outstanding credit to repay"},
            status=400
        )

    # --- Generate PayFast link ---
    data = [
        ("merchant_id", settings.PAYFAST_MERCHANT_ID),
        ("merchant_key", settings.PAYFAST_MERCHANT_KEY),
        ("return_url", "https://yourdomain.co.za/payfast/return/"),
        ("cancel_url", "https://yourdomain.co.za/payfast/cancel/"),
        ("notify_url", "https://yourdomain.co.za/payfast/itn/"),
        ("name_first", client.contact_person.split()[0]),
        ("name_last", client.contact_person.split()[-1]),
        ("email_address", client.email),
        ("m_payment_id", f"CR-{client.id}"),
        ("amount", f"{outstanding:.2f}"),
        ("item_name", f"Credit Repayment – {client.name}"),
    ]

    signature = generate_payfast_signature(
        data,
        passphrase=settings.PAYFAST_PASSPHRASE
    )

    payfast_data = dict(data)
    payfast_data["signature"] = signature

    payfast_link = (
        f"{settings.PAYFAST_PROCESS_URL}?"
        f"{urllib.parse.urlencode(payfast_data)}"
    )

    # --- Prepare Email ---
    subject = f"The Daily Market – Credit Repayment Request"

    ctx = {
        "client": client,
        "credit_account": credit_account,
        "outstanding": outstanding,
        "payfast_link": payfast_link,
        "support_email": getattr(
            settings,
            "SUPPORT_EMAIL",
            "support@thedailymarket.co.za",
        ),
    }

    text_body = render_to_string(
        "email/payfast_credit_request.txt",
        ctx
    )
    html_body = render_to_string(
        "email/payfast_credit_request.html",
        ctx
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[client.email],
        headers={"Reply-To": ctx["support_email"]},
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

    return JsonResponse({
        "success": True,
        "message": "Credit repayment request sent successfully."
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
