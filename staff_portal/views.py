# staff_portal/views.py
from __future__ import annotations
from seshibo_site.core.access import get_user_portal_access
import json
from decimal import Decimal
from datetime import timedelta
from tasks.models import Notification
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Count, Sum, F, Q, Value, DecimalField, IntegerField, Prefetch
)
from django.db.models import Count, Sum

from deliveries.models import (
    DeliveryRun,
    DeliveryStop,
    InternalDeliveryRate,
    ExternalDeliveryRate,
)
from profiles.models import StaffProfile, SalesRepProfile, DriverProfile
from profiles.forms import DriverProfileForm
from django.contrib.auth.hashers import check_password
import requests
from django.utils.crypto import get_random_string
from django.contrib.auth import get_user_model
from profiles.models import SalesRepProfile, SalesRole, SalesOperator
from django.contrib.auth.models import User
from django.db.models.expressions import ExpressionWrapper
from django.db.models.functions import Coalesce, TruncDay, Cast
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from clients.models import Client
from profiles.models import StaffProfile, CustomerProfile
from .forms import StaffProfileForm, UserBasicsForm, CustomerProfileEditForm
from profiles.forms import SalesRepProfileForm
from collections import Counter
from credit.models import CreditAccount
from transactions.models import Transaction
from orders.models import Order, OrderItem
from deliveries.models import DeliveryRun
from tasks.models import Task  # adjust if your Task app name differs
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.hashers import make_password
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST

# ---------------------------
# Auth helpers
# ---------------------------
def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")

# ---------------------------
# Utilities
# ---------------------------
def _day_start(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

# ---------------------------
# Dashboard
# ---------------------------

@login_required
@staff_required
def dashboard(request):

    # -------------------------------------------------
    # Date range
    # -------------------------------------------------
    now = timezone.localtime()
    param = request.GET.get("range", "today")

    def day_start(dt):
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    if param == "7d":
        start = day_start(now - timedelta(days=6))
        end = day_start(now + timedelta(days=1))
        range_name = "7d"
    else:
        start = day_start(now)
        end = day_start(now + timedelta(days=1))
        range_name = "today"

    # -------------------------------------------------
    # Orders
    # -------------------------------------------------
    orders_qs = (
        Order.objects
        .annotate(ts=Coalesce(
            "submitted_at",
            "approved_at",
            "reviewed_at",
            "updated_at",
            "order_date",
        ))
        .filter(ts__gte=start, ts__lt=end)
        .select_related("client")
        .order_by("-ts")[:25]
    )

    # -------------------------------------------------
    # Deliveries
    # -------------------------------------------------
    deliveries_qs = (
        DeliveryRun.objects
        .filter(
            service_date__gte=start.date(),
            service_date__lt=end.date()
        )
        .annotate(stops_count=Count("stops"))
        .order_by("-service_date", "-id")[:25]
    )

    # -------------------------------------------------
    # Tasks
    # -------------------------------------------------
    tasks_qs = (
        Task.objects
        .filter(created_at__gte=start, created_at__lt=end)
        .order_by("-created_at")[:25]
    )

    # -------------------------------------------------
    # KPI SNAPSHOTS
    # -------------------------------------------------
    kpi_orders = orders_qs.count()

    kpi_revenue = (
        Transaction.objects
        .filter(
            created_at__gte=start,
            created_at__lt=end,
            amount__gt=0
        )
        .aggregate(
            s=Coalesce(Sum("amount"), Decimal("0.00"))
        )["s"]
    )

    kpi_deliveries = deliveries_qs.count()

    kpi_credit_used = (
        CreditAccount.objects
        .aggregate(
            s=Coalesce(Sum("credit_used"), Decimal("0.00"))
        )["s"]
    )

    kpi_open_tasks = (
        Task.objects
        .filter(status__in=["OPEN", "IN_PROGRESS"])
        .count()
    )

    kpi_new_clients = (
        Client.objects
        .filter(created_at__gte=start, created_at__lt=end)
        .count()
    )

    # -------------------------------------------------
    # Sales trend
    # -------------------------------------------------
    month_start = day_start(now.replace(day=1))
    next_month = day_start((month_start + timedelta(days=32)).replace(day=1))

    order_days = (
        Order.objects
        .annotate(ts=Coalesce(
            "submitted_at",
            "approved_at",
            "reviewed_at",
            "updated_at",
            "order_date",
        ))
        .filter(ts__gte=month_start, ts__lt=next_month)
        .values_list("ts", flat=True)
    )

    day_counts = Counter(
        timezone.localtime(d).date()
        for d in order_days if d
    )

    labels, data = [], []
    cursor = month_start
    today_end = day_start(now + timedelta(days=1))

    while cursor < today_end:
        labels.append(cursor.strftime("%d %b"))
        data.append(int(day_counts.get(cursor.date(), 0)))
        cursor += timedelta(days=1)

    # -------------------------------------------------
    # Context
    # -------------------------------------------------
    context = {
        "range": range_name,

        "kpi_orders": kpi_orders,
        "kpi_revenue": kpi_revenue,
        "kpi_deliveries": kpi_deliveries,
        "kpi_credit_used": kpi_credit_used,
        "kpi_open_tasks": kpi_open_tasks,
        "kpi_new_clients": kpi_new_clients,

        "orders": orders_qs,
        "deliveries": deliveries_qs,
        "tasks": tasks_qs,

        "sales_labels": json.dumps(labels),
        "sales_data": json.dumps(data),
    }

    # -------------------------------------------------
    # Portal access flags
    # -------------------------------------------------
    access = get_user_portal_access(request.user)
    context.update(access)

    return render(request, "staff_portal/dashboard.html", context)

# ---------------------------




@login_required
@staff_required
def my_profile(request: HttpRequest) -> HttpResponse:
    user = request.user
    with transaction.atomic():
        sp, _created = StaffProfile.objects.get_or_create(user=user)
    ctx = {
        "sp": sp,
        "user_obj": user,
        "user_groups": user.groups.all().order_by("name"),
    }
    return render(request, "staff_portal/my_profile.html", ctx)




@login_required
@staff_required
def staff_profile(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    # =========================
    # ALL STAFF
    # =========================
    qs = (
        StaffProfile.objects
        .select_related("user")
        .all()
    )

    if q:
        qs = qs.filter(
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(job_title__icontains=q) |
            Q(phone__icontains=q)
        )

    if status in {"active", "pending", "inactive"}:
        qs = qs.filter(status=status)

    qs = qs.order_by(
        "user__first_name",
        "user__last_name",
        "user__username"
    )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    page_start = ((page_obj.number - 1) * paginator.per_page) + 1

    # =========================
    # SALES STAFF
    # =========================
    sales_staff = (
        SalesRepProfile.objects
        .select_related(
            "user",
            "staff_profile",
            "sales_operator",
            "supervisor",
        )
        .prefetch_related("roles")
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username",
        )
    )

    if q:
        sales_staff = sales_staff.filter(
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(staff_profile__job_title__icontains=q) |
            Q(staff_profile__phone__icontains=q) |
            Q(sales_operator__name__icontains=q)
        )

    if status in {"active", "pending", "inactive"}:
        sales_staff = sales_staff.filter(status=status)

    # =========================
    # LOGISTICS STAFF / DRIVERS
    # =========================
    logistics_staff = (
        DriverProfile.objects
        .select_related(
            "user",
            "staff_profile",
        )
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username",
        )
    )

    if q:
        logistics_staff = logistics_staff.filter(
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(staff_profile__job_title__icontains=q) |
            Q(staff_profile__phone__icontains=q)
        )

    if status in {"active", "pending", "inactive"}:
        logistics_staff = logistics_staff.filter(status=status)

    ctx = {
        "staff_list": page_obj.object_list,
        "page_obj": page_obj,
        "page_start": page_start,
        "sales_staff": sales_staff,
        "logistics_staff": logistics_staff,
    }

    return render(
        request,
        "staff_portal/staff_profile.html",
        ctx
    )


