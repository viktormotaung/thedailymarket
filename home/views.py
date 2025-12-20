
from __future__ import annotations
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import SupplierLead, HeroSlide 
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from suppliers.models import Supplier
from profiles.models import CustomerProfile
from profiles.forms import PersonalProfileForm
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

from decimal import Decimal, InvalidOperation
from typing import Iterable

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Prefetch
from django.shortcuts import render, get_object_or_404
from django.utils.functional import cached_property
from django.db import transaction, IntegrityError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from clients.models import Client
from products.models import Product
from orders.models import Order

from django.db import transaction
from tasks.models import Task
from orders.models import Order, OrderItem
from clients.models import Client
from products.models import Product, Category
from django.contrib.contenttypes.models import ContentType
from django.core.mail import EmailMessage
from django.db.models.functions import Coalesce

from products.models import Product, Category, ProductPricing

from products.models import Product  # adjust import path
  
from django.contrib import messages
from django.db import transaction
from .forms import RegisterUserForm, ClientFullForm, CustomerProfileForm
from django.db.models import Q, Prefetch
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.views import View
from functools import wraps
from decimal import Decimal, ROUND_HALF_UP
from django.http import JsonResponse, HttpRequest, HttpResponse
from datetime import timedelta, datetime
from decimal import Decimal
from typing import List, Tuple, Optional, Dict
from django.utils.timezone import now
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.db.models.functions import Coalesce, ExtractWeek, ExtractYear
from clients.models import Client
from invoices.models import Invoice
from credit.models import CreditAccount, CreditEntry
from django.utils.http import urlencode
from django.contrib.auth import get_user_model
import hashlib
from clients.forms import ClientBusinessForm
from django.db.models import OuterRef, Subquery, Value, Q
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.contrib.auth.hashers import make_password
from django.core import signing
from django.core.mail import send_mail
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
from django.middleware.csrf import get_token
from profiles.models import CustomerProfile, StaffProfile, SalesRepProfile  
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery, F
from django.db.models.functions import Coalesce
from django.shortcuts import render
from typing import Optional, Tuple
from clients.forms import ClientMinimalForm
from .forms import UserProfileForm
from invoices.models import Invoice
from credit.models import CreditAccount, CreditEntry
from invoices.models import Invoice
from orders.models import Order
from credit.models import FunderMember 
from clients.models import Client
from django.db.models import OuterRef, Subquery, Value, DateTimeField
import random
from django.db.models import (
    Sum, Q, DecimalField, IntegerField, OuterRef, Subquery, F, Value
)

User = get_user_model()
# Optional variants support (only if you created ProductVariant)
try:
    from products.models import ProductVariant
except Exception:
    ProductVariant = None

D0 = Decimal("0.00")
VAT_DEFAULT = Decimal("15.00")  # 15% SA standard

# Optional: if you want to compute spend from orders
try:
    from orders.models import Order
    HAS_ORDERS = True
except Exception:
    HAS_ORDERS = False
import logging
log = logging.getLogger(__name__)

# lifetimes (suggested values)
PWRESET_OTP_TTL_SECONDS = 120        # 2 minutes for 4-digit OTP
PWRESET_TOKEN_TTL_SECONDS = 600      # 10 minutes for token used across steps
PWRESET_VERIFIED_TTL_SECONDS = 600   # 10 minutes to allow completing reset after OTP verify
PWRESET_SALT = "seshibo_pwreset_v1"

# --- Trade Assist config ---
REQ_WEEKS_MIN   = 4   # may request credit after 4 consecutive pre-paid weeks
REQ_WEEKS_MAX   = 8   # guaranteed activation after 8 consecutive pre-paid weeks
ASSIST_RATIO_PCT = 70 # projected limit as % of avg weekly spend
SETTLE_DAYS      = 3  # days to settle TA-funded invoices

def _week_key(dt):
    return (dt.isocalendar().year, dt.isocalendar().week)

# ---------- helpers ----------
def resolve_client_for_user(user, request=None):
    """
    Canonical path for your setup:
    User -> user.customer_profile -> effective_client (business Client or None).
    Staff can optionally preview another client via ?client_id=...
    """
    # Optional staff preview: /wholesale_assist/?client_id=123
    if request and (user.is_staff or user.is_superuser):
        cid = request.GET.get("client_id")
        if cid:
            return Client.objects.filter(pk=cid).first()

    prof = getattr(user, "customer_profile", None)
    if prof:
        return prof.effective_client  # returns client if BUSINESS, else None

    return None


def _compute_weekly_spend_and_streak(client, *, weeks: int = 12):
    """
    Returns (labels[], amounts[], consecutive_weeks_int).
    amounts[i] corresponds to labels[i], newest first.
    """
    labels, amounts = [], []
    consecutive = 0

    if not HAS_ORDERS:
        return labels, amounts, consecutive

    # Consider only approved/complete orders as 'spend'
    end = timezone.now()
    start = end - timedelta(weeks=weeks + 1)

    qs = (
        Order.objects.filter(
            client=client,
            submitted_at__range=(start, end),
            status__in=["approved", "complete"],
        )
        .annotate(week=TruncWeek("submitted_at"))
        .values("week")
        .annotate(total=Coalesce(Sum("grand_total_inc"), Decimal("0.00")))
        .order_by("week")
    )

    # Build a dense weekly timeline (oldest -> newest), then flip to newest first
    # Normalize to local week buckets
    bucket = {}
    for row in qs:
        wk = row["week"].date() if hasattr(row["week"], "date") else row["week"]
        bucket[wk] = Decimal(row["total"] or 0)

    # Generate week starts from the most recent backwards
    today = timezone.localdate()
    # Align to the start of week (Mon)
    start_of_this_week = today - timedelta(days=today.weekday())
    weeks_list = [start_of_this_week - timedelta(weeks=i) for i in range(0, weeks)]

    dense = [(wk, bucket.get(wk, Decimal("0.00"))) for wk in weeks_list]
    # newest first
    dense.sort(reverse=True)

    # Build outputs
    labels = [wk.strftime("%d %b") for wk, _ in dense]
    amounts = [amt for _, amt in dense]

    # Compute consecutive non-zero weeks, newest backwards
    for amt in amounts:
        if amt > 0:
            consecutive += 1
        else:
            break

    return labels, amounts, consecutive


def _avg_nonzero(values):
    vals = [Decimal(v) for v in values if Decimal(v) > 0]
    if not vals:
        return Decimal("0.00")
    return sum(vals) / Decimal(len(vals))

# --------- Helper: resolve which Client to show for this user ----------
def _resolve_client_for_user(user, *, request=None) -> Client | None:
    """
    Resolve the 'business client' linked to the current user.

    Staff / superuser:
      - Can pass ?client_id= in the querystring to view any client.

    Non-staff:
      - Return the single Client linked to this user, if any.
        Adjust this logic to match your actual relation (profile → client, etc.).
    """
    if not user.is_authenticated:
        return None

    # Staff override: ?client_id=123
    if (user.is_staff or user.is_superuser) and request:
        cid = (request.GET.get("client_id") or "").strip()
        if cid.isdigit():
            return get_object_or_404(Client, pk=int(cid))

    # Non-staff (and staff without a query): infer from known relations
    # Adjust these branches to match your project’s links.
    # 1) If Client has a direct OneToOne to User (rare):
    try:
        return Client.objects.filter(user=user).first()  # type: ignore[attr-defined]
    except Exception:
        pass

    # 2) If there’s a CustomerProfile that points to a Client:
    try:
        profile = getattr(user, "customerprofile", None)
        if profile and getattr(profile, "client_id", None):
            return profile.client
    except Exception:
        pass

    # 3) If your Client model stores a contact email you map from user.email, etc.
    try:
        if getattr(user, "email", ""):
            c = Client.objects.filter(email__iexact=user.email).first()
            if c:
                return c
    except Exception:
        pass

    return None


