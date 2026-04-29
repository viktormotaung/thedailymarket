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
import json
from seshibo_site.core.access import get_user_portal_access
from decimal import Decimal, InvalidOperation
from typing import Iterable
import requests
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
from profiles.models import CustomerProfile, StaffProfile, SalesRepProfile, DriverProfile  
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery, F
from django.db.models.functions import Coalesce
from django.shortcuts import render
from typing import Optional, Tuple
from clients.forms import ClientMinimalForm
from datetime import date, timedelta
from payments.ozow import generate_ozow_hash
from .forms import UserProfileForm
import hashlib
import urllib.parse
from invoices.models import Invoice
from credit.models import CreditAccount, CreditEntry
from invoices.models import Invoice, PaymentLog
from orders.models import Order
from credit.models import FunderMember 
from clients.models import Client
from django.db.models import OuterRef, Subquery, Value, DateTimeField
import random
from tasks.models import Ticket
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import render, redirect
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
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

from decimal import Decimal

VAT = Decimal("0.15")  # 15%

def with_vat(price_excl: Decimal) -> Decimal:
    return _r2(price_excl * (1 + VAT))


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

    # Get client's CreditAccount
    ca, _ = CreditAccount.objects.get_or_create(client=client)

    # Total outstanding (ACCOUNT-LEVEL)
    total_outstanding = ca.credit_used or Decimal("0.00")
    print("Total outstanding (CreditAccount.credit_used):", total_outstanding)

    # Credit snapshot: only invoices funded by TA
    ta_invoices = Invoice.objects.filter(
        client=client,
        credit_used__gt=Decimal("0.00"),
        due_date__isnull=False
    )

    # ---- Next Due: earliest due invoice ----
    next_due_obj = ta_invoices.filter(due_date__gte=today).order_by("due_date", "id").first()

    next_due = None
    if next_due_obj and total_outstanding > 0:
        next_due = type("NextDue", (), {
            "invoice_id": next_due_obj.id,                # anchor invoice
            "due_date":   next_due_obj.due_date + timedelta(days=1),
            "outstanding": total_outstanding,             # 🔑 ACCOUNT balance
        })()

    # ---- Overdue: flag only (amount still account-level) ----
    overdue_invoices = ta_invoices.filter(due_date__lt=today)
    overdue = overdue_invoices.exists()

    overdue_list = []
    for inv in overdue_invoices:
        overdue_list.append({
            "invoice_id": inv.id,
            "due_date": inv.due_date + timedelta(days=1),
            "days_overdue": (today - inv.due_date).days,
        })


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
        "outstanding": total_outstanding,  # <-- use total_outstanding here


        # Movements,
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
      - Logistics portal

    After successful login, always show a modal:
      "Your profile has access to the following portal/s, please choose one"
    Buttons are enabled/disabled based on access.
    """

    # -------------------------------------------------
    # GET
    # -------------------------------------------------
    if request.method == "GET":
        return render(request, "home/staff_login.html", {
            "prefill_username": request.GET.get("username", "").strip(),
        })

    # -------------------------------------------------
    # POST
    # -------------------------------------------------
    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""

    ctx = {"prefill_username": username}

    # -------------------------------------------------
    # 1) User existence (case-insensitive)
    # -------------------------------------------------
    user = User.objects.filter(username__iexact=username).first()
    if not user:
        ctx.update({
            "show_modal": True,
            "modal_title": "We couldn't find an account",
            "modal_message": "No user exists with that username. Please check and try again.",
        })
        return render(request, "home/staff_login.html", ctx)

    # -------------------------------------------------
    # 2) Credentials
    # -------------------------------------------------
    authed = authenticate(request, username=user.username, password=password)
    if not authed:
        ctx.update({
            "show_modal": True,
            "modal_title": "Invalid username or password",
            "modal_message": "Please try again. If you’ve forgotten your password, use the Reset link below.",
        })
        return render(request, "home/staff_login.html", ctx)

    # -------------------------------------------------
    # 3) Detect roles / profiles
    # -------------------------------------------------

    # --- Lender ---
    has_active_funder_membership = FunderMember.objects.filter(
        user=authed,
        is_active=True
    ).exists()

    # --- Staff ---
    is_staff_user = authed.is_staff

    # --- Sales ---
    has_active_sales_rep = SalesRepProfile.objects.filter(
        user=authed,
        status="active"
    ).exists()

    # --- Logistics (NEW) ---
    has_active_driver = DriverProfile.objects.filter(
        user=authed,
        status="active"
    ).exists()

    # -------------------------------------------------
    # 4) Hard deny if user has ZERO portal access
    # -------------------------------------------------
    if not any([
        is_staff_user,
        has_active_funder_membership,
        has_active_sales_rep,
        has_active_driver,
    ]):
        ctx.update({
            "show_modal": True,
            "modal_title": "Not authorized",
            "modal_message": (
                "Your account isn’t enabled for staff, lender, sales, or logistics access. "
                "Please contact support@thedailymarket.co.za."
            ),
        })
        return render(request, "home/staff_login.html", ctx)

    # -------------------------------------------------
    # 5) StaffProfile gating (ONLY for staff portal)
    # -------------------------------------------------
    staff_profile = None
    staff_status = None

    if is_staff_user:
        staff_profile = getattr(authed, "staff_profile", None)
        if staff_profile is None:
            ctx.update({
                "show_modal": True,
                "modal_title": "Profile not linked",
                "modal_message": (
                    "Your account does not have a staff profile linked. "
                    "Please contact support@thedailymarket.co.za."
                ),
            })
            return render(request, "home/staff_login.html", ctx)

        staff_status = (getattr(staff_profile, "status", "") or "").upper()
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
                    "modal_message": "Your profile is not active. Please contact support@thedailymarket.co.za.",
                })
            return render(request, "home/staff_login.html", ctx)

    # -------------------------------------------------
    # 6) All good → log the user in
    # -------------------------------------------------
    login(request, authed)

    # -------------------------------------------------
    # 7) Lender session bookkeeping
    # -------------------------------------------------
    if has_active_funder_membership:
        memberships = list(
            FunderMember.objects
            .select_related("funder")
            .filter(user=authed, is_active=True)
            .order_by("funder__name")
        )
        request.session["lender_funders"] = [m.funder_id for m in memberships]

        if len(memberships) == 1:
            request.session["current_funder_id"] = memberships[0].funder_id
        else:
            request.session.pop("current_funder_id", None)
    else:
        request.session.pop("lender_funders", None)
        request.session.pop("current_funder_id", None)

    # -------------------------------------------------
    # 8) Portal access flags (centralised)
    # -------------------------------------------------
    from seshibo_site.core.access import get_user_portal_access

    access = get_user_portal_access(authed)

    # -------------------------------------------------
    # 9) Show portal picker modal
    # -------------------------------------------------
    ctx = {
        "prefill_username": authed.username,
        "show_portal_modal": True,
    }

    # Inject all access flags
    ctx.update(access)

    return render(request, "home/staff_login.html", ctx)


User = get_user_model()


def staff_password_set(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == "POST":
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()

                messages.success(
                    request,
                    "Your password has been set successfully. Please log in."
                )

                # 🔁 Redirect to STAFF LOGIN (not auto-login)
                return redirect("staff-login")
        else:
            form = SetPasswordForm(user)

        return render(
            request,
            "home/staff_password_set.html",
            {
                "form": form,
                "validlink": True,
            },
        )

    # ❌ Invalid / expired link
    return render(
        request,
        "home/staff_password_set.html",
        {
            "validlink": False,
        },
    )



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
                "modal_message": "Your account does not have a customer profile linked. Please contact support@thedailymarket.co.za.",
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
                    "modal_message": "Your profile is not active. Please contact support@thedailymarket.co.za.",
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
    Headline price = WHOLESALE (incl VAT) only.
    Fallback: first active supplier row's wholesale price incl VAT.
    """
    p.display_price_inc = None
    p.display_price_label = None

    # 1) Wholesale price on product
    if p.wholesale_price:
        # Compute incl VAT (assuming 15% VAT)
        VAT_PERCENT = Decimal("15.00")
        p.display_price_inc = (p.wholesale_price * (Decimal("1.00") + VAT_PERCENT / Decimal("100"))).quantize(Decimal("0.01"))
        p.display_price_label = "Wholesale"
        return

    # 2) Fallback to first active supplier row
    rows = getattr(p, "pricing_rows_all_prefetched", None) or p.pricing_rows.all()
    row = next((r for r in rows if getattr(r, "is_active", True)), None)
    if row:
        p.display_price_inc = row.wholesale_price_inc  # already includes VAT
        p.display_price_label = "From supplier"
        return



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
    # Base queryset
    # -------------------------
    qs = (
        Product.objects
        .select_related("category", "category__parent")
        .prefetch_related(
            Prefetch(
                "pricing_rows",
                queryset=ProductPricing.objects.select_related("supplier").order_by("supplier__name"),
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
    # Category / Subcategory filter
    # -------------------------
    if subcategory_id:
        qs = qs.filter(category_id=subcategory_id)
    elif category_id:
        qs = qs.filter(category__parent_id=category_id)

    # -------------------------
    # Pull into list (needed for price logic)
    # -------------------------
    items = list(qs)

    # Attach wholesale incl VAT for each product
    for p in items:
        _attach_display_price(p)

    # -------------------------
    # Price range filtering
    # -------------------------
    if min_price is not None:
        items = [p for p in items if (p.display_price_inc or Decimal("0.00")) >= min_price]

    if max_price is not None:
        items = [p for p in items if (p.display_price_inc or Decimal("0.00")) <= max_price]

    # -------------------------
    # Sorting
    # -------------------------
    if sort in ("name", "-name"):
        items.sort(key=lambda p: (p.name or "").lower(), reverse=sort.startswith("-"))
    elif sort in ("price", "-price"):
        items.sort(key=lambda p: ((p.display_price_inc or Decimal("0.00")), (p.name or "").lower()), reverse=sort.startswith("-"))
    elif sort == "-created":
        items.sort(key=lambda p: (p.created_at or p.id), reverse=True)
    else:
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
    # Preserve filters for pagination
    # -------------------------
    querydict = request.GET.copy()
    querydict.pop("page", None)
    query_string = querydict.urlencode()

    # -------------------------
    # Context
    # -------------------------
    context = {
        "products": page_obj,
        "categories": categories,
        "q": q,
        "selected_category": category_id,
        "selected_subcategory": subcategory_id,
        "sort": sort,
        "min_price": min_price,
        "max_price": max_price,
        "query_string": query_string,
    }

    return render(request, "home/products.html", context)


def _r2(x: Decimal | None) -> Decimal:
    if x is None:
        return Decimal("0.00")
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def product_detail(request, slug):
    # =========================================================
    # PRODUCT
    # =========================================================
    product = get_object_or_404(
        Product.objects
        .select_related("category")
        .prefetch_related(
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.order_by("pack_size", "id")
            ),
        ),
        slug=slug,
    )

    # =========================================================
    # USER / CLIENT CONTEXT
    # =========================================================
    client = None
    customer_profile = None

    if request.user.is_authenticated:
        client = resolve_client_for_user(request.user, request=request)
        customer_profile, _ = CustomerProfile.objects.get_or_create(
            user=request.user,
            defaults={
                "display_name": request.user.get_full_name() or request.user.username,
            }
        )

    # =========================================================
    # CHANNEL
    # =========================================================
    selected_channel = "wholesale"

    # =========================================================
    # BASE PRODUCT PRICES
    # =========================================================
    base_ex = _r2(product.price_for_channel("wholesale"))
    base_inc = _r2(base_ex * (Decimal("1.00") + Decimal("15.00") / Decimal("100")))  # adjust VAT if needed

    # =========================================================
    # VARIANTS
    # =========================================================
    variant_list = []
    for v in product.variants.all():
        # Use the stored price directly (already inclusive of VAT)
        v.display_price_ex = v.wholesale_price or D0
        v.display_price_inc = v.wholesale_price or D0

        variant_list.append(v)

    # =========================================================
    # CONTEXT
    # =========================================================
    context = {
        "product": product,

        # Pricing
        "wholesale_ex": base_ex,
        "wholesale_inc": base_inc,
        "variants": variant_list,
        "typical_pack_sizes": [1.5, 2.5, 5, 10],

        # Channel
        "selected_channel": selected_channel,

        # Client / Profile
        "client": client,
        "customer_profile": customer_profile,
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
    List all orders belonging to the signed-in client's account.
    """

    # Resolve client linked to this user
    client = resolve_client_for_user(request.user, request=request)

    if not client:
        # Safety fallback: user has no client yet
        return render(request, "orders/orders.html", {
            "orders": [],
            "client": None,
        })

    # Optional status filter (?status=pending)
    status_filter = request.GET.get("status")

    orders_qs = (
        Order.objects
        .filter(client=client)
        .select_related("client", "created_by", "approved_by")
        .prefetch_related("items", "items__product")
        .order_by("-submitted_at")
    )

    if status_filter:
        orders_qs = orders_qs.filter(status=status_filter)

    return render(request, "home/orders.html", {
        "orders": orders_qs,
        "client": client,
        "status_filter": status_filter,
    })


def create_support_task_for_new_registration(*, request, client, user):
    """
    Creates a one-time verification task for a newly completed client profile.
    """

    # 🛑 Prevent duplicate tasks
    if Task.objects.filter(
        title__icontains="Verify new client",
        content_type=ContentType.objects.get_for_model(client),
        object_id=client.id,
    ).exists():
        return

    # 🔗 Build client edit URL (DEV / STAGING / LIVE safe)
    client_edit_url = request.build_absolute_uri(
        reverse("client-edit", args=[client.id])
    )

    Task.objects.create(
        title=f"Verify new client: {client.name}",
        description=(
            f"A new client has completed their profile and requires verification.\n\n"
            f"Client: {client.name}\n"
            f"Contact person: {client.contact_person}\n"
            f"Email: {client.email}\n\n"
            f"🔗 Open client profile:\n"
            f"{client_edit_url}\n\n"
            f"Please verify this client within 30–60 minutes."
        ),
        status=Task.Status.PENDING,
        priority=Task.Priority.HIGH,
        department=Task.Department.COMPLIANCE,
        created_by=user,
        due_at=timezone.now() + timedelta(minutes=60),
        content_type=ContentType.objects.get_for_model(client),
        object_id=client.id,
    )

    
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


def about(request):
    return render(request, "home/about.html")


def trade_assist(request):
    return render(request, "home/trade_assist.html")


def grill(request):
    return render(request, "home/grill.html")


def retail(request):
    return render(request, "home/retail.html")


def wholesale(request):
    return render(request, "home/wholesale.html")


def contact(request):
    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip()
        cell = (request.POST.get("cell") or "").strip()
        province = (request.POST.get("province") or "").strip()
        suburb = (request.POST.get("suburb") or "").strip()
        category = (request.POST.get("category") or "").strip().lower()
        subject = (request.POST.get("subject") or "").strip()
        message = (request.POST.get("message") or "").strip()

        if not first_name or not last_name or not email or not cell or not category or not subject or not message:
            messages.error(request, "Please complete all required fields.")
            return render(request, "home/contact.html")

        full_name = f"{first_name} {last_name}".strip()

        # Default mapping
        department = Ticket.Department.SUPPORT
        ticket_type = Ticket.TicketType.GENERAL_ENQUIRY

        # Map website category -> department + ticket type
        if category == "wholesale":
            department = Ticket.Department.SALES
            ticket_type = Ticket.TicketType.SALES_ENQUIRY
        elif category == "retail":
            department = Ticket.Department.SALES
            ticket_type = Ticket.TicketType.SALES_ENQUIRY
        elif category == "grill":
            department = Ticket.Department.SALES
            ticket_type = Ticket.TicketType.SALES_ENQUIRY
        elif category == "general":
            department = Ticket.Department.SUPPORT
            ticket_type = Ticket.TicketType.GENERAL_ENQUIRY

        # Optional client link if authenticated business user
        linked_client = None
        if request.user.is_authenticated:
            customer_profile = getattr(request.user, "customer_profile", None)
            if customer_profile and customer_profile.profile_type == "BUSINESS":
                linked_client = customer_profile.client

        description_parts = [
            f"Website contact form enquiry.",
            f"Category: {category.title()}",
        ]

        if province:
            description_parts.append(f"Province: {province}")
        if suburb:
            description_parts.append(f"Suburb: {suburb}")

        description_parts.append("")
        description_parts.append("Message:")
        description_parts.append(message)

        ticket = Ticket.objects.create(
            title=subject,
            description="\n".join(description_parts),
            status=Ticket.Status.NEW,
            priority=Ticket.Priority.MEDIUM,
            department=department,
            ticket_type=ticket_type,
            source=Ticket.Source.WEBSITE,
            requester_name=full_name,
            requester_email=email,
            requester_phone=cell,
            client=linked_client,
            created_by=request.user if request.user.is_authenticated else None,
        )

        messages.success(
            request,
            f"Thank you, your message has been received. Ticket #{ticket.id} has been created."
        )
        return redirect("contact")

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


def _money(x):
    return Decimal(str(x or "0"))


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _r2(x: Decimal | None) -> Decimal:
    """Round to 2 decimals, treat None as 0"""
    if x is None:
        return D0
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _next_line_id(cart):
    """Generate next line ID like L0001"""
    return f"L{len(cart['lines']) + 1:04d}"


def pick_unit_price_inc(product, variant=None, channel=None):
    print("=== PICK PRICE DEBUG (FINAL) ===")
    print(f"Product: {product.id} | {product.name}")
    print(f"Variant: {getattr(variant, 'id', None)}")

    qs = ProductPricing.objects.filter(
        product=product,
        is_active=True,
    ).order_by("-is_primary", "supplier_price_excl")

    print(f"Pricing rows found: {qs.count()}")

    for p in qs:
        print(
            f"PricingRow → id={p.id}, "
            f"is_primary={p.is_primary}, "
            f"supplier_price_excl={p.supplier_price_excl}"
        )

    # ✅ Primary price first
    row = qs.filter(is_primary=True).first()
    if row and row.supplier_price_excl is not None:
        print(f"✔ Using PRIMARY supplier_price_excl: {row.supplier_price_excl}")
        print("=== END PICK PRICE DEBUG ===")
        return row.supplier_price_excl

    # ✅ Fallback: cheapest/first active
    row = qs.first()
    if row and row.supplier_price_excl is not None:
        print(f"⚠ Using FALLBACK supplier_price_excl: {row.supplier_price_excl}")
        print("=== END PICK PRICE DEBUG ===")
        return row.supplier_price_excl

    # ❌ Hard fail-safe
    print("❌ NO PRICE FOUND → returning 0.00")
    print("=== END PICK PRICE DEBUG ===")
    return Decimal("0.00")

def debug_product_pricing(product):
    print("=== PRODUCT PRICING MODEL DEBUG ===")
    qs = ProductPricing.objects.filter(product=product)

    print(f"Pricing rows found: {qs.count()}")

    for p in qs:
        print("----")
        for field in p._meta.fields:
            name = field.name
            value = getattr(p, name, None)
            print(f"{name}: {value}")

    print("=== END PRODUCT PRICING DEBUG ===")


def _calc_cart_totals(cart):
    """
    Calculates totals for cart.
    Supports:
      - session cart format (dict with product IDs as keys)
      - checkout cart format (dict with "lines": [...])
    Mutates cart with totals.
    """

    subtotal_excl = Decimal("0.00")
    vat_total = Decimal("0.00")
    total_inc = Decimal("0.00")

    # Determine which list of lines to use
    if "lines" in cart:
        # Checkout format
        lines_iter = cart["lines"]
        is_checkout_format = True
    else:
        # Session cart format
        lines_iter = [
            line for line_id, line in cart.items() if not line_id.startswith("_")
        ]
        is_checkout_format = False

    rich_lines = []

    for line in lines_iter:
        qty = Decimal(str(line.get("qty", "0")))
        unit_excl = Decimal(str(line.get("unit_price_excl", "0.00")))
        unit_inc = Decimal(str(line.get("unit_price_inc", "0.00")))

        line_excl = unit_excl * qty
        line_inc = unit_inc * qty
        line_vat = line_inc - line_excl

        subtotal_excl += line_excl
        vat_total += line_vat
        total_inc += line_inc

        rich_line = {
            "product_id": line.get("product_id"),
            "name": line.get("name"),
            "sku": line.get("sku"),
            "qty": qty,
            "unit_price_inc": unit_inc,
            "line_total_inc": line_inc,
        }
        rich_lines.append(rich_line)

    # Update totals
    summary = {
        "subtotal_excl": str(subtotal_excl),
        "vat_total": str(vat_total),
        "total_inc": str(total_inc),
    }

    if is_checkout_format:
        cart["_summary"] = summary
        cart["lines"] = rich_lines  # replace with updated lines
    else:
        cart["_summary"] = summary

    return cart


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



@login_required
@require_http_methods(["GET", "POST"])
def cart(request):

    # ==================================================
    # Resolve client
    # ==================================================
    client = resolve_client_for_user(request.user, request=request)

    credit_account = None
    credit_available = Decimal("0.00")

    if client:
        if (
            getattr(client, "account_type", "") == "CREDIT"
            and getattr(client, "credit_status", "") == "ACTIVE"
        ):
            credit_account = CreditAccount.objects.filter(client=client).first()

            if credit_account:
                credit_available = credit_account.credit_available

    # ==================================================
    # Get session cart or create default
    # ==================================================
    cart = request.session.get("cart")

    if not cart:
        cart = {"lines": []}
        request.session["cart"] = cart

    lines = cart.setdefault("lines", [])

    # ==================================================
    # POST ACTIONS
    # ==================================================
    if request.method == "POST":

        action = request.POST.get("action")

        # -------------------------------
        # REMOVE LINE
        # -------------------------------
        if action == "remove":
            line_id = request.POST.get("line_id")

            cart["lines"] = [
                l for l in lines
                if str(l.get("product_id")) != line_id
            ]

            request.session.modified = True

            print("REMOVE LINE DEBUG → Cart after removal:", cart)

            return redirect("cart")

        # -------------------------------
        # UPDATE QTY
        # -------------------------------
        if action == "update":

            line_id = request.POST.get("line_id")
            qty = max(1, int(request.POST.get("qty", 1)))

            for l in lines:
                if str(l.get("product_id")) == line_id:
                    l["qty"] = qty
                    print("UPDATE LINE DEBUG → Updated line:", l)
                    break

            request.session.modified = True

            return redirect("cart")

        # -------------------------------
        # ADD TO CART
        # -------------------------------
        product_id = int(request.POST.get("product_id"))
        qty = max(1, int(request.POST.get("qty", 1)))

        product = get_object_or_404(Product, pk=product_id)

        pricing = (
            product.pricing_rows
            .filter(is_active=True)
            .order_by("-is_primary")
            .first()
        )

        if not pricing:
            raise ValueError(f"No pricing configured for product {product.id}")

        unit_price_excl = pricing.wholesale_price_excl or Decimal("0.00")
        unit_price_inc = pricing.wholesale_price_inc or Decimal("0.00")

        print("ADD TO CART DEBUG → Product:", product.name)
        print("Qty:", qty)
        print("Unit excl:", unit_price_excl, "Unit inc:", unit_price_inc)
        print("Cart before add:", cart)

        # If product already in cart
        for l in lines:
            if l["product_id"] == product.id:
                l["qty"] += qty
                print("Updated existing line:", l)
                break
        else:

            lines.append({
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku,
                "qty": qty,
                "unit_price_excl": str(unit_price_excl),
                "unit_price_inc": str(unit_price_inc),
            })

            print("Appended new line:", lines[-1])

        request.session.modified = True

        print("Cart after add:", cart)

        return redirect("cart")

    # ==================================================
    # VIEW CART (GET)
    # ==================================================
    rich_lines = []

    subtotal_excl = Decimal("0.00")
    vat_total = Decimal("0.00")
    total_inc = Decimal("0.00")

    for line in lines:

        qty = Decimal(str(line.get("qty", "0")))

        unit_excl = Decimal(str(line.get("unit_price_excl", "0.00")))
        unit_inc = Decimal(str(line.get("unit_price_inc", "0.00")))

        line_excl = unit_excl * qty
        line_inc = unit_inc * qty

        subtotal_excl += line_excl
        vat_total += (line_inc - line_excl)
        total_inc += line_inc

        rich_lines.append({
            "id": line.get("product_id"),
            "name": line.get("name"),
            "sku": line.get("sku"),
            "qty": qty,
            "unit_inc": unit_inc,
            "line_inc": line_inc,
        })

    print("CART GET DEBUG →", rich_lines, subtotal_excl, vat_total, total_inc)

    # ==================================================
    # Render
    # ==================================================
    return render(
        request,
        "home/cart.html",
        {
            "lines": rich_lines,
            "subtotal_excl": subtotal_excl,
            "vat_total": vat_total,
            "total_inc": total_inc,

            # CREDIT INFO
            "credit_account": credit_account,
            "credit_available": credit_available,
        },
    )



VAT_PERCENT = Decimal("15")

def add_vat(price_excl: Decimal, vat_percent: Decimal = VAT_PERCENT) -> Decimal:
    """Return price including VAT."""
    return _r2(price_excl * (1 + vat_percent / 100))

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
def checkout(request):
    """
    Turn the session cart into a real Order + OrderItems, then auto-approve and redirect.

    GET  -> confirmation page
    POST -> create order from session cart and redirect to view-order
    """

    # =========================================================
    # 1) LOAD CART (SESSION SAFE)
    # =========================================================
    scart = _get_session_cart(request)
    _calc_cart_totals(scart)  # MUST only write STRINGS to session

    # Guard: empty cart
    if not scart.get("lines"):
        messages.info(request, "Your cart is empty.")
        return redirect("cart")

    # =========================================================
    # 2) RESOLVE CLIENT
    # =========================================================
    profile = getattr(request.user, "customer_profile", None)
    client: Client | None = None

    if profile and profile.client_id:
        client = profile.client

    if client is None:
        messages.error(
            request,
            "Please complete your profile and link a client before checking out."
        )
        return redirect("profile")

    if client.status != "ACTIVE":
        messages.error(
            request,
            "Your account is not yet verified. Please wait for approval before checkout."
        )
        return redirect("cart")

    # =========================================================
    # 3) GET → CONFIRMATION
    # =========================================================
    if request.method == "GET":
        return render(request, "home/checkout_confirm.html", {
            "cart": {
                "lines": scart.get("lines", []),
                "subtotal_excl": scart.get("subtotal_excl"),
                "vat_total": scart.get("vat_total"),
                "total_incl": scart.get("total_incl"),
            },
            "client": client,
        })

    # =========================================================
    # 4) POST → CREATE ORDER (ATOMIC)
    # =========================================================
    with transaction.atomic():

        order = Order.objects.create(
            client=client,
            created_by=request.user,
            channel="WEB",
            status="pending",
            customer_notes=request.POST.get("customer_notes", "").strip(),
        )

        items_to_create: list[OrderItem] = []

        for ln in scart.get("lines", []):
            try:
                product = Product.objects.select_related("category").get(
                    pk=ln["product_id"]
                )
            except (Product.DoesNotExist, KeyError):
                continue

            # 🔐 Convert SESSION STRINGS → DECIMAL
            qty = Decimal(str(ln.get("qty", "1")))
            unit_price_excl = Decimal(str(ln.get("unit_price_excl", "0.00")))

            if qty <= 0:
                continue

            items_to_create.append(
                OrderItem(
                    order=order,
                    category=product.category,
                    product=product,
                    sku=ln.get("sku") or product.sku or "",
                    product_name=ln.get("name") or product.name,
                    uom=ln.get("uom") or product.uom,
                    quantity=qty,
                    # unit_price_excl intentionally omitted
                )
            )


        if not items_to_create:
            order.delete()
            messages.error(
                request,
                "We couldn’t create your order because no valid items were found."
            )
            return redirect("cart")

        for item in items_to_create:
            item.save()


        # Snapshot totals
        order.recalc_totals(save=True)

        # =====================================================
        # 5) AUTO-APPROVE
        # =====================================================
        try:
            order.mark_approved(request.user)
        except Exception:
            # Defensive fallback
            order.status = "approved"
            order.approved_by = request.user
            order.approved_at = now()
            order.save(update_fields=[
                "status", "approved_by", "approved_at", "updated_at"
            ])

    # =========================================================
    # 6) CLEAR CART (JSON SAFE)
    # =========================================================
    request.session["cart"] = {
        "lines": [],
        "subtotal_excl": "0.00",
        "vat_total": "0.00",
        "total_incl": "0.00",
    }
    request.session.modified = True

    messages.success(
        request,
        f"Order #{order.id} has been placed and approved."
    )

    return redirect("view-order", pk=order.id)

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
def payfast_return(request):
    messages.success(request, "Payment received. Awaiting confirmation.")
    return redirect("orders")


@login_required
def payfast_cancel(request):
    messages.warning(request, "Payment was cancelled.")
    return redirect("orders")

@csrf_exempt  # PayFast posts from their servers
def payfast_ipn(request):
    # TODO: verify signature, amount, source IP, etc., then mark invoice paid.
    return HttpResponse("OK")


@login_required
def view_order(request, pk: int):
    """
    Display a single order belonging to the signed-in client.
    """

    # Resolve the client linked to this user
    client = resolve_client_for_user(request.user, request=request)

    if not client:
        return render(
            request,
            "home/view_order.html",
            {
                "order": None,
                "client": None,
                "invoice": None,
            },
        )

    # Fetch the order securely (must belong to this client)
    order = get_object_or_404(
        Order.objects
        .select_related("client", "created_by", "approved_by")
        .prefetch_related("items", "items__product"),
        pk=pk,
        client=client,
    )

    # --------------------------------------------------
    # Enrich order items with unit_price_inc (derived)
    # --------------------------------------------------
    for item in order.items.all():
        if item.quantity and item.quantity > 0:
            item.unit_price_inc = (
                item.line_total_inc / item.quantity
            ).quantize(Decimal("0.01"))
        else:
            item.unit_price_inc = Decimal("0.00")

    # Fetch invoice (may or may not exist yet)
    invoice = Invoice.objects.filter(order=order).first()

    return render(
        request,
        "home/view_order.html",
        {
            "order": order,
            "client": client,
            "invoice": invoice,
            "items": order.items.all(),  # explicit & consistent
        },
    )

logger = logging.getLogger(__name__)

@csrf_exempt
def payfast_itn(request):
    if request.method != "POST":
        return HttpResponse("Invalid request method", status=405)

    data = request.POST.dict()

    # 1) Verify signature
    signature = data.pop("signature", None)

    def generate_signature(payload, passphrase=None):
        pairs = []
        for key in sorted(payload.keys()):
            value = payload[key]
            if value is None:
                continue
            pairs.append(f"{key}={value}")
        signing_string = "&".join(pairs)

        if passphrase:
            signing_string += f"&passphrase={passphrase}"

        return hashlib.md5(signing_string.encode("utf-8")).hexdigest()

    expected_signature = generate_signature(data, settings.PAYFAST_PASSPHRASE)

    if signature != expected_signature:
        return HttpResponse("Invalid signature", status=400)

    # 2) Only process completed payments
    if data.get("payment_status") != "COMPLETE":
        return HttpResponse("Ignored", status=200)

    # 3) Resolve invoice
    invoice_ref = (data.get("m_payment_id") or "").strip()

    if not invoice_ref.startswith("INV-"):
        return HttpResponse("Invalid invoice reference", status=400)

    invoice_id = invoice_ref.replace("INV-", "", 1)

    try:
        invoice = Invoice.objects.get(pk=invoice_id)
    except Invoice.DoesNotExist:
        return HttpResponse("Invoice not found", status=404)

    # 4) Parse amount safely
    try:
        amount = Decimal(str(data.get("amount_gross", "0.00")))
    except (InvalidOperation, TypeError, ValueError):
        return HttpResponse("Invalid amount", status=400)

    # 5) Prevent duplicate processing if already fully paid
    if invoice.status == "paid":
        return HttpResponse("Already processed", status=200)

    # 6) Trigger the normal invoice payment flow
    invoice.record_payment(
        amount=amount,
        reference=data.get("pf_payment_id", "") or f"PF-{invoice.id}",
        note="PayFast payment received",
    )

    return HttpResponse("OK")



@login_required
def send_invoice_email(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    # Only handle POST
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    email_to = data.get("email")
    recipient_name = data.get("recipient_name", "").strip()

    if not email_to:
        return JsonResponse({"success": False, "error": "No email provided."}, status=400)

    if not recipient_name:
        # fallback to user's full name or username
        profile = invoice.client.customer_profiles.first()
        user = profile.user if profile else None
        if user:
            recipient_name = user.get_full_name() or user.username
        else:
            recipient_name = "Valued Customer"

    # Get customer profile and user
    profile = invoice.client.customer_profiles.first()
    user = profile.user if profile else None
    client = invoice.client

    # Build context
    ctx = {
        "invoice": invoice,
        "user": user,
        "client": client,
        "recipient_name": recipient_name,  # <-- use in template
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
        "invoice_url": request.build_absolute_uri(reverse("view-invoice", args=[invoice.id])),
    }

    # Render templates
    text_body = render_to_string("email/invoice_email.txt", ctx)
    html_body = render_to_string("email/invoice_email.html", ctx)

    # Send email
    subject = f"The Daily Market – Invoice INV-{invoice.id}"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "accounts@thedailymarket.co.za")

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[email_to],
        headers={"Reply-To": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za")},
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

    return JsonResponse({"success": True})



@csrf_exempt
def payfast_itn(request):
    data = request.POST.dict()

    # 1️⃣ Verify signature
    received_signature = data.pop("signature", "")
    calculated_signature = generate_payfast_signature(data)

    if received_signature != calculated_signature:
        return HttpResponse("Invalid signature", status=400)

    # 2️⃣ Validate with PayFast
    response = requests.post(
        settings.PAYFAST_PROCESS_URL.replace("/eng/process", "/eng/query/validate"),
        data=data,
        timeout=10
    )

    if response.text.strip().lower() != "valid":
        return HttpResponse("Invalid PayFast response", status=400)

    # 3️⃣ Process payment
    payment_id = data.get("m_payment_id", "")
    if not payment_id.startswith("INV-"):
        return HttpResponse("Invalid payment reference", status=400)

    invoice_id = int(payment_id.replace("INV-", ""))
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)

    if invoice.amount_due > 0:
        invoice.mark_paid(
            reference=data.get("pf_payment_id"),
            paid_at=now()
        )

    return HttpResponse("OK")

@login_required
def view_invoice(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related("order", "order__client"),
        pk=pk,
        order__client=resolve_client_for_user(request.user, request=request),
    )

    # Prefill email from first active customer profile linked to client
    default_email = ""
    profiles = invoice.order.client.customer_profiles.filter(status="active")
    if profiles.exists():
        default_email = profiles.first().user.email

    return render(request, "home/view_invoice.html", {
        "invoice": invoice,
        "client": invoice.order.client,
        "default_email": default_email,  # pass to template
    })




def register_profile(request: HttpRequest) -> HttpResponse:
    """
    Minimal registration flow:
    1) Create User (email = username)
    2) Create Client (minimal fields only, status=PENDING)

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

    # Case-insensitive duplicate check (UX layer)
    if candidate_email:
        exists = (
            User.objects.filter(username__iexact=candidate_email).exists()
            or User.objects.filter(email__iexact=candidate_email).exists()
        )
        if exists:
            user_form.add_error(
                "email",
                "A user with this email address already exists."
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

        try:
            user.save()
        except IntegrityError:
            # 🔥 DB-level protection (prevents crash)
            user_form.add_error(
                "email",
                "A user with this email address already exists."
            )
            return render(
                request,
                "home/register_profile.html",
                {
                    "user_form": user_form,
                    "client_form": client_form,
                },
            )

        # ---- 2) CLIENT (MINIMAL) ----
        client = client_form.save(commit=False)
        client.status = "PENDING"
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
    msg.send(fail_silently=False)


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


def _redirect_after_register(request: HttpRequest) -> str:
    """
    Decide where to send the user after successful registration.
    Prefers a 'next' param (GET/POST). Falls back to 'home'.
    """
    nxt = request.GET.get("next") or request.POST.get("next")
    if nxt:
        return nxt
    return reverse("home")


@login_required
def profile(request):
    user = request.user

    # =================================================
    # RESOLVE / CREATE CUSTOMER PROFILE (GUARANTEED)
    # =================================================
    customer_profile, _ = CustomerProfile.objects.get_or_create(
        user=user,
        defaults={
            "display_name": user.get_full_name() or user.username,
        }
    )

    # =================================================
    # RESOLVE CLIENT (SINGLE SOURCE OF TRUTH)
    # =================================================
    client = resolve_client_for_user(user, request=request)

    if client is None:
        messages.error(request, "Unable to load business profile.")
        return redirect("home")

    # =================================================
    # HANDLE FORMS
    # =================================================

    # ---- User Profile ----
    user_form = UserProfileForm(
        request.POST or None,
        instance=user
    )

    if request.method == "POST" and request.POST.get("form_type") == "user_profile":
        if user_form.is_valid():
            user_form.save()
            messages.success(request, "User profile updated successfully.")
            return redirect("profile")
        else:
            print(user_form.errors)

    # ---- Business Profile ----
    business_form = ClientBusinessForm(
        request.POST or None,
        instance=client
    )

    if request.method == "POST" and request.POST.get("form_type") == "business_profile":
        if business_form.is_valid():
            business_form.save()
            messages.success(request, "Business profile updated successfully.")
            return redirect("profile")
        else:
            print(business_form.errors)

    # ---- Personal Profile ----
    personal_form = PersonalProfileForm(
        request.POST or None,
        instance=customer_profile
    )

    if request.method == "POST" and request.POST.get("form_type") == "personal_profile":
        if personal_form.is_valid():
            personal_form.save()
            messages.success(request, "Personal profile updated successfully.")
            return redirect("profile")
        else:
            print(personal_form.errors)

    # =================================================
    # PROFILE COMPLETENESS HELPERS
    # =================================================
    def is_filled(value):
        return value is not None and str(value).strip() != ""

    # ================= USER =================
    user_profile_complete = all([
        is_filled(user.first_name),
        is_filled(user.last_name),
        is_filled(user.email),
    ])

    # ================= PERSONAL =================
    personal_profile_complete = all([
        is_filled(customer_profile.display_name),
        is_filled(customer_profile.phone),
    ])

    # ================= BUSINESS =================

    # Contact
    business_contact_complete = all([
        is_filled(client.name),
        is_filled(client.contact_person),
        is_filled(client.email),
        is_filled(client.phone),
    ])

    # Address
    business_address_complete = all([
        is_filled(client.address_line1),
        is_filled(client.suburb),
        is_filled(client.city),
        is_filled(client.province),
        is_filled(client.postal_code),
    ])

    # Delivery (🔥 NEW)
    business_delivery_complete = all([
        is_filled(client.delivery_address_line1),
        is_filled(client.delivery_city),
        is_filled(client.delivery_province),
        is_filled(client.delivery_country),
        is_filled(client.preferred_delivery_slot_1),
    ])

    # Compliance
    business_compliance_complete = all([
        is_filled(client.price_type),
        is_filled(client.estimated_weekly_spend),
        is_filled(client.vat_number) or is_filled(client.registration_identifier),
    ])

    # Overview (🔥 NEW)
    business_overview_complete = all([
        is_filled(client.area),
    ])

    # Full business profile
    business_profile_complete = all([
        business_contact_complete,
        business_address_complete,
        business_delivery_complete,
        business_compliance_complete,
        business_overview_complete,
    ])

    # =================================================
    # PROFILE COMPLETION %
    # =================================================
    completed_sections = [
        user_profile_complete,
        personal_profile_complete,
        business_contact_complete,
        business_address_complete,
        business_delivery_complete,
        business_compliance_complete,
        business_overview_complete,
        business_profile_complete,
    ]

    completed_count = sum(1 for s in completed_sections if s)
    total_sections = len(completed_sections)

    profile_completion_percent = (
        int((completed_count / total_sections) * 100)
        if total_sections else 0
    )

    # =================================================
    # FIRST-TIME COMPLETION ACTION
    # =================================================
    show_profile_complete_popup = False

    if profile_completion_percent == 100:
        if not request.session.get("profile_completion_acknowledged"):
            show_profile_complete_popup = True
            request.session["profile_completion_acknowledged"] = True

            create_support_task_for_new_registration(
                request=request,
                client=client,
                user=user,
            )

    # =================================================
    # RENDER
    # =================================================
    return render(request, "home/profile.html", {
        "user_form": user_form,
        "business_form": business_form,
        "personal_form": personal_form,

        "client": client,
        "customer_profile": customer_profile,

        "user_profile_complete": user_profile_complete,
        "personal_profile_complete": personal_profile_complete,
        "business_profile_complete": business_profile_complete,

        "business_contact_complete": business_contact_complete,
        "business_address_complete": business_address_complete,
        "business_delivery_complete": business_delivery_complete,  # 🔥 NEW
        "business_compliance_complete": business_compliance_complete,
        "business_overview_complete": business_overview_complete,

        "profile_completion_percent": profile_completion_percent,
        "show_profile_complete_popup": show_profile_complete_popup,
    })



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


# views.py
def terms(request):
    return render(request, "legal/terms.html")

def privacy(request):
    return render(request, "legal/privacy.html")

def refund(request):
    return render(request, "legal/refund.html")

def shipping(request):
    return render(request, "legal/shipping.html")


@login_required
def pay_invoice(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)

    if invoice.amount_due <= 0:
        return redirect("view-invoice", pk=invoice.id)

    amount = f"{invoice.amount_due:.2f}"

    transaction_reference = f"INV-{invoice.id}"
    bank_reference = f"INV-{invoice.id}"
    customer_email = request.user.email

    success_url = "https://thedailymarket.co.za/payment/ozow/success/"
    cancel_url = "https://thedailymarket.co.za/payment/ozow/cancel/"
    error_url = "https://thedailymarket.co.za/payment/ozow/error/"
    notify_url = "https://thedailymarket.co.za/payment/ozow/notify/"

    hash_value = generate_ozow_hash(
        settings.OZOW_SITE_CODE,
        settings.OZOW_COUNTRY_CODE,
        settings.OZOW_CURRENCY_CODE,
        amount,
        transaction_reference,
        bank_reference,
        str(invoice.id),   # optional1
        customer_email,
        cancel_url,
        error_url,
        success_url,
        notify_url,
        settings.OZOW_PRIVATE_KEY,
    )

    payload = {
        "siteCode": settings.OZOW_SITE_CODE,
        "countryCode": settings.OZOW_COUNTRY_CODE,
        "currencyCode": settings.OZOW_CURRENCY_CODE,
        "amount": amount,
        "transactionReference": transaction_reference,
        "bankReference": bank_reference,
        "customerEmail": customer_email,
        "successUrl": success_url,
        "cancelUrl": cancel_url,
        "errorUrl": error_url,
        "notifyUrl": notify_url,
        "optional1": str(invoice.id),   # ADD THIS LINE
        "hashCheck": hash_value,
    }

    print("---- OZOW REQUEST ----")
    print("URL:", settings.OZOW_API_URL)
    print("HEADERS:", {
        "Content-Type": "application/json",
        "ApiKey": settings.OZOW_API_KEY
    })
    print("BODY:", json.dumps(payload, indent=2))
    print("----------------------")

    response = requests.post(
        settings.OZOW_API_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "apiKey": settings.OZOW_API_KEY
        },
        timeout=30
    )

    print("OZOW STATUS:", response.status_code)
    print("OZOW RESPONSE:", response.text)

    try:
        data = response.json()
    except Exception:
        data = {}

    PaymentLog.objects.create(
        provider="ozow",
        invoice=invoice,
        transaction_reference=transaction_reference,
        amount=invoice.amount_due,
        raw_request=payload,
        raw_response=data,
        status="initiated",
    )

    if data.get("url"):
        return redirect(data["url"])

    return redirect("view-invoice", pk=invoice.id)

@csrf_exempt
def ozow_notify(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    data = request.POST

    transaction_reference = data.get("TransactionReference")
    amount = Decimal(data.get("Amount", "0"))
    status = data.get("Status")

    if not transaction_reference:
        return HttpResponse("Missing reference", status=400)

    invoice_id = transaction_reference.replace("INV-", "")
    invoice = Invoice.objects.filter(id=invoice_id).first()

    if not invoice:
        return HttpResponse("Invalid invoice", status=400)

    PaymentLog.objects.create(
        provider="ozow",
        invoice=invoice,
        transaction_reference=transaction_reference,
        amount=amount,
        raw_request=dict(data),
        status=status,
    )

    if status == "Complete":

        if invoice.is_fully_paid():
            return HttpResponse("Already processed")

        if amount != invoice.amount_due:
            return HttpResponse("Amount mismatch", status=400)

        with transaction.atomic():
            invoice.record_payment(
                amount=amount,
                reference=f"OZOW-{transaction_reference}",
                note="Ozow payment received",
            )

    return HttpResponse("OK")

@login_required
def ozow_success(request):
    messages.success(request, "Payment completed successfully.")
    return redirect("orders")  # or your dashboard


@login_required
def ozow_cancel(request):
    messages.warning(request, "Payment was cancelled.")
    return redirect("orders")


@login_required
def ozow_error(request):
    messages.error(request, "An error occurred during payment.")
    return redirect("orders")


@login_required
def pay_invoice_ozow(request, invoice_id):
    """
    Redirects the client to Ozow payment gateway
    """

    invoice = get_object_or_404(Invoice, id=invoice_id)

    # Prevent payment if already paid
    if invoice.status == "paid":
        return redirect("view-invoice", invoice_id=invoice.id)

    amount = invoice.amount_due

    # ===============================
    # OZOW PAYMENT PARAMETERS
    # ===============================
    data = {
        "SiteCode": settings.OZOW_SITE_CODE,
        "CountryCode": "ZA",
        "CurrencyCode": "ZAR",
        "Amount": f"{amount:.2f}",
        "TransactionReference": f"INV-{invoice.id}",
        "BankReference": f"Invoice {invoice.id}",
        "Customer": invoice.client.name if invoice.client else "Customer",
        "CustomerEmail": invoice.client.email if invoice.client else "",
        "CancelUrl": settings.OZOW_CANCEL_URL,
        "ErrorUrl": settings.OZOW_ERROR_URL,
        "SuccessUrl": settings.OZOW_SUCCESS_URL,
        "NotifyUrl": settings.OZOW_NOTIFY_URL,
        "IsTest": settings.OZOW_IS_TEST,
    }

    # ===============================
    # CREATE OZOW HASH
    # ===============================
    hash_string = (
        data["SiteCode"]
        + data["CountryCode"]
        + data["CurrencyCode"]
        + data["Amount"]
        + data["TransactionReference"]
        + data["BankReference"]
        + data["Customer"]
        + data["CustomerEmail"]
        + data["CancelUrl"]
        + data["ErrorUrl"]
        + data["SuccessUrl"]
        + data["NotifyUrl"]
        + str(data["IsTest"])
        + settings.OZOW_PRIVATE_KEY
    )

    secure_hash = hashlib.sha512(hash_string.encode("utf-8")).hexdigest()

    data["HashCheck"] = secure_hash

    # ===============================
    # REDIRECT TO OZOW
    # ===============================
    ozow_url = settings.OZOW_PAYMENT_URL + "?" + urlencode(data)

    return redirect(ozow_url)