@login_required
@staff_required
def driver_profile_create(request):
    staff_profiles = (
        StaffProfile.objects
        .select_related("user")
        .filter(driver_profile__isnull=True)
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username"
        )
    )

    if request.method == "POST":
        form = DriverProfileForm(request.POST)
        staff_profile_id = request.POST.get("staff_profile")

        if not staff_profile_id:
            messages.error(request, "Please select a staff member.")
            return redirect("driver_profile_create")

        sp = get_object_or_404(
            StaffProfile.objects.select_related("user"),
            pk=staff_profile_id
        )

        if DriverProfile.objects.filter(staff_profile=sp).exists():
            messages.error(request, "This staff member already has a driver profile.")
            return redirect("driver_profile_create")

        if form.is_valid():
            try:
                with transaction.atomic():
                    driver_profile = form.save(commit=False)
                    driver_profile.user = sp.user
                    driver_profile.staff_profile = sp
                    driver_profile.save()

                    sp.department = "LOGISTICS"
                    sp.save(
                        update_fields=[
                            "department",
                            "updated_at",
                        ]
                    )

                messages.success(
                    request,
                    "Driver profile created successfully."
                )

                return redirect(
                    "staff_profile"
                )

            except Exception as e:
                messages.error(
                    request,
                    f"Error creating driver profile: {e}"
                )

        else:
            messages.error(
                request,
                "Please correct the errors below."
            )

    else:
        form = DriverProfileForm()

    return render(
        request,
        "staff_portal/driver_profile_create.html",
        {
            "form": form,
            "staff_profiles": staff_profiles,
        }
    )