@login_required
def payfast_start(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    invoice_id = request.POST.get("invoice_id")
    amount_raw = request.POST.get("amount")

    # Basic validation
    if not invoice_id or not amount_raw:
        return HttpResponseBadRequest("Missing parameters")

    # Optional: verify invoice & outstanding matches your DB to prevent tampering
    # try:
    #     inv = Invoice.objects.get(pk=invoice_id, client__user=request.user)
    # except Invoice.DoesNotExist:
    #     raise Http404("Invoice not found")
    # if Decimal(amount_raw).quantize(Decimal("0.01")) != inv.ta_outstanding.quantize(Decimal("0.01")):
    #     return HttpResponseBadRequest("Amount mismatch")

    # Prepare PayFast payload
    amount = _format_amount(Decimal(amount_raw))
    merchant_id = settings.PAYFAST_MERCHANT_ID
    merchant_key = settings.PAYFAST_MERCHANT_KEY
    passphrase = getattr(settings, "PAYFAST_PASSPHRASE", "")

    # Build absolute return / notify / cancel URLs
    return_url = request.build_absolute_uri(reverse("payfast_return"))
    cancel_url = request.build_absolute_uri(reverse("payfast_cancel"))
    notify_url = request.build_absolute_uri(reverse("payfast_notify"))

    # Payment “item” info
    item_name = f"TA Invoice #{invoice_id}"
    m_payment_id = f"INV{invoice_id}"  # your internal reference

    # Payer details (best-effort)
    first = getattr(request.user, "first_name", "") or "Customer"
    last = getattr(request.user, "last_name", "") or "User"
    email = getattr(request.user, "email", "") or "customer@example.com"

    data = {
        "merchant_id": merchant_id,
        "merchant_key": merchant_key,
        "return_url": return_url,
        "cancel_url": cancel_url,
        "notify_url": notify_url,
        "m_payment_id": m_payment_id,
        "amount": amount,
        "item_name": item_name,
        # optional meta
        "name_first": first[:100],
        "name_last": last[:100],
        "email_address": email[:100],
        # Custom vars you can read back in ITN (notify):
        "custom_str1": str(invoice_id),
        "custom_str2": "trade_assist",
    }

    # Signature (if passphrase configured)
    signature = _build_signature(data, passphrase=passphrase)
    data["signature"] = signature

    # Render auto-posting form to PayFast sandbox endpoint
    payfast_action = "https://sandbox.payfast.co.za/eng/process"  # switch to live when ready
    return render(request, "payments/payfast_redirect.html", {
        "action": payfast_action,
        "fields": data,
    })

@login_required
def wholesale_assist(request):
    """
    Trade Assist eligibility + snapshot.

    Eligibility uses *pre-paid* history:
      - invoices.status='paid'
      - paid_date not null and within last 8 weeks (rolling)
      - credit_used == 0 (i.e. not funded by TA)
      - bucket by ISO week (paid_date)

    TA snapshot (Active section) uses TA-funded invoices (credit_used > 0):
      - Next Due (TA): earliest due_date >= today with outstanding > 0
      - Overdue (TA): due_date < today with outstanding > 0
    """
    # ---- 0) Resolve client for this user ----
    try:
        client = resolve_client_for_user(request.user, request=request)
    except Exception:
        # If you use a differently named helper (e.g., _resolve_client_for), fall back:
        from .views_helpers import _resolve_client_for  # adjust path if needed
        client = _resolve_client_for(request.user)

    # ---- 1) Build the 8-week pre-paid window ----
    period_start = now().date() - timedelta(days=REQ_WEEKS_MAX * 7)

    inv_qs = Invoice.objects.none()
    if client:
        inv_qs = (
            Invoice.objects.filter(
                client=client,
                status="paid",
                paid_date__isnull=False,
                paid_date__gte=period_start,
                credit_used=Decimal("0.00"),   # exclude TA-funded spend
            )
        )

    weekly = (
        inv_qs
        .annotate(y=ExtractYear("paid_date"), w=ExtractWeek("paid_date"))
        .values("y", "w")
        .annotate(
            week_spend=Coalesce(
                Sum("order_total_inc", output_field=DecimalField()),
                Decimal("0.00"),
                output_field=DecimalField()
            )
        )
        .order_by("-y", "-w")
    )

    weekly_list  = list(weekly)
    weekly_spend = [row["week_spend"] for row in weekly_list]  # recent → older
    week_labels  = [f'{int(row["y"])}-W{int(row["w"]):02d}' for row in weekly_list]

    non_zero_weeks = [Decimal(amt) for amt in weekly_spend if amt and Decimal(amt) > 0]
    weeks_with_spend = len(non_zero_weeks)
    avg_weekly_spend = (sum(non_zero_weeks) / weeks_with_spend) if weeks_with_spend else Decimal("0.00")

    # Count consecutive non-zero ISO weeks from most recent backwards
    non_zero_keys = {(int(r["y"]), int(r["w"])) for r in weekly_list if r["week_spend"] and Decimal(r["week_spend"]) > 0}

    def previous_iso_week(y: int, w: int) -> tuple[int, int]:
        d = date.fromisocalendar(y, int(w), 1) - timedelta(days=7)
        ic = d.isocalendar()
        return ic.year, ic.week

    if weekly_list:
        cur_y, cur_w = int(weekly_list[0]["y"]), int(weekly_list[0]["w"])
    else:
        ic = now().date().isocalendar()
        cur_y, cur_w = ic.year, ic.week

    consecutive_weeks = 0
    for _ in range(REQ_WEEKS_MAX):
        if (cur_y, cur_w) in non_zero_keys:
            consecutive_weeks += 1
            cur_y, cur_w = previous_iso_week(cur_y, cur_w)
        else:
            break

    can_request_credit = consecutive_weeks >= REQ_WEEKS_MIN
    guaranteed_credit  = consecutive_weeks >= REQ_WEEKS_MAX
    qualifying_progress = min(consecutive_weeks / REQ_WEEKS_MAX, 1.0)

    projected_limit = (
        (avg_weekly_spend * Decimal(ASSIST_RATIO_PCT) / Decimal("100"))
        .quantize(Decimal("0.01"))
    )

    # ---- 2) No linked client -> eligibility panel only ----
    if not client:
        return render(request, "home/wholesale_assist.html", {
            "client": None,
            "is_staff_viewing": request.user.is_staff or request.user.is_superuser,

            "consecutive_weeks": consecutive_weeks,
            "req_weeks_min": REQ_WEEKS_MIN,
            "req_weeks_max": REQ_WEEKS_MAX,
            "qualifying_progress": qualifying_progress,
            "weekly_spend": weekly_spend,
            "week_labels": week_labels,
            "projected_limit": projected_limit,
            "assist_ratio_pct": ASSIST_RATIO_PCT,
            "settle_days": SETTLE_DAYS,
            "can_request_credit": can_request_credit,
            "guaranteed_credit": guaranteed_credit,
        })

    # ---- 3) Per-client credit snapshot ----
    ca, _ = CreditAccount.objects.get_or_create(client=client)
    total_limit     = ca.credit_limit or Decimal("0.00")
    total_used      = ca.credit_used or Decimal("0.00")
    total_available = ca.credit_available
    percent_used_total = Decimal("0.00")
    if total_limit and total_limit != Decimal("0.00"):
        percent_used_total = (total_used / total_limit * Decimal("100")).quantize(Decimal("0.01"))

    credit_active = (getattr(client, "account_type", "") == "CREDIT" and getattr(client, "credit_status", "") == "ACTIVE")

    if not credit_active:
        # Show eligibility + snapshot even if not ACTIVE
        return render(request, "home/wholesale_assist.html", {
            "client": client,
            "is_staff_viewing": request.user.is_staff or request.user.is_superuser,

            "consecutive_weeks": consecutive_weeks,
            "req_weeks_min": REQ_WEEKS_MIN,
            "req_weeks_max": REQ_WEEKS_MAX,
            "qualifying_progress": qualifying_progress,
            "weekly_spend": weekly_spend,
            "week_labels": week_labels,
            "projected_limit": projected_limit,
            "assist_ratio_pct": ASSIST_RATIO_PCT,
            "settle_days": SETTLE_DAYS,
            "can_request_credit": can_request_credit,
            "guaranteed_credit": guaranteed_credit,

            "total_limit": total_limit,
            "total_used": total_used,
            "total_available": total_available,
            "percent_used_total": percent_used_total,
        })

    # ---- 4) Active TA: Next Due (TA) and Overdue (TA) ----
    today = now().date()

    # Treat outstanding as invoice.amount_due (positive) for TA-funded invoices (credit_used > 0)
    ta_unpaid = Invoice.objects.filter(
        client=client,
        credit_used__gt=Decimal("0.00"),
        amount_due__gt=Decimal("0.00")
    )

    # Next Due: earliest due_date >= today
    next_due_obj = (
        ta_unpaid
        .filter(due_date__isnull=False, due_date__gte=today)
        .order_by("due_date", "id")
        .values("id", "due_date", "amount_due")
        .first()
    )
    next_due = None
    if next_due_obj:
        next_due = type("NextDue", (), {
            "invoice_id": next_due_obj["id"],
            "due_date":   next_due_obj["due_date"],
            "outstanding": next_due_obj["amount_due"],
        })()

    # Overdue: due_date < today
    overdue_qs = (
        ta_unpaid
        .filter(due_date__isnull=False, due_date__lt=today)
        .order_by("due_date", "id")
        .values("id", "due_date", "amount_due")
    )

    overdue_list = []
    for row in overdue_qs:
        dd = row["due_date"]
        overdue_list.append({
            "invoice_id":  row["id"],
            "due_date":    dd,
            "outstanding": row["amount_due"],
            "days_overdue": (today - dd).days,
        })
    overdue = bool(overdue_list)

    # ---- 5) Movements (ledger) on CreditAccount ----
    try:
        limit = max(1, min(int(request.GET.get("limit") or 50), 200))
    except Exception:
        limit = 50

    ledger = (
        ca.entries
        .select_related("invoice")
        .order_by("-posted_at", "-id")
    )[:limit]

    return render(request, "home/wholesale_assist.html", {
        "client": client,
        "is_staff_viewing": request.user.is_staff or request.user.is_superuser,

        # ACTIVE snapshot
        "status": "Active",
        "assist_limit": total_limit,
        "assist_available": total_available,
        "assist_used": total_used,
        "assist_ratio_pct": ASSIST_RATIO_PCT,
        "projected_limit": projected_limit,
        "settle_days": SETTLE_DAYS,

        # Dues
        "next_due": next_due,
        "overdue": overdue,
        "overdue_list": overdue_list,

        # Movements
        "ledger": ledger,
        "ledger_limit": limit,

        # Totals (same semantics as credit_list)
        "total_limit": total_limit,
        "total_used": total_used,
        "total_available": total_available,
        "percent_used_total": percent_used_total,

        # thresholds for banners
        "req_weeks_min": REQ_WEEKS_MIN,
        "req_weeks_max": REQ_WEEKS_MAX,
        "consecutive_weeks": consecutive_weeks,
        "weekly_spend": weekly_spend,
        "week_labels": week_labels,
    })

def home(request):
    suppliers = Supplier.objects.filter(
        is_active=True,
        visible=True
    ).only("id", "name", "logo").order_by("name")

    hero_slides = HeroSlide.objects.filter(
        is_active=True
    ).order_by("sort_order", "id")[:3]  # limit to 3

    return render(
        request,
        "home/index.html",
        {
            "suppliers": suppliers,
            "hero_slides": hero_slides,
        }
    )

def logout_view(request):
    logout(request)
    return redirect('home')

@require_http_methods(["GET", "POST"])
def staff_login(request):
    """
    Unified sign-in for:
      - Staff portal
      - Lender portal
      - Sales portal

    After successful login, always show a modal:
      "Your profile has access to the following portal/s, please choose one"
    with 3 buttons: Main, Lender, Sales.
    Buttons are enabled/disabled based on access.
    """
    if request.method == "GET":
        return render(request, "home/staff_login.html", {
            "prefill_username": request.GET.get("username", "").strip(),
        })

    # POST
    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""

    ctx = {"prefill_username": username}

    # 1) User existence (case-insensitive)
    user = User.objects.filter(username__iexact=username).first()
    if not user:
        ctx.update({
            "show_modal": True,
            "modal_title": "We couldn't find an account",
            "modal_message": "No user exists with that username. Please check and try again.",
        })
        return render(request, "home/staff_login.html", ctx)

    # 2) Credentials
    authed = authenticate(request, username=user.username, password=password)
    if not authed:
        ctx.update({
            "show_modal": True,
            "modal_title": "Invalid username or password",
            "modal_message": "Please try again. If you’ve forgotten your password, use the Reset link below.",
        })
        return render(request, "home/staff_login.html", ctx)

    # 3) Figure out roles
    has_active_funder_membership = FunderMember.objects.filter(
        user=authed, is_active=True
    ).exists()

    is_staff_user = authed.is_staff

    # ✅ New: check active SalesRepProfile
    has_active_sales_rep = SalesRepProfile.objects.filter(
        user=authed, status="active"
    ).exists()

    # If neither staff nor funder nor sales rep → deny
    if not is_staff_user and not has_active_funder_membership and not has_active_sales_rep:
        ctx.update({
            "show_modal": True,
            "modal_title": "Not authorized",
            "modal_message": (
                "Your account isn’t enabled for staff, lender, or sales access. "
                "Please contact support@seshibodailymarket.co.za."
            ),
        })
        return render(request, "home/staff_login.html", ctx)

    # 4) StaffProfile gating ONLY for staff portal access
    staff_profile = None
    staff_status = None

    if is_staff_user:
        staff_profile = getattr(authed, "staff_profile", None)
        if staff_profile is None:
            ctx.update({
                "show_modal": True,
                "modal_title": "Profile not linked",
                "modal_message": "Your account does not have a staff profile linked. Please contact support@seshibodailymarket.co.za.",
            })
            return render(request, "home/staff_login.html", ctx)

        staff_status = (getattr(staff_profile, "status", "") or "").upper()  # 'PENDING'/'ACTIVE'/'INACTIVE'
        if staff_status != "ACTIVE":
            if staff_status == "PENDING":
                ctx.update({
                    "show_modal": True,
                    "modal_title": "Profile pending verification",
                    "modal_message": "Your profile is being verified. A confirmation email will be sent shortly.",
                })
            else:
                ctx.update({
                    "show_modal": True,
                    "modal_title": "Profile inactive",
                    "modal_message": "Your profile is not active. Please contact support@seshibodailymarket.co.za.",
                })
            return render(request, "home/staff_login.html", ctx)

    # 5) All good → sign in
    login(request, authed)

    # 6) Lender membership bookkeeping (keep your existing behaviour minus the auto-redirect)
    memberships = []
    if has_active_funder_membership:
        memberships = list(
            FunderMember.objects.select_related("funder")
            .filter(user=authed, is_active=True)
            .order_by("funder__name")
        )
        request.session["lender_funders"] = [m.funder_id for m in memberships]

        if len(memberships) == 1:
            # remember selection
            request.session["current_funder_id"] = memberships[0].funder_id
        else:
            # multiple funders: let lender dashboard present a picker
            request.session.pop("current_funder_id", None)
    else:
        request.session.pop("lender_funders", None)
        request.session.pop("current_funder_id", None)

    # 7) Determine portal access flags

    # Main (staff) portal: must be staff with ACTIVE StaffProfile
    can_staff_portal = bool(
        is_staff_user
        and staff_profile is not None
        and (staff_status or "").upper() == "ACTIVE"
    )

    # Sales portal:
    #  - either active SalesRepProfile
    #  - or staff with ACTIVE StaffProfile and can_access_sales=True
    sales_flag_from_staff = bool(
        staff_profile is not None
        and getattr(staff_profile, "can_access_sales", False)
        and (staff_status or "").upper() == "ACTIVE"
    )
    can_sales_portal = bool(has_active_sales_rep or sales_flag_from_staff)

    # Lender portal: has any active lender membership
    can_lender_portal = bool(has_active_funder_membership)

    # 8) Show portal selection modal instead of redirecting
    ctx = {
        "prefill_username": authed.username,
        "show_portal_modal": True,
        "can_staff_portal": can_staff_portal,
        "can_lender_portal": can_lender_portal,
        "can_sales_portal": can_sales_portal,
    }

    return render(request, "home/staff_login.html", ctx)


@require_http_methods(["GET", "POST"])
def consumer_login(request):
    return render(request, "home/consumer_login.html")


class ClientLoginView(View):
    template_name = "home/login_client.html"
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        # Already logged in? Go home.
        if self.redirect_authenticated_user and request.user.is_authenticated:
            return redirect(self.get_success_url())

        # Safe prefill (e.g., when redirected back with ?username=…)
        ctx = {
            "prefill_username": (request.GET.get("username") or "").strip(),
            # No modal by default on GET
        }
        return render(request, self.template_name, ctx)

    def post(self, request, *args, **kwargs):
        # Already logged in? Go home.
        if self.redirect_authenticated_user and request.user.is_authenticated:
            return redirect(self.get_success_url())

        # Email-as-username
        email = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        # Keep what the user typed
        ctx = {
            "prefill_username": email,
        }

        # 1) Does a user exist with this email-as-username?
        user = User.objects.filter(username__iexact=email).first()
        if not user:
            ctx.update({
                "show_modal": True,
                "modal_kind": "user_not_found",
                "modal_title": "We couldn't find an account",
                "modal_message": "No user exists with that email. Please check the email or register a new account.",
            })
            return render(request, self.template_name, ctx)

        # 2) Check credentials
        authed = authenticate(request, username=user.username, password=password)
        if not authed:
            ctx.update({
                "show_modal": True,
                "modal_kind": "invalid_credentials",
                "modal_title": "Invalid email or password",
                "modal_message": "Please try again. If you’ve forgotten your password, use the Reset link below.",
            })
            return render(request, self.template_name, ctx)

        # 3) Check linked customer profile + status
        profile = getattr(user, "customer_profile", None)
        if not profile:
            ctx.update({
                "show_modal": True,
                "modal_kind": "no_profile",
                "modal_title": "Profile not linked",
                "modal_message": "Your account does not have a customer profile linked. Please contact support@seshibodailymarket.co.za.",
            })
            return render(request, self.template_name, ctx)

        status = (profile.status or "").upper()  # "PENDING" / "ACTIVE" / "INACTIVE"
        if status != "ACTIVE":
            if status == "PENDING":
                ctx.update({
                    "show_modal": True,
                    "modal_kind": "status_pending",
                    "modal_title": "Profile pending verification",
                    "modal_message": "Your profile is being verified. A confirmation email will be sent shortly.",
                })
            else:
                ctx.update({
                    "show_modal": True,
                    "modal_kind": "status_inactive",
                    "modal_title": "Profile inactive",
                    "modal_message": "Your profile is not active. Please contact support@seshibodailymarket.co.za.",
                })
            return render(request, self.template_name, ctx)

        # 4) All good → log in and redirect
        login(request, authed)
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("home")
#

@login_required
def client_dashboard(request):
    # Optional: gate by group later (e.g., 'client_owner' or 'client_staff')
    return render(request, "home/dashboard_client.html")

def _to_decimal(val, default: Decimal = Decimal("0")) -> Decimal:
    if val in (None, "",):
        return default
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError):
        return default

