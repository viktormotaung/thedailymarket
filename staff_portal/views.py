# staff_portal/views.py
from __future__ import annotations

import json
from decimal import Decimal
from datetime import timedelta

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
from collections import Counter
from credit.models import CreditAccount
from transactions.models import Transaction
from orders.models import Order, OrderItem
from deliveries.models import DeliveryRun
from tasks.models import Task  # adjust if your Task app name differs
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

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

    # ✅ Revenue = positive transactions
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
    # Sales trend (orders per day)
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

        # KPI cards
        "kpi_orders": kpi_orders,
        "kpi_revenue": kpi_revenue,
        "kpi_deliveries": kpi_deliveries,
        "kpi_credit_used": kpi_credit_used,
        "kpi_open_tasks": kpi_open_tasks,
        "kpi_new_clients": kpi_new_clients,

        # Lists
        "orders": orders_qs,
        "deliveries": deliveries_qs,
        "tasks": tasks_qs,

        # Chart
        "sales_labels": json.dumps(labels),
        "sales_data": json.dumps(data),
    }

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
    qs = StaffProfile.objects.select_related("user").all()
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
    qs = qs.order_by("user__first_name", "user__last_name", "user__username")
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    page_start = (page_obj.number - 1) * paginator.per_page + 1
    ctx = {
        "staff_list": page_obj.object_list,
        "page_obj": page_obj,
        "page_start": page_start,
    }
    return render(request, "staff_portal/staff_profile.html", ctx)

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
def staff_profile_edit(request, pk: int):
    sp = get_object_or_404(StaffProfile.objects.select_related("user"), pk=pk)
    user_obj = sp.user
    if request.method == "POST":
        staff_form = StaffProfileForm(request.POST, instance=sp, prefix="sp")
        user_form = UserBasicsForm(request.POST, instance=user_obj, prefix="usr")
        if staff_form.is_valid() and user_form.is_valid():
            staff_form.save()
            user_form.save()
            return redirect(reverse("staff_profile_view", kwargs={"pk": sp.pk}))
    else:
        staff_form = StaffProfileForm(instance=sp, prefix="sp")
        user_form = UserBasicsForm(instance=user_obj, prefix="usr")
    return render(
        request,
        "staff_portal/staff_profile_edit.html",
        {"sp": sp, "user_obj": user_obj, "staff_form": staff_form, "user_form": user_form},
    )

@login_required
@staff_required
def staff_profile_create(request):
    if request.method == "POST":
        username = request.POST.get("username")
        first_name = request.POST.get("first_name", "")
        last_name = request.POST.get("last_name", "")
        email = request.POST.get("email", "")
        password = request.POST.get("password")

        job_title = request.POST.get("job_title", "")
        phone = request.POST.get("phone", "")
        status = request.POST.get("status", "pending")
        notes = request.POST.get("notes", "")
        link_sales = request.POST.get("link_sales") == "on"

        # Use transaction to ensure atomic save
        try:
            with transaction.atomic():
                # Create Django user
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    is_staff=True
                )

                # Create StaffProfile
                staff_profile = StaffProfile.objects.create(
                    user=user,
                    job_title=job_title,
                    phone=phone,
                    status=status,
                    notes=notes
                )

                # Optionally create SalesRepProfile
                if link_sales:
                    # Check if already exists just in case
                    SalesRepProfile.objects.get_or_create(user=user)

            messages.success(request, f"Staff profile for '{username}' created successfully.")
            return redirect("staff_profile")  # adjust to your staff list view

        except Exception as e:
            messages.error(request, f"Error creating staff profile: {e}")

    return render(request, "staff_portal/staff_profile_create.html")

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