@login_required
@staff_required
def driver_profile_view(request, staff_pk):
    sp = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=staff_pk
    )

    user_obj = sp.user

    driver_profile = get_object_or_404(
        DriverProfile.objects.select_related(
            "user",
            "staff_profile",
        ),
        staff_profile=sp
    )

    delivery_runs = (
        DeliveryRun.objects
        .select_related("vehicle")
        .prefetch_related("stops")
        .filter(driver=user_obj)
        .order_by("-service_date", "-id")
    )

    delivery_stops = (
        DeliveryStop.objects
        .select_related(
            "run",
            "order",
            "supplier",
        )
        .filter(run__driver=user_obj)
        .order_by("-run__service_date", "run_id", "sequence", "id")
    )

    internal_rate = (
        InternalDeliveryRate.objects
        .filter(is_active=True)
        .first()
    )

    external_rate = (
        ExternalDeliveryRate.objects
        .filter(is_active=True)
        .first()
    )

    run_summary = delivery_runs.aggregate(
        total_runs=Count("id"),
        total_distance=Sum("total_distance_km"),
        total_driver_cost=Sum("driver_total_cost"),
        total_assistant_cost=Sum("assistant_total_cost"),
        total_overall_cost=Sum("overall_total_cost"),
    )

    stop_summary = delivery_stops.aggregate(
        total_stops=Count("id"),
    )

    user_groups = (
        user_obj.groups
        .all()
        .order_by("name")
    )

    return render(
        request,
        "staff_portal/driver_profile_view.html",
        {
            "sp": sp,
            "user_obj": user_obj,
            "driver_profile": driver_profile,
            "delivery_runs": delivery_runs,
            "delivery_stops": delivery_stops,
            "internal_rate": internal_rate,
            "external_rate": external_rate,
            "run_summary": run_summary,
            "stop_summary": stop_summary,
            "user_groups": user_groups,
        }
    )





def staff_profile_view(request, pk: int):
    sp = get_object_or_404(StaffProfile.objects.select_related("user"), pk=pk)
    user_obj = sp.user
    user_groups = list(user_obj.groups.all().only("name"))

    # Handle form submission if this is the edit page
    if request.method == "POST":
        form = StaffProfileForm(request.POST, instance=sp)
        if form.is_valid():
            form.save()
            return redirect("staff_profile", pk=sp.pk)
    else:
        form = StaffProfileForm(instance=sp)

    return render(
        request,
        "staff_portal/staff_profile_view.html",
        {
            "sp": sp,
            "user_obj": user_obj,
            "user_groups": user_groups,
            "form": form,  # pass form to template
        },
    )



@login_required
@staff_required
def sales_staff_profile_view(request, staff_pk):
    sp = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=staff_pk
    )

    user_obj = sp.user

    sales_profile = (
        SalesRepProfile.objects
        .select_related(
            "user",
            "staff_profile",
            "sales_operator",
            "supervisor",
        )
        .prefetch_related("roles")
        .filter(
            staff_profile=sp
        )
        .first()
    )

    user_groups = (
        user_obj.groups
        .all()
        .order_by("name")
    )

    sales_roles = []

    if sales_profile:
        sales_roles = (
            sales_profile.roles
            .all()
            .order_by("name")
        )

    return render(
        request,
        "staff_portal/sales_staff_profile_view.html",
        {
            "sp": sp,
            "user_obj": user_obj,
            "sales_profile": sales_profile,
            "sales_roles": sales_roles,
            "user_groups": user_groups,
        },
    )