def _attach_display_price(p: Product) -> None:
    """
    Headline price = WHOLESALE (ex VAT) only.
    Fallback: first active supplier row's ex-VAT price (from supplier).
    """
    p.display_price_excl = None
    p.display_price_inc = None
    p.display_price_label = None

    # 1) Wholesale first (ex VAT)
    if p.wholesale_price:
        p.display_price_excl = p.wholesale_price
        p.display_price_label = "Wholesale"
        return

    # 2) Fallback to first active supplier row (ex VAT only)
    rows: Iterable[ProductPricing] = getattr(p, "pricing_rows_all_prefetched", None) or p.pricing_rows.all()
    row = next((r for r in rows if getattr(r, "is_active", True)), None)
    if row:
        # keep INC None so the template renders "Excl VAT"
        p.display_price_excl = row.retail_price_excl
        p.display_price_inc = None
        p.display_price_label = "From supplier"
        return

    # Fall back to first active supplier row (prefetched)
    rows: Iterable[ProductPricing] = getattr(p, "pricing_rows_all_prefetched", None) or p.pricing_rows.all()
    row = next((r for r in rows if r.is_active), None)
    if row:
        # Use the computed properties from your model
        p.display_price_excl = row.retail_price_excl
        p.display_price_inc = row.retail_price_inc
        p.display_price_label = "From supplier"


