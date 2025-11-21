# credit/views.py
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import F, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from clients.models import Client
from transactions.models import Transaction   # ← ADD THIS
from .models import CreditAccount, CreditLog
from .forms import CreditEditForm

from django.db.models import F, Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from django.db import transaction

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render

from clients.models import Client
from .models import CreditAccount, CreditLog
from .forms import CreditEditForm



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
    client = get_object_or_404(Client, pk=client_id)
    account, _created = CreditAccount.objects.get_or_create(client=client)

    if request.method == "POST":
        form = CreditEditForm(request.POST)
        if form.is_valid():
            new_account_type = form.cleaned_data["account_type"]
            new_credit_status = form.cleaned_data["credit_status"]
            new_limit = form.cleaned_data["credit_limit"]
            note = form.cleaned_data.get("note") or ""
            new_funder = form.cleaned_data.get("funder")  # <- make sure form has this

            with transaction.atomic():
                # 1) Update client fields first (if changed)
                updates_client = []
                if client.account_type != new_account_type:
                    client.account_type = new_account_type
                    updates_client.append("account_type")
                if client.credit_status != new_credit_status:
                    client.credit_status = new_credit_status
                    updates_client.append("credit_status")
                if updates_client:
                    client.save(update_fields=updates_client)

                # 2) Persist funder on the CreditAccount BEFORE any limit change
                updates_account = []
                if account.funder_id != (new_funder.pk if new_funder else None):
                    account.funder = new_funder
                    updates_account.append("funder")
                if updates_account:
                    account.save(update_fields=updates_account + ["updated_at"])

                # 3) Change limit via the audited path (this creates CreditLog + ledger entries)
                prev_limit = account.credit_limit or Decimal("0.00")
                if new_limit != prev_limit:
                    # IMPORTANT: do NOT set account.credit_limit directly.
                    account.set_limit(
                        new_limit,
                        authorised_by=request.user,
                        note=note,
                    )
                    # No need to call CreditLog.objects.create() here—set_limit does it.

            messages.success(request, "Credit details updated.")
            return redirect("credit-view", client_id=client.id)
    else:
        form = CreditEditForm(initial={
            "account_type": client.account_type,
            "credit_status": client.credit_status,
            "credit_limit": account.credit_limit,
            "funder": account.funder_id,  # prefill funder
            "note": "",
        })

    # Snapshot numbers for the page
    limit_ = account.credit_limit or Decimal("0.00")
    used_ = account.credit_used or Decimal("0.00")
    available_ = account.credit_available  # property

    return render(request, "credit/credit_edit.html", {
        "client": client,
        "account": account,
        "form": form,
        "limit": limit_,
        "used": used_,
        "available": available_,
    })


@login_required
@staff_required
def credit_client_view(request, client_id):
    client = get_object_or_404(Client.objects.select_related("credit_account"), pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)

    logs = account.logs.select_related("authorised_by").order_by("-created_at")
    tx_qs = (
        Transaction.objects
        .select_related("invoice")
        .filter(
            client=client,
            transaction_type__in=["credit_usage", "credit_repayment", "credit_issue", "adjustment"]
        )
        .order_by("-created_at", "-id")
    )

    limit_ = account.credit_limit or Decimal("0.00")
    used_  = account.credit_used  or Decimal("0.00")
    avail_ = (limit_ - used_) if limit_ > 0 else Decimal("0.00")
    pct    = Decimal("0.00") if limit_ == 0 else (used_ / limit_) * Decimal("100")

    return render(request, "credit/credit_view.html", {
        "client": client,
        "account": account,
        "logs": logs,
        "transactions": tx_qs,
        "credit_limit": limit_,
        "credit_used": used_,
        "credit_available": avail_,
        "percent_used": pct.quantize(Decimal("0.01")),
    })