@login_required
@staff_required
def sales_staff_profile_edit(request, staff_pk):
    sp = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=staff_pk
    )

    user_obj = sp.user

    sales_profile, created = SalesRepProfile.objects.get_or_create(
        staff_profile=sp,
        defaults={
            "user": user_obj,
            "status": sp.status,
            "department": "SALES",
        }
    )

    if request.method == "POST":

        # =========================
        # USER
        # =========================
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip()

        # =========================
        # STAFF PROFILE
        # =========================
        job_title = (request.POST.get("job_title") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        staff_status = (request.POST.get("staff_status") or "").strip()
        notes = (request.POST.get("notes") or "").strip()

        # =========================
        # SALES PROFILE
        # =========================
        sales_status = (request.POST.get("sales_status") or "").strip()
        department = (request.POST.get("department") or "").strip()

        sales_operator_id = request.POST.get("sales_operator")
        supervisor_id = request.POST.get("supervisor")

        base_commission_pct = (
            request.POST.get("base_commission_pct") or 0
        )

        bonus_commission_pct = (
            request.POST.get("bonus_commission_pct") or 0
        )

        role_ids = request.POST.getlist("roles")

        try:

            with transaction.atomic():

                # =========================
                # UPDATE USER
                # =========================
                user_obj.first_name = first_name
                user_obj.last_name = last_name
                user_obj.email = email

                user_obj.save(
                    update_fields=[
                        "first_name",
                        "last_name",
                        "email",
                    ]
                )

                # =========================
                # UPDATE STAFF PROFILE
                # =========================
                sp.job_title = job_title
                sp.phone = phone
                sp.status = staff_status
                sp.notes = notes

                sp.can_access_sales = True
                sp.department = "SALES"

                sp.save(
                    update_fields=[
                        "job_title",
                        "phone",
                        "status",
                        "notes",
                        "can_access_sales",
                        "department",
                        "updated_at",
                    ]
                )

                # =========================
                # UPDATE SALES PROFILE
                # =========================
                sales_profile.status = sales_status
                sales_profile.department = department or "SALES"

                sales_profile.base_commission_pct = (
                    Decimal(base_commission_pct or 0)
                )

                sales_profile.bonus_commission_pct = (
                    Decimal(bonus_commission_pct or 0)
                )

                # =========================
                # SALES OPERATOR
                # =========================
                if sales_operator_id:
                    sales_profile.sales_operator_id = sales_operator_id
                else:
                    sales_profile.sales_operator = None

                # =========================
                # SUPERVISOR
                # =========================
                if supervisor_id:
                    sales_profile.supervisor_id = supervisor_id
                else:
                    sales_profile.supervisor = None

                sales_profile.save()

                # =========================
                # ROLES
                # =========================
                sales_profile.roles.set(role_ids)

            messages.success(
                request,
                "Sales staff profile updated successfully."
            )

            return redirect(
                "sales_staff_profile_view",
                staff_pk=sp.pk
            )

        except Exception as e:

            messages.error(
                request,
                f"Error updating sales staff profile: {e}"
            )

    sales_operators = (
        SalesOperator.objects
        .all()
        .order_by("name")
    )

    supervisors = (
        get_user_model()
        .objects
        .filter(is_staff=True)
        .order_by("first_name", "last_name", "username")
    )

    sales_roles = (
        SalesRole.objects
        .all()
        .order_by("name")
    )

    ctx = {
        "sp": sp,
        "user_obj": user_obj,
        "sales_profile": sales_profile,

        "sales_operators": sales_operators,
        "supervisors": supervisors,
        "sales_roles": sales_roles,
    }

    return render(
        request,
        "staff_portal/sales_staff_profile_edit.html",
        ctx
    )



@login_required
@staff_required
def sales_staff_profile_create(request):
    staff_profiles = (
        StaffProfile.objects
        .select_related("user")
        .filter(sales_profile__isnull=True)
        .order_by("user__first_name", "user__last_name", "user__username")
    )

    if request.method == "POST":
        form = SalesRepProfileForm(request.POST)
        staff_profile_id = request.POST.get("staff_profile")

        if not staff_profile_id:
            messages.error(request, "Please select a staff member.")
            return redirect("sales_staff_profile_create")

        sp = get_object_or_404(
            StaffProfile.objects.select_related("user"),
            pk=staff_profile_id
        )

        if SalesRepProfile.objects.filter(staff_profile=sp).exists():
            messages.error(request, "This staff member already has a sales rep profile.")
            return redirect("sales_staff_profile_create")

        if form.is_valid():
            try:
                with transaction.atomic():
                    sales_profile = form.save(commit=False)
                    sales_profile.user = sp.user
                    sales_profile.staff_profile = sp
                    sales_profile.department = "SALES"
                    sales_profile.save()

                    form.save_m2m()

                    sp.department = "SALES"
                    sp.can_access_sales = True
                    sp.save(
                        update_fields=[
                            "department",
                            "can_access_sales",
                            "updated_at",
                        ]
                    )

                messages.success(request, "Sales rep profile created successfully.")

                return redirect(
                    "sales_staff_profile_view",
                    staff_pk=sp.pk
                )

            except Exception as e:
                messages.error(request, f"Error creating sales rep profile: {e}")

        else:
            messages.error(request, "Please correct the errors below.")

    else:
        form = SalesRepProfileForm()

    return render(
        request,
        "staff_portal/sales_staff_profile_create.html",
        {
            "form": form,
            "staff_profiles": staff_profiles,
        }
    )

@login_required
@staff_required
def staff_profile_edit(request, pk: int):
    sp = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=pk
    )

    user_obj = sp.user

    all_groups = Group.objects.all().order_by("name")

    if request.method == "POST":
        staff_form = StaffProfileForm(
            request.POST,
            instance=sp,
            prefix="sp"
        )

        user_form = UserBasicsForm(
            request.POST,
            instance=user_obj,
            prefix="usr"
        )

        selected_group_ids = request.POST.getlist("groups")

        if staff_form.is_valid() and user_form.is_valid():
            with transaction.atomic():
                staff_form.save()
                user_form.save()

                user_obj.groups.set(selected_group_ids)

            messages.success(
                request,
                "Staff profile updated successfully."
            )

            return redirect(
                reverse("staff_profile_view", kwargs={"pk": sp.pk})
            )

        messages.error(request, "Please correct the errors below.")

    else:
        staff_form = StaffProfileForm(
            instance=sp,
            prefix="sp"
        )

        user_form = UserBasicsForm(
            instance=user_obj,
            prefix="usr"
        )

    user_groups = user_obj.groups.all().order_by("name")

    return render(
        request,
        "staff_portal/staff_profile_edit.html",
        {
            "sp": sp,
            "user_obj": user_obj,
            "staff_form": staff_form,
            "user_form": user_form,
            "user_groups": user_groups,
            "all_groups": all_groups,
        },
    )