def _effective_price_for_filtering(p: Product) -> Decimal:
    """
    Use the same value the card shows: wholesale ex VAT (or supplier ex VAT fallback).
    """
    if p.display_price_excl is not None:
        return p.display_price_excl
    if p.display_price_inc is not None:
        return p.display_price_inc
    return Decimal("0")





def products(request):
    # -------------------------
    # Read query params
    # -------------------------
    q = (request.GET.get("q") or "").strip()
    category_id = request.GET.get("category") or ""
    subcategory_id = request.GET.get("subcategory") or ""
    min_price = _to_decimal(request.GET.get("min_price"), None)
    max_price = _to_decimal(request.GET.get("max_price"), None)
    sort = (request.GET.get("sort") or "").strip()

    # -------------------------
    # Base queryset (perf-safe)
    # -------------------------
    qs = (
        Product.objects
        .select_related("category", "category__parent")
        .prefetch_related(
            Prefetch(
                "pricing_rows",
                queryset=ProductPricing.objects
                    .select_related("supplier")
                    .order_by("supplier__name"),
                to_attr="pricing_rows_all_prefetched",
            )
        )
    )

    # -------------------------
    # Text search
    # -------------------------
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(sku__icontains=q) |
            Q(category__name__icontains=q) |
            Q(category__parent__name__icontains=q)
        )

    # -------------------------
    # Category / Subcategory filtering
    # -------------------------
    if subcategory_id:
        # Most specific filter (subcategory wins)
        qs = qs.filter(category_id=subcategory_id)

    elif category_id:
        # Parent category → include all children
        qs = qs.filter(category__parent_id=category_id)

    # -------------------------
    # Pull into Python list
    # (needed for price logic)
    # -------------------------
    items = list(qs)

    for p in items:
        _attach_display_price(p)

    # -------------------------
    # Price range filtering
    # -------------------------
    if min_price is not None:
        items = [
            p for p in items
            if _effective_price_for_filtering(p) >= min_price
        ]

    if max_price is not None:
        items = [
            p for p in items
            if _effective_price_for_filtering(p) <= max_price
        ]

    # -------------------------
    # Sorting
    # -------------------------
    if sort in ("name", "-name"):
        items.sort(
            key=lambda p: (p.name or "").lower(),
            reverse=sort.startswith("-")
        )

    elif sort in ("price", "-price"):
        items.sort(
            key=lambda p: (
                _effective_price_for_filtering(p),
                (p.name or "").lower()
            ),
            reverse=sort.startswith("-")
        )

    elif sort == "-created":
        items.sort(
            key=lambda p: (p.created_at or p.id),
            reverse=True
        )

    else:
        # Default: Name A–Z
        items.sort(key=lambda p: (p.name or "").lower())

    # -------------------------
    # Pagination
    # -------------------------
    paginator = Paginator(items, 12)
    page = request.GET.get("page")

    try:
        page_obj = paginator.get_page(page)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.get_page(1)

    # -------------------------
    # Categories for UI
    # -------------------------
    categories = (
        Category.objects
        .filter(parent__isnull=True, is_active=True)
        .prefetch_related("children")
        .order_by("sort_order", "name")
    )

    # -------------------------
    # Context
    # -------------------------
    context = {
        "products": page_obj,          # Page object
        "categories": categories,      # Parents + children
        "q": q,
        "selected_category": category_id,
        "selected_subcategory": subcategory_id,
        "sort": sort,
        "min_price": min_price,
        "max_price": max_price,
    }

    return render(request, "home/products.html", context)


def _r2(x: Decimal | None) -> Decimal:
    if x is None:
        return Decimal("0.00")
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects
        .select_related("category")
        .prefetch_related(
            Prefetch(
                "pricing_rows",
                queryset=ProductPricing.objects
                    .select_related("supplier")
                    .order_by("-is_primary", "supplier_price_excl")
            ),
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.order_by("pack_size", "id")
            ),
        ),
        slug=slug,
    )

    # 🔹 We are wholesale-only on this view
    selected_channel = "wholesale"

    # --- 1. Base wholesale price (ex VAT) for this product ---
    def base_ex_for_product(p: Product) -> Decimal:
        # a) Prefer Product.wholesale_price (via helper)
        base = p.price_for_channel("wholesale")
        if base and base > 0:
            return _r2(base)

        # b) Fall back to first pricing row (already ordered primary/cheapest)
        row = next(iter(p.pricing_rows.all()), None)
        if not row:
            return Decimal("0.00")
        return _r2(row.wholesale_price_excl)

    base_ex_main = base_ex_for_product(product)

    # --- 2. Build variant list with a wholesale display_price_ex ---
    variant_list = []
    for v in product.variants.all():
        override = v.wholesale_price_override
        derived = v.wholesale_derived  # uses product.wholesale_price * pack_size when scalable

        if override not in (None, Decimal("0.00")):
            display = override
        elif derived not in (None, Decimal("0.00")):
            display = derived
        else:
            display = base_ex_main  # fall back to product base wholesale

        v.display_price_ex = _r2(display)
        variant_list.append(v)

    context = {
        "product": product,
        # 👇 This is now DEFINITELY wholesale ex VAT
        "wholesale_ex": base_ex_main,
        "selected_channel": selected_channel,  # template checks this
        "variants": variant_list,
        "typical_pack_sizes": [1.5, 2.5, 5, 10],
    }
    return render(request, "home/product_detail.html", context)

_CLIENT_HAS_USER_FK = any(f.name == "user" for f in Client._meta.fields)

def _resolve_client_for(user):
    """
    Best-effort way to find the logged-in user's company/client.
    Falls back gracefully if no direct link exists.
    """
    # 1) Direct OneToOne: user.client
    cli = getattr(user, "client", None)
    if cli:
        return cli

    # 2) Client.user FK (only if the field exists)
    if _CLIENT_HAS_USER_FK:
        match = Client.objects.filter(user_id=user.id).only("id").first()
        if match:
            return match

    # 3) Profile patterns
    prof = getattr(user, "profile", None)
    if prof:
        if getattr(prof, "client", None):
            return prof.client
        company = getattr(prof, "company", None)
        if company and hasattr(company, "client"):
            return company.client

    return None

def _resolve_client_for(user):
    """
    Try best-effort ways to resolve the logged-in user's Client.
    Priority:
      1) Client.user == user (if that FK/OneToOne exists)
      2) CustomerProfile(user=user).client (if your profile model links to Client)
      3) Match by email (last resort, if your Client stores an email)
    Returns: Client instance or None.
    """
    if not user.is_authenticated:
        return None

    # 1) Direct link on Client model (if exists)
    try:
        direct = Client.objects.filter(user=user).first()
        if direct:
            return direct
    except Exception:
        pass

    # 2) Through CustomerProfile (if present in project)
    if CustomerProfile is not None:
        try:
            prof = CustomerProfile.objects.select_related("client").filter(user=user).first()
            if prof and getattr(prof, "client_id", None):
                return prof.client
        except Exception:
            pass

    # 3) Email match fallback (be cautious if multiple matches possible)
    email = (user.email or "").strip()
    if email:
        try:
            by_email = Client.objects.filter(Q(email__iexact=email) | Q(contact_email__iexact=email)).first()
            if by_email:
                return by_email
        except Exception:
            pass

    return None


def _resolve_client_for(user):
    """
    Try to resolve the business Client record for this authenticated user.

    Priority:
      1) user.client (OneToOne / FK relation on Client model)
      2) Match Client by email (fallback, if configured that way)
    """
    if not user.is_authenticated:
        return None

    # 1) Direct relation: user.client
    try:
        return user.client
    except (AttributeError, Client.DoesNotExist):
        pass

    # 2) Fallback: match by email, if available
    if user.email:
        return Client.objects.filter(email__iexact=user.email).first()

    return None


@login_required
def orders(request):
    """
    Show ALL orders (no client filtering for now),
    annotated with latest invoice info.
    """

    # Base queryset: everything
    qs = (
        Order.objects
        .select_related("client")
        .annotate(
            sort_ts=Coalesce(
                "submitted_at",
                "order_date",
                "updated_at",
                Value(now()),
            )
        )
        .order_by("-sort_ts", "-id")
    )

    # Latest invoice per order
    latest_invoice = Invoice.objects.filter(order_id=OuterRef("pk")).order_by("-id")

    qs = qs.annotate(
        invoice_id=Subquery(latest_invoice.values("id")[:1]),
        invoice_status=Subquery(latest_invoice.values("status")[:1]),
        invoice_amount_due=Subquery(latest_invoice.values("amount_due")[:1]),
        invoice_due_date=Subquery(latest_invoice.values("due_date")[:1]),
    )

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page") or 1

    try:
        page_obj = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    context = {
        "orders_page": page_obj,          # page object
        "orders_total": paginator.count,  # simple integer
    }
    return render(request, "home/orders.html", context)

@login_required
def profile(request):
    user = request.user

    # ---- Resolve / create CustomerProfile ----
    customer_profile, _ = CustomerProfile.objects.get_or_create(
        user=user,
        defaults={
            "display_name": user.get_full_name() or user.username,
        }
    )

    # ---- Resolve / create Client ----
    client = resolve_client_for_user(user, request=request)

    # ================= USER PROFILE =================
    if request.method == "POST" and request.POST.get("form_type") == "user_profile":
        user_form = UserProfileForm(request.POST, instance=user)
        if user_form.is_valid():
            user_form.save()
            messages.success(request, "User profile updated successfully.")
            return redirect("profile")
    else:
        user_form = UserProfileForm(instance=user)

    # ================= BUSINESS PROFILE =================
    if request.method == "POST" and request.POST.get("form_type") == "business_profile":
        business_form = ClientBusinessForm(request.POST, instance=client)
        if business_form.is_valid():
            business_form.save()
            messages.success(request, "Business profile updated successfully.")
            return redirect("profile")
    else:
        business_form = ClientBusinessForm(instance=client)

    # ================= PERSONAL PROFILE =================
    if request.method == "POST" and request.POST.get("form_type") == "personal_profile":
        personal_form = PersonalProfileForm(request.POST, instance=customer_profile)
        if personal_form.is_valid():
            personal_form.save()
            messages.success(request, "Personal profile updated successfully.")
            return redirect("profile")
    else:
        personal_form = PersonalProfileForm(instance=customer_profile)

    return render(request, "home/profile.html", {
        "user_form": user_form,
        "business_form": business_form,
        "personal_form": personal_form,
        "client": client,
        "customer_profile": customer_profile,
    })

    
def _user_can_access_order(user, order) -> bool:
    if user.is_staff or user.is_superuser:
        return True
    # Try common links to Client
    linked_client_id = (
        getattr(getattr(user, "client", None), "id", None)
        or getattr(getattr(user, "profile", None), "client_id", None)
    )
    return linked_client_id == order.client_id

def _user_can_access_order(user, order: Order) -> bool:
    """Staff can view all orders; non-staff only their own client’s orders."""
    if not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    client = _resolve_client_for(user)
    return bool(client and order.client_id == client.id)


@login_required
def order_view(request, pk):
    """
    Order detail page with inline PayFast 'Pay now' button when invoice is unpaid.
    Expects settings:
      - PAYFAST_USE_SANDBOX (bool)
      - PAYFAST_PROCESS_URL (optional; else picked by USE_SANDBOX)
      - PAYFAST_MERCHANT_ID / PAYFAST_MERCHANT_KEY (pair must match sandbox/live)
      - PAYFAST_PASSPHRASE (optional, recommended)
    """
    # Fetch order (+ guard access)
    order = get_object_or_404(
        Order.objects.select_related("client").prefetch_related("items__product"),
        pk=pk,
    )
    if not _user_can_access_order(request.user, order):
        raise Http404("Order not found")

    # Invoice (robust fetch)
    invoice = getattr(order, "invoice", None) or Invoice.objects.filter(order_id=order.id).first()

    ctx = {
        "order": order,
        "invoice": invoice,
        "payfast_fields": None,
        "PAYFAST_PROCESS_URL": None,
    }

    # Nothing to prepare if there isn't an unpaid balance
    status = (getattr(invoice, "status", "") or "").lower() if invoice else ""
    amount_due = Decimal(getattr(invoice, "amount_due", 0) or 0) if invoice else Decimal("0.00")
    if not (invoice and status != "paid" and amount_due > 0):
        return render(request, "home/view_order.html", ctx)

    # Build absolute URLs from named routes (no namespace used in your urls.py)
    return_url = request.build_absolute_uri(reverse("payfast_return"))
    cancel_url = request.build_absolute_uri(reverse("payfast_cancel"))
    notify_url = request.build_absolute_uri(reverse("payfast_ipn"))

    # Format amount: 2 decimals, dot separator
    amt = amount_due.quantize(Decimal("0.01"))
    amount_str = f"{amt:.2f}"

    # Choose endpoint & creds (sandbox vs live)
    use_sandbox = getattr(settings, "PAYFAST_USE_SANDBOX", True)
    process_url = (
        getattr(settings, "PAYFAST_PROCESS_URL", None)
        or ("https://sandbox.payfast.co.za/eng/process" if use_sandbox else "https://www.payfast.co.za/eng/process")
    )
    merchant_id = getattr(settings, "PAYFAST_MERCHANT_ID", "")
    merchant_key = getattr(settings, "PAYFAST_MERCHANT_KEY", "")

    # Build the minimum required field set
    pf = {
        "merchant_id": merchant_id,
        "merchant_key": merchant_key,
        "return_url": return_url,
        "cancel_url": cancel_url,
        "notify_url": notify_url,
        "m_payment_id": (str(getattr(invoice, "uuid", "")) or f"INV-{invoice.id}"),
        "amount": amount_str,
        "item_name": f"Invoice {getattr(invoice, 'number', f'INV-{invoice.id}')}",
        "email_address": getattr(request.user, "email", "") or "",
        # Optional extras (uncomment as needed):
        # "name_first": request.user.first_name or "",
        # "name_last": request.user.last_name or "",
        # "custom_str1": str(request.user.id),
    }

    # Signature (recommended if you configured a passphrase in your PayFast dashboard)
    passphrase = getattr(settings, "PAYFAST_PASSPHRASE", "")
    if passphrase:
        # PayFast requires URL-encoded string of fields in key order + &passphrase=...
        query = urlencode(pf)
        sign_str = f"{query}&passphrase={passphrase}"
        pf["signature"] = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
        # If your account is set to SHA256, switch to:
        # pf["signature"] = hashlib.sha256(sign_str.encode("utf-8")).hexdigest()

    # Optional debug log to verify endpoint/merchant pairing
    log.info("PayFast post → url=%s id=%r key=%r amount=%s", process_url, merchant_id, merchant_key, amount_str)

    ctx.update({
        "payfast_fields": pf,
        "PAYFAST_PROCESS_URL": process_url,
    })
    return render(request, "home/view_order.html", ctx)


def about(request):
    return render(request, "home/about.html")

def grill(request):
    return render(request, "home/grill.html")

def retail(request):
    return render(request, "home/retail.html")

def wholesale(request):
    return render(request, "home/wholesale.html")


def contact(request):
    return render(request, "home/contact.html")

def trade_application(request):
    return render(request, "home/trade_application.html")

def become_supplier(request):
    if request.method == "POST":
        f = request.POST
        SupplierLead.objects.create(
            full_name=f.get("full_name","").strip(),
            business_name=f.get("business_name","").strip(),
            email=f.get("email","").strip(),
            phone=f.get("phone","").strip(),
            location=f.get("location","").strip(),
            product_type=f.get("product_type"),
            weekly_capacity=f.get("weekly_capacity","").strip(),
            packaging=f.get("packaging","").strip(),
            certification_file=request.FILES.get("certification_file"),
            delivery=f.get("delivery"),
            message=f.get("message","").strip(),
        )
        messages.success(request, "Thanks! Your application has been submitted. We’ll respond within 2–3 business days.")
        return redirect("become_supplier")

    return render(request, "home/become_supplier.html")

def _get_session_cart(request):
    """
    Session cart structure:
    {
      "lines": [
        {
          "id": "L0001",
          "product_id": 123,
          "variant_id": 456 or None,
          "name": "Chicken",
          "sku": "CHK001",
          "uom": "Each",
          "pack_label": "1.5 kilogram",
          "qty": 2,
          "unit_price_excl": "48.75",     # stored as string
          "image_url": "/media/....jpg",
          "vat_percent": "15.00",         # optional
          "is_zero_rated": false          # optional
        },
        ...
      ]
    }
    """
    cart = request.session.get("cart")
    if not cart:
        cart = {"lines": []}
        request.session["cart"] = cart
        request.session.modified = True
    return cart

def _money(x):
    return Decimal(str(x or "0"))

def _q2(x):
    return (Decimal(str(x)) if x is not None else D0).quantize(Decimal("0.01"))

def _next_line_id(cart):
    return f"L{len(cart['lines']) + 1:04d}"