@login_required
@staff_required
def staff_profile_send_password_sms(request, pk):
    sp = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=pk
    )

    if request.method != "POST":
        return redirect("staff_profile_view", pk=sp.pk)

    auth_code = (request.POST.get("auth_code") or "").strip()

    if not auth_code.isdigit() or len(auth_code) != 5:
        messages.error(request, "Authorisation code must be exactly 5 digits.")
        return redirect("staff_profile_view", pk=sp.pk)

    # This is the logged-in support/admin staff member
    request_staff = getattr(request.user, "staff_profile", None)

    if not request_staff:
        messages.error(request, "Your staff profile could not be found.")
        return redirect("staff_profile_view", pk=sp.pk)

    if not request_staff.auth_code_hash:
        messages.error(request, "Your account does not have an authorisation code set.")
        return redirect("staff_profile_view", pk=sp.pk)

    if not request_staff.verify_auth_code(auth_code):
        messages.error(request, "Invalid authorisation code.")
        return redirect("staff_profile_view", pk=sp.pk)

    # This is the target staff member whose password is being reset
    user = sp.user

    new_password = get_random_string(
        5,
        allowed_chars="23456789"
    )

    user.set_password(new_password)
    user.save(update_fields=["password"])

    sms_sent, sms_message = send_staff_password_sms(
        phone=sp.phone,
        username=user.username,
        password=new_password,
    )

    if sms_sent:
        messages.success(request, "Temporary password generated and sent via SMS.")
    else:
        messages.warning(request, f"Password was updated, but SMS failed. {sms_message}")

    return redirect("staff_profile_view", pk=sp.pk)


@login_required
@staff_required
def staff_profile_send_password_email(request, pk):
    sp = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=pk
    )

    if request.method != "POST":
        return redirect("staff_profile_view", pk=sp.pk)

    auth_code = (request.POST.get("auth_code") or "").strip()

    if not auth_code.isdigit() or len(auth_code) != 5:
        messages.error(request, "Authorisation code must be exactly 5 digits.")
        return redirect("staff_profile_view", pk=sp.pk)

    # This is the logged-in support/admin staff member
    request_staff = getattr(request.user, "staff_profile", None)

    if not request_staff:
        messages.error(request, "Your staff profile could not be found.")
        return redirect("staff_profile_view", pk=sp.pk)

    if not request_staff.auth_code_hash:
        messages.error(request, "Your account does not have an authorisation code set.")
        return redirect("staff_profile_view", pk=sp.pk)

    if not request_staff.verify_auth_code(auth_code):
        messages.error(request, "Invalid authorisation code.")
        return redirect("staff_profile_view", pk=sp.pk)

    # This is the target staff member whose password is being reset
    user = sp.user

    if not user.email:
        messages.error(request, "This staff member does not have an email address.")
        return redirect("staff_profile_view", pk=sp.pk)

    new_password = get_random_string(
        5,
        allowed_chars="23456789"
    )

    user.set_password(new_password)
    user.save(update_fields=["password"])

    subject = "The Daily Market - Temporary Staff Login Password"

    body = (
        f"Hi {user.get_full_name() or user.username},\n\n"
        "Your staff login password has been reset.\n\n"
        f"Username: {user.username}\n"
        f"Temporary Password: {new_password}\n\n"
        "Please log in and change your password."
    )

    EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    ).send(fail_silently=False)

    messages.success(request, "Temporary password generated and sent via email.")

    return redirect("staff_profile_view", pk=sp.pk)



def normalize_sa_number(phone):
    phone = (phone or "").strip().replace(" ", "").replace("-", "")

    if phone.startswith("0"):
        phone = "27" + phone[1:]

    if phone.startswith("+"):
        phone = phone[1:]

    return phone


def send_staff_password_sms(phone, username, password):
    client_id = getattr(settings, "SMSPORTAL_CLIENT_ID", "")
    api_secret = getattr(settings, "SMSPORTAL_API_SECRET", "")

    if not client_id or not api_secret:
        return False, "SMSPortal credentials are missing."

    phone = normalize_sa_number(phone)

    if not phone:
        return False, "No phone number provided."

    message = (
        "The Daily Market staff profile created. "
        f"Username: {username}. "
        f"Temporary password: {password}. "
        "Please log in and change your password."
    )

    url = "https://rest.smsportal.com/v1/bulkmessages"

    payload = {
        "messages": [
            {
                "content": message,
                "destination": phone,
            }
        ]
    }

    try:
        response = requests.post(
            url,
            json=payload,
            auth=(client_id, api_secret),
            timeout=20,
        )

        if response.status_code in [200, 201, 202]:
            return True, "SMS sent successfully."

        return False, f"SMS failed: {response.status_code} - {response.text}"

    except Exception as e:
        return False, f"SMS error: {e}"