def _pick_price_ex(product, variant, channel: str) -> Decimal:
    """
    Decide EX VAT unit price for line:
      1) variant.price_for_channel(channel) if available
      2) product.price_for_channel(channel)
      3) quick price field on product (retail/wholesale)
      4) first active supplier row (retail/wholesale ladder)
    """
    price_ex = None

    # 1) Variant method
    if variant and hasattr(variant, "price_for_channel"):
        try:
            price_ex = variant.price_for_channel(channel)
        except Exception:
            price_ex = None

    # 2) Product method
    if (price_ex is None or _money(price_ex) == D0) and hasattr(product, "price_for_channel"):
        try:
            price_ex = product.price_for_channel(channel)
        except Exception:
            price_ex = None

    # 3) Quick price fields
    if price_ex is None or _money(price_ex) == D0:
        if channel == "retail":
            price_ex = product.retail_price
        else:
            price_ex = product.wholesale_price

    # 4) Supplier fallback
    if price_ex is None or _money(price_ex) == D0:
        try:
            row = product.pricing_rows.filter(is_active=True).first()
        except Exception:
            row = None
        if row:
            price_ex = row.retail_price_excl if channel == "retail" else row.wholesale_price_excl

    return _q2(price_ex or D0)

def _calc_cart_totals(cart_dict):
    """
    Mutates and returns cart_dict with:
      - line_total_excl
      - subtotal_excl
      - vat_total
      - total_incl
    Respects per-line vat_percent and is_zero_rated flags when present.
    """
    subtotal = D0
    vat_total = D0

    for line in cart_dict.get("lines", []):
        qty = _q2(line.get("qty", 0))
        unit = _q2(line.get("unit_price_excl", 0))
        line_total = _q2(qty * unit)
        line["line_total_excl"] = line_total
        subtotal += line_total

        # VAT
        is_zero = bool(line.get("is_zero_rated", False))
        vat_pct = _q2(line.get("vat_percent", VAT_DEFAULT))
        if is_zero:
            vat_pct = D0
        vat_total += _q2(line_total * (vat_pct / Decimal("100")))

    cart_dict["subtotal_excl"] = _q2(subtotal)
    cart_dict["vat_total"] = _q2(vat_total)
    cart_dict["total_incl"] = _q2(subtotal + vat_total)
    return cart_dict

@login_required
@require_http_methods(["GET", "POST"])
def cart(request):
    cart = _get_session_cart(request)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()

        # -------- ADD (from product or variant forms) --------
        if "product_id" in request.POST or "variant_id" in request.POST:
            channel = (request.POST.get("channel") or "retail").lower()
            qty = max(1, int(request.POST.get("qty", "1") or 1))

            product = None
            variant = None
            if request.POST.get("variant_id") and ProductVariant:
                variant = get_object_or_404(ProductVariant, pk=request.POST["variant_id"])
                product = variant.product
            else:
                product = get_object_or_404(Product, pk=request.POST["product_id"])

            unit_price_excl = _pick_price_ex(product, variant, channel)

            # Display bits
            name = product.name
            sku = getattr(product, "sku", "") or ""
            uom_display = product.get_uom_display() if hasattr(product, "get_uom_display") else ""

            # Variant label + discrete fields for template
            pack_label = ""
            variant_uom = ""
            variant_pack_size = None
            if variant:
                if hasattr(variant, "get_uom_display"):
                    variant_uom = variant.get_uom_display()
                elif hasattr(variant, "uom") and variant.uom:
                    variant_uom = str(variant.uom)

                if hasattr(variant, "pack_size") and variant.pack_size is not None:
                    variant_pack_size = variant.pack_size

                # For the quick one-line label
                if variant_pack_size is not None:
                    if variant_uom:
                        pack_label = f"{variant_pack_size:g} {variant_uom.lower()}"
                    elif uom_display:
                        pack_label = f"{variant_pack_size:g} {uom_display.lower()}"

            # Image preference: variant > product
            image_url = ""
            if variant and getattr(variant, "image", None):
                try:
                    image_url = variant.image.url
                except Exception:
                    image_url = ""
            if not image_url and getattr(product, "image", None):
                try:
                    image_url = product.image.url
                except Exception:
                    image_url = ""

            # Merge line if same product/variant/channel price
            merged = False
            for ln in cart["lines"]:
                if (
                    ln["product_id"] == product.id
                    and ln["variant_id"] == (variant.id if variant else None)
                    and _money(ln["unit_price_excl"]) == unit_price_excl
                ):
                    ln["qty"] = int(ln["qty"]) + qty
                    merged = True
                    break

            if not merged:
                cart["lines"].append(
                    {
                        "id": _next_line_id(cart),
                        "product_id": product.id,
                        "variant_id": variant.id if variant else None,
                        "name": name,
                        "sku": sku,
                        # for template "product.uom_label"
                        "uom": uom_display or "",
                        # for template "variant.uom / variant.uom_label / variant.pack_size"
                        "variant_uom": variant_uom or "",
                        "variant_pack_size": str(variant_pack_size) if variant_pack_size is not None else "",
                        # quick pretty label used elsewhere
                        "pack_label": pack_label,
                        "qty": qty,
                        "unit_price_excl": str(unit_price_excl),
                        "image_url": image_url,
                        # VAT info (defaults)
                        "vat_percent": str(VAT_DEFAULT),
                        "is_zero_rated": False,
                    }
                )

            request.session["cart"] = cart
            request.session.modified = True
            messages.success(request, f"Added {qty} × {name} to your cart.")
            return redirect("cart")

        # -------- UPDATE QTY --------
        if action == "update":
            line_id = request.POST.get("line_id")
            qty = max(1, int(request.POST.get("qty", "1") or 1))
            for ln in cart["lines"]:
                if ln["id"] == line_id:
                    ln["qty"] = qty
                    break
            request.session.modified = True
            return redirect("cart")

        # -------- REMOVE LINE --------
        if action == "remove":
            line_id = request.POST.get("line_id")
            cart["lines"] = [ln for ln in cart["lines"] if ln["id"] != line_id]
            request.session.modified = True
            return redirect("cart")

        # -------- BULK UPDATE (reserved) --------
        if action == "bulk_update":
            request.session.modified = True
            return redirect("cart")

    # ---------- GET: build rich lines for template ----------
    # ---------- GET: build rich lines for template ----------
    rich_lines = []
    for ln in cart["lines"]:
        unit = _q2(ln.get("unit_price_excl"))
        qty = int(ln.get("qty", 1))
        line_total = _q2(unit * qty)

        # Tiny proxies so template can safely access attributes
        ProductProxy = type("ProductProxy", (), {})
        VariantProxy = type("VariantProxy", (), {})
        ImgProxy = type("ImgProxy", (), {})

        # ---- product proxy (ALWAYS give uom & uom_label) ----
        p = ProductProxy()
        p.name = ln.get("name") or "Item"
        p.sku = ln.get("sku") or ""
        # ensure both attributes exist so template never raises VariableDoesNotExist
        p.uom = ln.get("uom") or ""          # e.g. "Each", "Kilogram"
        p.uom_label = ln.get("uom") or ""    # same value; template may read either

        # ---- variant proxy (if present) ----
        v = None
        if ln.get("variant_id"):
            v = VariantProxy()
            # ensure these attributes always exist
            v.uom = ln.get("variant_uom") or ""
            v.uom_label = ln.get("variant_uom") or ""
            # keep numeric (string ok for display; template uses floatformat)
            v.pack_size = ln.get("variant_pack_size") or ""
            v.pack_label = ln.get("pack_label") or ""

        # ---- image proxy (if present) ----
        img = None
        if ln.get("image_url"):
            img = ImgProxy()
            img.url = ln["image_url"]

        rich_lines.append(
            {
                "id": ln["id"],
                "qty": qty,
                "unit_price_excl": unit,
                "line_total_excl": line_total,
                "product": p,
                "variant": v,
                "image": img,
            }
        )

    totals = _calc_cart_totals({"lines": rich_lines})

    context = {
        "cart": {
            "lines": rich_lines,
            "subtotal_excl": totals["subtotal_excl"],
            "vat_total": totals["vat_total"],
            "total_incl": totals["total_incl"],
            "subtotal": totals["subtotal_excl"],  # alias so template fallbacks never break
        }
    }
    return render(request, "home/cart.html", context)


def _get_client_for_user(user):
    from clients.models import Client
    # Prefer CustomerProfile link (BUSINESS)
    try:
        prof = getattr(user, "customer_profile", None)
        if prof and prof.profile_type == "BUSINESS" and prof.client:
            return prof.client
    except Exception:
        pass

    # Fallbacks you had before
    try:
        return Client.objects.get(user=user)
    except Exception:
        pass
    try:
        return Client.objects.filter(email__iexact=getattr(user, "email", "")).first()
    except Exception:
        return None

def _get_client_for_user(user):
    """
    Prefer CustomerProfile's linked Client when profile_type == BUSINESS.
    Fallback to a Client linked to user/email if present. Return None if not found.
    """
    # 1) From CustomerProfile (Business)
    try:
        prof = getattr(user, "customer_profile", None)
        if prof and prof.profile_type == "BUSINESS" and prof.client:
            return prof.client
    except Exception:
        pass

    # 2) Direct user link (if you use this pattern)
    try:
        return Client.objects.get(user=user)
    except Exception:
        pass

    # 3) Email match (optional)
    try:
        return Client.objects.filter(email__iexact=getattr(user, "email", "")).first()
    except Exception:
        return None


@login_required
def checkout(request):
    """
    Turn the session cart into a real Order + OrderItems, then auto-approve and redirect.
    GET  -> simple confirmation (or skip straight to POST if you prefer).
    POST -> create order from session cart and redirect to view-order.
    """
    # 1) Read session cart (uses your existing helper)
    scart = _get_session_cart(request)
    _calc_cart_totals(scart)  # ensure totals up to date

    # Guard: empty cart
    if not scart.get("lines"):
        messages.info(request, "Your cart is empty.")
        return redirect("cart")

    # 2) Resolve client from the user's customer profile
    #    - Business profiles must have a linked Client
    #    - Personal profiles can also link to a Client or you can choose to create one
    profile = getattr(request.user, "customer_profile", None)
    client: Client | None = None
    if profile and profile.profile_type == "BUSINESS" and profile.client_id:
        client = profile.client
    elif profile and profile.profile_type == "PERSONAL" and profile.client_id:
        client = profile.client

    if client is None:
        messages.error(
            request,
            "Please complete your profile and link a client before checking out."
        )
        return redirect("profile")  # change to your profile route name

    if request.method == "GET":
        # Optional confirmation page – shows a summary using the cart template snippet
        return render(request, "home/checkout_confirm.html", {
            "cart": {
                "lines": scart["lines"],
                "subtotal_excl": scart.get("subtotal_excl"),
                "vat_total": scart.get("vat_total"),
                "total_incl": scart.get("total_incl"),
            },
            "client": client,
        })

    # 3) POST: create Order + OrderItems inside a single transaction
    with transaction.atomic():
        order = Order.objects.create(
            client=client,
            created_by=request.user,
            channel="WEB",
            status="pending",     # will be flipped to approved below
            customer_notes=request.POST.get("customer_notes", "").strip(),
        )

        # Build items from session cart lines
        items_to_create: list[OrderItem] = []
        for ln in scart.get("lines", []):
            try:
                product = Product.objects.select_related("category").get(pk=ln["product_id"])
            except Product.DoesNotExist:
                # skip bad/missing products gracefully
                continue

            qty = Decimal(str(ln.get("qty", 1)))
            unit = Decimal(str(ln.get("unit_price_excl", "0")))

            items_to_create.append(
                OrderItem(
                    order=order,
                    category=product.category,
                    product=product,
                    sku=ln.get("sku", "") or (product.sku or ""),
                    product_name=ln.get("name", "") or product.name,
                    uom=ln.get("uom", "") or product.uom,  # snapshot
                    quantity=qty,
                    unit_price_excl=unit,
                    # discount_excl defaults to 0.00; vat_percent defaults to 0.00
                )
            )

        if items_to_create:
            OrderItem.objects.bulk_create(items_to_create)
        else:
            # No valid lines -> abort
            order.delete()
            messages.error(request, "We couldn’t create your order because no valid items were found.")
            return redirect("cart")

        # Compute order totals/snapshots
        order.recalc_totals(save=True)

        # 4) Auto-approve (this will also ensure invoice + delivery artifacts)
        try:
            order.mark_approved(request.user)
        except Exception:
            # defensive fallback; normally not needed
            from django.utils.timezone import now
            order.status = "approved"
            order.approved_by = request.user
            order.approved_at = now()
            order.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    # 5) Clear the cart and redirect to the order view
    request.session["cart"] = {"lines": []}
    request.session.modified = True

    messages.success(request, f"Order #{order.id} has been placed and approved.")
    return redirect("view-order", pk=order.id)



@login_required
def view_order(request, order_id: int):
    """
    Minimal order detail page so the redirect has somewhere to land.
    """
    order = get_object_or_404(
        Order.objects.select_related("client").prefetch_related("items__product", "items__category"),
        pk=order_id
    )
    return render(request, "home/view_order.html", {"order": order})


def payfast_return(request):
    return HttpResponse("Thanks! We'll email you a receipt shortly.")

def payfast_cancel(request):
    return HttpResponse("Payment cancelled.")

@csrf_exempt  # PayFast posts from their servers
def payfast_ipn(request):
    # TODO: verify signature, amount, source IP, etc., then mark invoice paid.
    return HttpResponse("OK")

def _redirect_after_register(request: HttpRequest) -> str:
    """
    Decide where to send the user after successful registration.
    Prefers a 'next' param (GET/POST). Falls back to 'home'.
    """
    nxt = request.GET.get("next") or request.POST.get("next")
    if nxt:
        return nxt
    return reverse("home")


def register_profile(request: HttpRequest) -> HttpResponse:
    """
    Minimal registration flow:
    1) Create User (email = username)
    2) Create Client (minimal fields only, status=ACTIVE)
    3) Create Business CustomerProfile linked to User + Client
       (display_name enforced as client.name at model level)

    After success:
    - Auto-login user
    - Send welcome email
    - Redirect to success page
    """

    def _blank_ctx():
        return {
            "user_form": RegisterUserForm(prefix="user"),
            "client_form": ClientMinimalForm(prefix="client"),
        }

    # ---------- GET ----------
    if request.method != "POST":
        return render(request, "home/register_profile.html", _blank_ctx())

    # ---------- POST ----------
    user_form = RegisterUserForm(request.POST, prefix="user")
    client_form = ClientMinimalForm(request.POST, prefix="client")

    # Username comes from email
    if "username" in user_form.fields:
        user_form.fields["username"].required = False

    user_ok = user_form.is_valid()
    client_ok = client_form.is_valid()

    # Pull candidate email safely
    candidate_email = (
        (user_form.cleaned_data.get("email") if user_ok else None)
        or request.POST.get(f"{user_form.prefix}-email", "")
        or ""
    ).strip()

    # Case-insensitive duplicate check
    if candidate_email:
        exists = (
            User.objects.filter(username__iexact=candidate_email).exists()
            or User.objects.filter(email__iexact=candidate_email).exists()
        )
        if exists:
            user_form.add_error(
                "email",
                "An account with this email already exists. Please use another email.",
            )
            user_ok = False
    else:
        user_form.add_error("email", "Please enter a valid email address.")
        user_ok = False

    # Early exit if forms invalid
    if not (user_ok and client_ok):
        messages.error(request, "Please fix the highlighted fields and try again.")
        return render(
            request,
            "home/register_profile.html",
            {
                "user_form": user_form,
                "client_form": client_form,
            },
        )

    created_bundle: Optional[Tuple[User, Client, CustomerProfile]] = None

    # ---------- ATOMIC CREATION ----------
    with transaction.atomic():
        # ---- 1) USER ----
        user = user_form.save(commit=False)
        user.username = candidate_email.lower()
        user.email = candidate_email
        user.save()

        # ---- 2) CLIENT (MINIMAL) ----
        client = client_form.save(commit=False)
        client.status = "ACTIVE"
        client.account_manager = None
        client.save()

        # ---- 3) CUSTOMER PROFILE (BUSINESS) ----
        profile = CustomerProfile(
            user=user,
            client=client,
            profile_type="BUSINESS",
            status="active",
        )
        profile.save()

        created_bundle = (user, client, profile)

    # ---------- POST-SUCCESS ----------
    user, client, profile = created_bundle  # type: ignore[misc]

    # Auto-login user
    login(request, user)

    # Welcome email (best-effort)
    try:
        if user.email:
            send_success_registration_email(user, client, profile)
    except Exception:
        pass

    # Redirect to success page
    return redirect("register-success")

def send_success_registration_email(user, client, profile):
    """
    Sends a branded HTML + text email to the newly registered user.
    All wording is in templates:
      - email/successful_registration.txt
      - email/successful_registration.html
    """
    # Context only (no wording here)
    ctx = {
        "user": user,
        "client": client,
        "profile": profile,
        "login_url": reverse("client-login"),  # relative URL; switch to absolute if you prefer
    }

    subject = "The Daily Market – Thanks, your account is under review"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "accounts@thedailymarket.co.za")
    to = [user.email or user.username]

    # Render templates
    text_body = render_to_string("email/successful_registration.txt", ctx)
    html_body = render_to_string("email/successful_registration.html", ctx)

    # Send
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=to,
        headers={"Reply-To": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za")},
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=True)


@login_required
def register_success(request):
    profile = request.user.customer_profile
    client_name = profile.client.name if profile.client else ""

    return render(
        request,
        "home/register_success.html",
        {
            "client_name": client_name,
        }
    )