@login_required
@staff_required
def staff_profile_create(request):
    User = get_user_model()

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip()

        job_title = (request.POST.get("job_title") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        status = request.POST.get("status") or "pending"
        notes = (request.POST.get("notes") or "").strip()

        link_sales = request.POST.get("link_sales") == "on"

        if not username:
            messages.error(request, "Username is required.")
            return render(request, "staff_portal/staff_profile_create.html")

        if not phone:
            messages.error(request, "Phone number is required so the password can be sent by SMS.")
            return render(request, "staff_portal/staff_profile_create.html")

        if User.objects.using("default").filter(username=username).exists():
            messages.error(request, "A user with this username already exists in the main database.")
            return render(request, "staff_portal/staff_profile_create.html")

        if User.objects.using("dummy").filter(username=username).exists():
            messages.error(request, "A user with this username already exists in the dummy database.")
            return render(request, "staff_portal/staff_profile_create.html")

        if email and User.objects.using("default").filter(email=email).exists():
            messages.error(request, "A user with this email address already exists in the main database.")
            return render(request, "staff_portal/staff_profile_create.html")

        if email and User.objects.using("dummy").filter(email=email).exists():
            messages.error(request, "A user with this email address already exists in the dummy database.")
            return render(request, "staff_portal/staff_profile_create.html")

        generated_password = get_random_string(
            10,
            allowed_chars="abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        )

        try:
            with transaction.atomic(using="default"):
                user = User.objects.db_manager("default").create_user(
                    username=username,
                    email=email,
                    password=generated_password,
                    first_name=first_name,
                    last_name=last_name,
                )

                user.is_staff = True
                user.save(
                    using="default",
                    update_fields=["is_staff"]
                )

                staff_profile = StaffProfile.objects.using("default").create(
                    user=user,
                    job_title=job_title,
                    phone=phone,
                    status=status,
                    notes=notes,
                )

                if link_sales:
                    SalesRepProfile.objects.using("default").get_or_create(
                        user=user,
                        defaults={
                            "staff_profile": staff_profile,
                            "status": status,
                            "department": "SALES",
                        },
                    )

                    staff_profile.can_access_sales = True
                    staff_profile.department = "SALES"
                    staff_profile.save(
                        using="default",
                        update_fields=[
                            "can_access_sales",
                            "department",
                            "updated_at",
                        ]
                    )

            sms_sent, sms_message = send_staff_password_sms(
                phone=phone,
                username=username,
                password=generated_password,
            )

            if sms_sent:
                messages.success(
                    request,
                    f"Staff profile for {username} created successfully. Login details sent by SMS."
                )
            else:
                messages.warning(
                    request,
                    f"Staff profile for {username} created, but SMS was not sent. {sms_message}"
                )

            return redirect(
                "staff_profile_view",
                pk=staff_profile.pk
            )

        except Exception as e:
            messages.error(
                request,
                f"Error creating staff profile: {e}"
            )

    return render(
        request,
        "staff_portal/staff_profile_create.html"
    )


# ---------------------------
# Customer Profiles
# ---------------------------
@login_required
@staff_required
def customer_profile(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    profile_type = (request.GET.get("profile_type") or "").strip()

    qs = CustomerProfile.objects.select_related("user", "client").all()

    if q:
        qs = qs.filter(
            Q(user__username__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(display_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(company_name__icontains=q) |
            Q(client__name__icontains=q)
        )
    if status in {"active", "pending", "inactive"}:
        qs = qs.filter(status=status)
    if profile_type in {"PERSONAL", "BUSINESS"}:
        qs = qs.filter(profile_type=profile_type)

    qs = qs.order_by("user__first_name", "user__last_name", "user__username")
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    page_start = (page_obj.number - 1) * paginator.per_page + 1

    ctx = {
        "customers": page_obj.object_list,
        "page_obj": page_obj,
        "page_start": page_start,
    }
    return render(request, "staff_portal/customer_profile.html", ctx)




@login_required
@staff_required
def customer_profile_view(request, pk: int):
    cp = get_object_or_404(CustomerProfile, pk=pk)
    client = getattr(cp, "client", None)

    ctx = {
        "cp": cp,
        "user_obj": cp.user,
        "client": client,
        "activity": {"orders": [], "invoices": [], "transactions": []},
        "metrics": {"orders_count": 0, "invoices_count": 0, "transactions_count": 0, "balance": None},
    }

    try:
        from orders.models import Order as _Order
        if client:
            ctx["activity"]["orders"] = _Order.objects.filter(client=client).order_by("-created_at")[:10]
            ctx["metrics"]["orders_count"] = _Order.objects.filter(client=client).count()
    except Exception:
        pass

    try:
        from invoices.models import Invoice
        if client:
            ctx["activity"]["invoices"] = Invoice.objects.filter(client=client).order_by("-created_at")[:10]
            ctx["metrics"]["invoices_count"] = Invoice.objects.filter(client=client).count()
    except Exception:
        pass

    try:
        from transactions.models import Transaction
        if client:
            ctx["activity"]["transactions"] = Transaction.objects.filter(client=client).order_by("-created_at")[:10]
            ctx["metrics"]["transactions_count"] = Transaction.objects.filter(client=client).count()
    except Exception:
        pass

    return render(request, "staff_portal/customer_profile_view.html", ctx)





@login_required
@staff_required
def customer_profile_edit(request, pk: int):
    """
    Edit a CustomerProfile.
    If status changes from 'pending' to 'active' (first time), send welcome email.
    """
    cp = get_object_or_404(CustomerProfile, pk=pk)

    def _send_customer_activation_email(user, profile):
        login_url = request.build_absolute_uri(reverse("client-login"))
        ctx = {"user": user, "profile": profile, "login_url": login_url}
        subject = "Seshibo Daily Market – Your account is now active"
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "accounts@seshibodailymarket.co.za")
        recipient = (user.email or user.username)
        if not recipient:
            return False
        text_body = render_to_string("email/welcome_email.txt", ctx)
        html_body = render_to_string("email/welcome_email.html", ctx)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[recipient],
            headers={"Reply-To": getattr(settings, "SUPPORT_EMAIL", "support@seshibodailymarket.co.za")},
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        return True

    if request.method == "POST":
        form = CustomerProfileEditForm(request.POST, instance=cp)
        prev_status = cp.status
        if form.is_valid():
            updated_cp = form.save()
            just_activated = (prev_status == "pending" and updated_cp.status == "active")
            if just_activated:
                try:
                    sent = _send_customer_activation_email(updated_cp.user, updated_cp)
                    if sent:
                        messages.success(request, "Customer profile updated and welcome email sent.")
                    else:
                        messages.warning(request, "Customer activated, but no email address on file.")
                except Exception as e:
                    messages.warning(request, f"Customer activated, but failed to send email: {e}")
            else:
                messages.success(request, "Customer profile updated successfully.")
            return redirect("customer_profile_view", pk=updated_cp.pk)
        else:
            messages.error(request, "Please fix the errors below and try again.")
    else:
        form = CustomerProfileEditForm(instance=cp)

    ctx = {"cp": cp, "form": form, "user_obj": cp.user}
    return render(request, "staff_portal/customer_profile_edit.html", ctx)




def send_staff_profile_created_email(user, staff_profile, request):
    subject = "The Daily Market – Your staff profile is ready"

    # Determine role
    if user.groups.filter(name="View Only").exists():
        role = "View Only"
    else:
        role = "Undefined"

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    # ✅ POINT TO HOME APP PASSWORD SET VIEW
    set_password_url = request.build_absolute_uri(
        reverse(
            "staff-password-set",
            kwargs={"uidb64": uid, "token": token},
        )
    )

    ctx = {
        "user": user,
        "staff_profile": staff_profile,
        "role": role,
        "set_password_url": set_password_url,
        "support_email": getattr(
            settings, "SUPPORT_EMAIL", "support@seshibodailymarket.co.za"
        ),
    }

    text_body = render_to_string(
        "email/staff_profile_created.txt", ctx
    )
    html_body = render_to_string(
        "email/staff_profile_created.html", ctx
    )

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
def staff_profile_email(request, pk):
    sp = get_object_or_404(StaffProfile, pk=pk)

    # Safety check
    if not sp.user.email:
        messages.error(request, "This staff member does not have an email address.")
        return redirect("staff_profile")

    send_staff_profile_created_email(
        user=sp.user,
        staff_profile=sp,
        request=request,
    )

    messages.success(
        request,
        f"Staff profile email sent to {sp.user.get_full_name() or sp.user.username}."
    )

    return redirect("staff_profile")




@login_required
def open_notification(request, pk):
    notification = get_object_or_404(Notification, pk=pk)

    user = request.user

    if notification.scope == Notification.Scope.INDIVIDUAL:
        if notification.recipient != user:
            return redirect("staff-dashboard")

    if notification.scope == Notification.Scope.DEPARTMENT:
        staff = getattr(user, "staff_profile", None)
        if not staff or staff.status != "active" or staff.department != notification.department:
            return redirect("staff-dashboard")

    notification.mark_opened(user)

    obj = notification.related_object

    if not obj:
        return redirect("staff-dashboard")

    if notification.notification_type == Notification.NotificationType.TASK:
        return redirect("tasks")

    if notification.notification_type == Notification.NotificationType.TICKET:
        return redirect("staff-dashboard")  # change later to ticket detail

    return redirect("staff-dashboard")


@login_required
@staff_required
@require_POST
def customer_profile_send_password_sms(request, pk):
    cp = get_object_or_404(
        CustomerProfile.objects.select_related("user"),
        pk=pk
    )

    auth_code = (request.POST.get("auth_code") or "").strip()

    if not auth_code.isdigit() or len(auth_code) != 5:
        messages.error(
            request,
            "Authorisation code must be exactly 5 digits."
        )
        return redirect("customer_profile_view", pk=pk)

    # Logged-in staff member
    request_staff = getattr(request.user, "staff_profile", None)

    if not request_staff:
        messages.error(
            request,
            "Your staff profile could not be found."
        )
        return redirect("customer_profile_view", pk=pk)

    if not request_staff.auth_code_hash:
        messages.error(
            request,
            "Your account does not have an authorisation code set."
        )
        return redirect("customer_profile_view", pk=pk)

    if not request_staff.verify_auth_code(auth_code):
        messages.error(
            request,
            "Invalid authorisation code."
        )
        return redirect("customer_profile_view", pk=pk)

    # Customer account
    user = cp.user

    # Generate a temporary password automatically
    new_password = get_random_string(
        5,
        allowed_chars="23456789"
    )

    user.set_password(new_password)
    user.save(update_fields=["password"])

    sent, msg = send_customer_password_sms(
        phone=cp.phone,
        username=user.username,
        password=new_password,
    )

    if sent:
        messages.success(
            request,
            "Temporary password generated and sent via SMS."
        )
    else:
        messages.warning(
            request,
            f"Password was updated, but SMS failed. {msg}"
        )

    return redirect("customer_profile_view", pk=pk)


def send_customer_password_sms(phone, username, password):
    client_id = getattr(settings, "SMSPORTAL_CLIENT_ID", "")
    api_secret = getattr(settings, "SMSPORTAL_API_SECRET", "")

    if not client_id or not api_secret:
        return False, "SMSPortal credentials are missing."

    phone = normalize_sa_number(phone)

    if not phone:
        return False, "No phone number provided."

    message = (
        "Welcome to The Daily Market.\n\n"
        f"Username: {username}\n"
        f"Temporary Password: {password}\n\n"
        "Please log in to your customer account and change your password."
    )

    url = "https://rest.smsportal.com/v1/bulkmessages"

    payload = {
        "messages": [
            {
                "content": message,
                "destination": phone,
            }
        ]
    }

    try:
        response = requests.post(
            url,
            json=payload,
            auth=(client_id, api_secret),
            timeout=20,
        )

        if response.status_code in [200, 201, 202]:
            return True, "SMS sent successfully."

        return False, f"SMS failed: {response.status_code} - {response.text}"

    except Exception as e:
        return False, f"SMS error: {e}"




@login_required
@staff_required
@require_POST
def customer_profile_send_password_email(request, pk):
    cp = get_object_or_404(
        CustomerProfile.objects.select_related("user"),
        pk=pk
    )

    auth_code = (request.POST.get("auth_code") or "").strip()

    if not auth_code.isdigit() or len(auth_code) != 5:
        messages.error(
            request,
            "Authorisation code must be exactly 5 digits."
        )
        return redirect("customer_profile_view", pk=pk)

    # Logged-in staff member
    request_staff = getattr(request.user, "staff_profile", None)

    if not request_staff:
        messages.error(
            request,
            "Your staff profile could not be found."
        )
        return redirect("customer_profile_view", pk=pk)

    if not request_staff.auth_code_hash:
        messages.error(
            request,
            "Your account does not have an authorisation code set."
        )
        return redirect("customer_profile_view", pk=pk)

    if not request_staff.verify_auth_code(auth_code):
        messages.error(
            request,
            "Invalid authorisation code."
        )
        return redirect("customer_profile_view", pk=pk)

    # Customer account
    user = cp.user

    if not user.email:
        messages.error(
            request,
            "This customer does not have an email address."
        )
        return redirect("customer_profile_view", pk=pk)

    # Generate a temporary password automatically
    new_password = get_random_string(
        5,
        allowed_chars="23456789"
    )

    user.set_password(new_password)
    user.save(update_fields=["password"])

    login_url = request.build_absolute_uri(
        reverse("client-login")
    )

    ctx = {
        "user": user,
        "profile": cp,
        "password": new_password,
        "login_url": login_url,
    }

    subject = "Welcome to The Daily Market - Your Customer Login Details"

    text_body = render_to_string(
        "email/customer_password.txt",
        ctx,
    )

    html_body = render_to_string(
        "email/customer_password.html",
        ctx,
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )

    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

    messages.success(
        request,
        "Temporary password generated and sent via email."
    )

    return redirect("customer_profile_view", pk=pk)


def send_customer_activation_email(request, user, profile):
    """
    Send the customer welcome / activation email.

    Returns:
        (success: bool, message: str)
    """

    recipient = user.email or user.username

    if not recipient:
        return False, "Customer does not have an email address."

    login_url = request.build_absolute_uri(
        reverse("client-login")
    )

    ctx = {
        "user": user,
        "profile": profile,
        "login_url": login_url,
    }

    subject = "The Daily Market - Welcome! Your Customer Account is Active"

    from_email = getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        "accounts@thedailymarket.co.za",
    )

    text_body = render_to_string(
        "email/welcome_email.txt",
        ctx,
    )

    html_body = render_to_string(
        "email/welcome_email.html",
        ctx,
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[recipient],
        headers={
            "Reply-To": getattr(
                settings,
                "SUPPORT_EMAIL",
                "support@thedailymarket.co.za",
            )
        },
    )

    msg.attach_alternative(
        html_body,
        "text/html",
    )

    try:
        msg.send(fail_silently=False)
        return True, "Welcome email sent successfully."

    except Exception as e:
        return False, str(e)
    

@login_required
@staff_required
@require_POST
def customer_profile_send_welcome_email(request, pk):
    cp = get_object_or_404(
        CustomerProfile.objects.select_related("user"),
        pk=pk
    )

    auth_code = (request.POST.get("auth_code") or "").strip()

    if not auth_code.isdigit() or len(auth_code) != 5:
        messages.error(
            request,
            "Authorisation code must be exactly 5 digits."
        )
        return redirect("customer_profile_view", pk=pk)

    request_staff = getattr(request.user, "staff_profile", None)

    if not request_staff:
        messages.error(
            request,
            "Your staff profile could not be found."
        )
        return redirect("customer_profile_view", pk=pk)

    if not request_staff.auth_code_hash:
        messages.error(
            request,
            "Your account does not have an authorisation code set."
        )
        return redirect("customer_profile_view", pk=pk)

    if not request_staff.verify_auth_code(auth_code):
        messages.error(
            request,
            "Invalid authorisation code."
        )
        return redirect("customer_profile_view", pk=pk)

    sent, msg = send_customer_activation_email(
        request,
        cp.user,
        cp,
    )

    if sent:
        messages.success(
            request,
            "Welcome email sent successfully."
        )
    else:
        messages.error(
            request,
            msg,
        )

    return redirect("customer_profile_view", pk=pk)