def create_support_task_for_new_registration(request, client, profile, user):
    # Safe URL building
    try:
        client_url = request.build_absolute_uri(reverse("client-view", args=[client.id]))
    except Exception:
        client_url = ""
    try:
        profile_url = request.build_absolute_uri(reverse("customer_profile"))
    except Exception:
        profile_url = ""

    title = f"New registration: {getattr(client, 'name', 'Client')} ({user.email or user.username})"

    # Plain text description used for Task (keeps admin list clean)
    body_lines = [
        "A new customer registration has been completed.",
        "",
        f"Client: {getattr(client, 'name', '')}",
        f"User:   {user.get_full_name() or user.username}",
        f"Email:  {user.email or user.username}",
    ]
    if client_url:
        body_lines.append(f"Client page:  {client_url}")
    if profile_url:
        body_lines.append(f"Profile page: {profile_url}")
    body_lines.append("")
    body_lines.append("Please review and activate as needed.")
    body_text_for_task = "\n".join(body_lines)

    # Create Task now (synchronous)
    try:
        Task.objects.create(
            title=title,
            description=body_text_for_task,
            status=Task.Status.OPEN,
            priority=Task.Priority.MEDIUM,
            department=Task.Department.SUPPORT,
            created_by=None,
            assigned_to=None,
            due_at=timezone.now() + timedelta(days=2),
            content_type=ContentType.objects.get_for_model(client),
            object_id=client.id,
        )
    except Exception as e:
        print("!!! Failed to create Task:", repr(e))

    # ---- Notify Support using HTML + text templates ----
    try:
        ctx = {
            "title": title,
            "client": client,
            "user": user,
            "profile": profile,
            "client_url": client_url,
            "profile_url": profile_url,
        }
        subject = f"[Seshibo] {title}"
        support_to = getattr(settings, "SUPPORT_EMAIL", "support@seshibodailymarket.co.za")
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "accounts@seshibodailymarket.co.za")

        # templates you’ll create in:
        #   home/templates/email/support_new_registration.txt
        #   home/templates/email/support_new_registration.html
        text_body = render_to_string("email/support_new_registration.txt", ctx)
        html_body = render_to_string("email/support_new_registration.html", ctx)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[support_to],
            headers={"Reply-To": support_to},
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=True)
    except Exception as e:
        print("!!! Failed to email Support about Task:", repr(e))



def _generate_4digit_otp() -> str:
    return f"{random.randint(0, 9999):04d}"

def _find_user_for_reset(identifier: str):
    """
    Accept an email-like identifier. We try:
    - username == identifier (case-insensitive)  [client flow where username is email]
    - email == identifier (case-insensitive)     [staff or client]
    Returns User or None.
    """
    ident = (identifier or "").strip()
    if not ident:
        return None
    return User.objects.filter(
        Q(username__iexact=ident) | Q(email__iexact=ident)
    ).first()

def _issue_pwreset_token(user_id: int) -> str:
    """
    Return a signed token that embeds the user id.
    We validate max_age on verify/complete.
    """
    payload = {"uid": user_id, "ts": timezone.now().timestamp()}
    return signing.dumps(payload, salt=PWRESET_SALT)

def _read_pwreset_token(token: str, max_age: int = PWRESET_VERIFIED_TTL_SECONDS):
    """
    Verify signature and max_age. Returns payload dict or raises.
    """
    return signing.loads(token, salt=PWRESET_SALT, max_age=max_age)

def _otp_cache_key(user_id: int) -> str:
    return f"pwreset:otp:{user_id}"

def _verified_cache_key(user_id: int) -> str:
    return f"pwreset:ok:{user_id}"

def _send_reset_otp_email(user: User, code: str):
    """
    Minimal email helper. Adjust subject/from_email/message to your brand.
    """
    subject = "Your Seshibo Daily Market password reset code"
    message = (
        f"Hi {user.get_full_name() or user.username},\n\n"
        f"Your one-time password (OTP) is: {code}\n"
        f"It expires in {PWRESET_OTP_TTL_SECONDS} seconds.\n\n"
        f"If you did not request this, you can ignore this email."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@seshibodailymarket.co.za")
    recipient_list = [user.email or user.username]
    # If no valid email, silently skip to avoid errors:
    if recipient_list and recipient_list[0]:
        send_mail(subject, message, from_email, recipient_list, fail_silently=True)

# ---------- Page view that hosts the 3-step modal flow ----------
class OtpResetPageView(View):
    template_name = "home/password_reset_otp.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        # Optional prefill via ?email=
        ctx = {
            "prefill_email": request.GET.get("email", "").strip(),
            # Provide a CSRF token for any JS fetch if you choose that approach
            "csrftoken": get_token(request),
        }
        return render(request, self.template_name, ctx)

# ---------- API: Step 1 -> Start (send OTP) ----------
@require_POST
def pwreset_start(request: HttpRequest) -> JsonResponse:
    """
    Input: email
    Output: { ok, message, token? }
    - If user exists: issue OTP (cache) and signed token (response)
    - If not: return ok with generic message (no token)
    """
    email = (request.POST.get("email") or "").strip()
    if not email:
        return JsonResponse({"ok": False, "message": "Please enter your registered email address."}, status=400)

    user = _find_user_for_reset(email)
    # Always reply generically to avoid user enumeration
    if not user:
        return JsonResponse({
            "ok": True,
            "message": "If that email is registered, an OTP has been sent. Please check your inbox."
        })

    # Rate limit basic: if an OTP already exists and hasn't expired, don't re-issue
    k = _otp_cache_key(user.id)
    existing = cache.get(k)
    if existing:
        # Don’t spam users; tell front-end to proceed to OTP step (token still needed)
        token = _issue_pwreset_token(user.id)
        return JsonResponse({
            "ok": True,
            "message": "If that email is registered, an OTP has already been sent recently.",
            "token": token
        })

    # Generate & store OTP (expires in 120s)
    code = _generate_4digit_otp()
    cache.set(k, code, timeout=PWRESET_OTP_TTL_SECONDS)

    # Email the user
    _send_reset_otp_email(user, code)

    # Return signed token to carry UID forward
    token = _issue_pwreset_token(user.id)

    return JsonResponse({
        "ok": True,
        "message": "If that email is registered, an OTP has been sent. Please check your inbox.",
        "token": token
    })

# ---------- API: Step 2 -> Verify OTP ----------
@require_POST
def pwreset_verify(request: HttpRequest) -> JsonResponse:
    """
    Input: token, code
    Output: { ok, message }
    Validates token (signed, age <= 10min) and OTP (== cached value & not expired).
    On success, mark verified in cache for a short window to complete reset.
    """
    token = (request.POST.get("token") or "").strip()
    code = (request.POST.get("code") or "").strip()

    if not token or not code:
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)

    try:
        payload = _read_pwreset_token(token, max_age=PWRESET_VERIFIED_TTL_SECONDS)
        uid = int(payload.get("uid"))
    except Exception:
        return JsonResponse({"ok": False, "message": "Your session expired. Please restart the reset process."}, status=400)

    otp_key = _otp_cache_key(uid)
    expected = cache.get(otp_key)
    if not expected:
        return JsonResponse({"ok": False, "message": "OTP expired. Please request a new code."}, status=400)

    if code != expected:
        return JsonResponse({"ok": False, "message": "Incorrect code. Please try again."}, status=400)

    # Mark verified and remove the OTP
    cache.delete(otp_key)
    cache.set(_verified_cache_key(uid), True, timeout=PWRESET_VERIFIED_TTL_SECONDS)

    return JsonResponse({"ok": True, "message": "OTP verified. You can now set a new password."})

def _login_redirect_for_user(user) -> str:
    """
    Decide where to send the user after resetting their password.
    - If they have a StaffProfile -> staff login
    - Else if they have a CustomerProfile -> client login
    - Else -> default to client login
    """
    # Prefer attribute access via related_name (safer & cheaper than imports here).
    # Your CustomerProfile uses related_name="customer_profile".
    # Assuming StaffProfile uses related_name="staff_profile" (adjust if different).
    if hasattr(user, "staff_profile") and getattr(user, "staff_profile") is not None:
        try:
            return reverse("staff-login")
        except Exception:
            pass  # fallback below

    if hasattr(user, "customer_profile") and getattr(user, "customer_profile") is not None:
        try:
            return reverse("client-login")
        except Exception:
            pass

    # Fallback if no profiles found or URL names differ
    try:
        return reverse("client-login")
    except Exception:
        return "/"  # final safety

@require_POST
def pwreset_complete(request: HttpRequest) -> JsonResponse:
    """
    Input: token, password1, password2
    Output: { ok, message, redirect? }
    Requires that the token is valid and verification flag is set in cache.
    """
    token = (request.POST.get("token") or "").strip()
    p1 = (request.POST.get("password1") or "").strip()
    p2 = (request.POST.get("password2") or "").strip()

    if not token or not p1 or not p2:
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)

    if p1 != p2:
        return JsonResponse({"ok": False, "message": "Passwords do not match."}, status=400)

    if len(p1) < 8:
        return JsonResponse({"ok": False, "message": "Password must be at least 8 characters."}, status=400)

    try:
        payload = _read_pwreset_token(token, max_age=PWRESET_VERIFIED_TTL_SECONDS)
        uid = int(payload.get("uid"))
    except Exception:
        return JsonResponse({"ok": False, "message": "Your session expired. Please restart the reset process."}, status=400)

    # Must be verified
    if not cache.get(_verified_cache_key(uid)):
        return JsonResponse({"ok": False, "message": "OTP not verified or session expired."}, status=400)

    user = User.objects.filter(id=uid).first()
    if not user:
        return JsonResponse({"ok": False, "message": "Account not found."}, status=400)

    # Set new password
    user.set_password(p1)
    user.save()

    # Clean up verification marker
    cache.delete(_verified_cache_key(uid))

    # Decide where to send them next
    redirect_url = _login_redirect_for_user(user)

    return JsonResponse({
        "ok": True,
        "message": "Password updated successfully. Redirecting to sign in…",
        "redirect": redirect_url
    })