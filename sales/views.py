# C:\Seshibo Daily Market\seshibo_site\sales\views.py
from decimal import Decimal
from datetime import timedelta, date, datetime
from django.db import models as db_models  # <--- import db models utilities (Sum, Count, etc.)
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Count, Q
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
import calendar
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from clients.models import Prospect, ProspectUpdate, Client
from clients.forms import ProspectForm, ProspectUpdateForm
from django.utils.timezone import localdate
from invoices.models import CommissionEntry, Invoice, MonthlyTarget, MonthlyTargetAllocation, MonthlyCommission
from products.models import Category, Product
from orders.models import Order, OrderItem, Quotation, QuotationItem
from django import forms
from django.forms import ModelForm, inlineformset_factory, widgets
from django.db.models import (
    Sum, Count, F, Q, Value, DecimalField, IntegerField, ExpressionWrapper
)
from communications.services.whatsapp import send_invoice_whatsapp
from communications.services.smsportal import send_sms
from django.core.mail import EmailMultiAlternatives
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.views.decorators.http import require_POST
from communications.models import CommunicationLog
from communications.services.whatsapp import send_quotation_whatsapp
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from tasks.forms import TicketCreateForm
from communications.services.whatsapp import send_whatsapp_message
import json
from invoices.forms import MonthlyTargetForm
from django.db.models import Q
from datetime import date
import calendar

from profiles.models import SalesRepProfile
from invoices.models import CommissionEntry, Invoice, MonthlyTarget


from invoices.models import MonthlyTarget
from collections import OrderedDict
from django.db.models import Count, Sum
from collections import Counter
from django.contrib.auth import get_user_model
from django.db.models.functions import Coalesce
from invoices.models import Invoice
from django.utils.timezone import now
from tasks.models import Task, Ticket
from django.contrib import messages
from django.http import Http404
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.http import JsonResponse
from credit.models import CreditAccount
from clients.forms import ClientEditForm
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from .forms import JobApplicationForm
from datetime import date
from decimal import Decimal
import calendar
from django.db.models import Sum, DecimalField
from django.db.models.functions import Coalesce
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.shortcuts import render
from django.utils.timezone import localdate

from invoices.models import CommissionEntry, MonthlyTarget
from profiles.models import SalesRepProfile

User = get_user_model()
User = get_user_model()
DAY_OPTIONS = [7, 14, 30, 60]





@login_required
def sales_dashboard(request):
    user = request.user
    now_dt = timezone.now()
    today = timezone.localdate()

    range_param = request.GET.get("range", "today")

    def month_start(d):
        return d.replace(day=1)

    def previous_month_start(d):
        if d.month == 1:
            return d.replace(year=d.year - 1, month=12, day=1)
        return d.replace(month=d.month - 1, day=1)

    def next_month_start(d):
        if d.month == 12:
            return d.replace(year=d.year + 1, month=1, day=1)
        return d.replace(month=d.month + 1, day=1)

    # =====================================================
    # DATE RANGE
    # =====================================================
    if range_param == "7d":
        start_dt = now_dt - timedelta(days=7)
        end_dt = now_dt

        prev_start_dt = start_dt - timedelta(days=7)
        prev_end_dt = start_dt

        period_label = "Last 7 days"
        comparison_label = "Previous 7 days"

    elif range_param == "month":
        start_date = today.replace(day=1)
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = now_dt

        prev_start_date = previous_month_start(start_date)
        prev_start_dt = timezone.make_aware(datetime.combine(prev_start_date, datetime.min.time()))
        prev_end_dt = prev_start_dt + (end_dt - start_dt)

        period_label = "This month"
        comparison_label = "Previous month"

    elif range_param == "last_month":
        this_month_start = today.replace(day=1)
        last_month_start = previous_month_start(this_month_start)
        month_before_start = previous_month_start(last_month_start)

        start_dt = timezone.make_aware(datetime.combine(last_month_start, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(this_month_start, datetime.min.time()))

        prev_start_dt = timezone.make_aware(datetime.combine(month_before_start, datetime.min.time()))
        prev_end_dt = start_dt

        period_label = "Last month"
        comparison_label = "Month before"

    else:
        range_param = "today"

        start_dt = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now_dt

        prev_start_dt = start_dt - timedelta(days=1)
        prev_end_dt = end_dt - timedelta(days=1)

        period_label = "Today"
        comparison_label = "Yesterday"

    # =====================================================
    # TREND HELPER
    # =====================================================
    def build_trend(current_value, previous_value):
        current_value = current_value or 0
        previous_value = previous_value or 0

        diff = current_value - previous_value

        if previous_value > 0:
            percent = round((diff / previous_value) * 100, 1)
            label = f"{abs(percent)}%"
        elif current_value > 0:
            percent = 100
            label = "New"
        else:
            percent = 0
            label = "No change"

        if diff > 0:
            direction = "up"
        elif diff < 0:
            direction = "down"
        else:
            direction = "same"

        return {
            "current": current_value,
            "previous": previous_value,
            "diff": diff,
            "percent": percent,
            "label": label,
            "direction": direction,
        }

    # =====================================================
    # PROSPECTS
    # =====================================================
    prospects_current = Prospect.objects.filter(
        owner=user,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    ).count()

    prospects_previous = Prospect.objects.filter(
        owner=user,
        created_at__gte=prev_start_dt,
        created_at__lt=prev_end_dt,
    ).count()

    prospects_trend = build_trend(prospects_current, prospects_previous)

    active_pipeline_total = (
        Prospect.objects
        .filter(owner=user, status="ACTIVE")
        .exclude(stage__in=["WON", "LOST"])
        .count()
    )

    # =====================================================
    # NEW CLIENTS
    # =====================================================
    new_clients_current = Client.objects.filter(
        account_manager=user,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    ).count()

    new_clients_previous = Client.objects.filter(
        account_manager=user,
        created_at__gte=prev_start_dt,
        created_at__lt=prev_end_dt,
    ).count()

    new_clients_trend = build_trend(new_clients_current, new_clients_previous)

    active_clients_overall = Client.objects.filter(
        account_manager=user,
        status="ACTIVE",
    ).count()

    # =====================================================
    # CONVERSION RATE
    # =====================================================
    prospects_converted_current = Prospect.objects.filter(
        owner=user,
        client__isnull=False,
        updated_at__gte=start_dt,
        updated_at__lt=end_dt,
    ).count()

    if prospects_current > 0:
        conversion_rate = round((prospects_converted_current / prospects_current) * 100, 1)
    else:
        conversion_rate = 0

    # =====================================================
    # ORDERS
    # =====================================================
    orders_qs = (
        Order.objects
        .annotate(
            ts=Coalesce(
                "submitted_at",
                "approved_at",
                "reviewed_at",
                "updated_at",
                "order_date",
            )
        )
        .filter(
            created_by=user,
            ts__gte=start_dt,
            ts__lt=end_dt,
        )
    )

    previous_orders_qs = (
        Order.objects
        .annotate(
            ts=Coalesce(
                "submitted_at",
                "approved_at",
                "reviewed_at",
                "updated_at",
                "order_date",
            )
        )
        .filter(
            created_by=user,
            ts__gte=prev_start_dt,
            ts__lt=prev_end_dt,
        )
    )

    orders_closed_count = orders_qs.count()

    # =====================================================
    # ORDER TREND GRAPH
    # =====================================================
    day_counts = OrderedDict()

    day_cursor = start_dt.date()
    end_day = (end_dt - timedelta(seconds=1)).date()

    while day_cursor <= end_day:
        day_counts[day_cursor] = 0
        day_cursor += timedelta(days=1)

    for ts in orders_qs.values_list("ts", flat=True):
        if ts:
            order_day = ts.date()
            if order_day in day_counts:
                day_counts[order_day] += 1

    sales_labels = [d.strftime("%d %b") for d in day_counts.keys()]
    sales_data = list(day_counts.values())

    # =====================================================
    # INVOICES
    # =====================================================
    invoices_qs = Invoice.objects.filter(
        invoice_date__gte=start_dt.date(),
        invoice_date__lt=end_dt.date() + timedelta(days=1),
        client__account_manager=user,
    )

    previous_invoices_qs = Invoice.objects.filter(
        invoice_date__gte=prev_start_dt.date(),
        invoice_date__lt=prev_end_dt.date() + timedelta(days=1),
        client__account_manager=user,
    )

    current_clients_invoice_data = (
        invoices_qs
        .values("client_id", "client__name", "client__organization")
        .annotate(
            invoice_count=Count("id"),
            invoice_value=Coalesce(
                Sum("order_total_inc"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
    )

    previous_clients_invoice_data = (
        previous_invoices_qs
        .values("client_id")
        .annotate(
            invoice_count=Count("id"),
            invoice_value=Coalesce(
                Sum("order_total_inc"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
    )

    previous_client_map = {
        row["client_id"]: row
        for row in previous_clients_invoice_data
    }

    client_rows = []

    for row in current_clients_invoice_data:
        previous = previous_client_map.get(row["client_id"], {})

        invoice_count = row["invoice_count"] or 0
        previous_invoice_count = previous.get("invoice_count", 0) or 0

        invoice_value = row["invoice_value"] or Decimal("0.00")
        previous_invoice_value = previous.get("invoice_value", Decimal("0.00")) or Decimal("0.00")

        client_rows.append({
            "client_id": row["client_id"],
            "client_name": row["client__name"],
            "client_organization": row["client__organization"],
            "invoice_count": invoice_count,
            "invoice_value": invoice_value,
            "quantity_trend": build_trend(invoice_count, previous_invoice_count),
            "value_trend": build_trend(float(invoice_value), float(previous_invoice_value)),
        })

    top_clients_by_invoice_quantity = sorted(
        client_rows,
        key=lambda x: (x["invoice_count"], x["invoice_value"]),
        reverse=True,
    )[:5]

    top_clients_by_invoice_value = sorted(
        client_rows,
        key=lambda x: (x["invoice_value"], x["invoice_count"]),
        reverse=True,
    )[:5]

    # =====================================================
    # TOP PRODUCTS
    # =====================================================
    current_products_data = (
        OrderItem.objects
        .filter(order_id__in=orders_qs.values("id"))
        .values("product_id", "product_name")
        .annotate(
            quantity_sold=Coalesce(
                Sum("quantity"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
    )

    previous_products_data = (
        OrderItem.objects
        .filter(order_id__in=previous_orders_qs.values("id"))
        .values("product_id")
        .annotate(
            quantity_sold=Coalesce(
                Sum("quantity"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
    )

    previous_product_map = {
        row["product_id"]: row["quantity_sold"] or Decimal("0.00")
        for row in previous_products_data
    }

    product_rows = []

    for row in current_products_data:
        current_qty = row["quantity_sold"] or Decimal("0.00")
        previous_qty = previous_product_map.get(row["product_id"], Decimal("0.00"))

        product_rows.append({
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "quantity_sold": current_qty,
            "quantity_trend": build_trend(float(current_qty), float(previous_qty)),
        })

    top_products = sorted(
        product_rows,
        key=lambda x: x["quantity_sold"],
        reverse=True,
    )[:5]

    context = {
        "range": range_param,
        "period_label": period_label,
        "comparison_label": comparison_label,

        "prospects_trend": prospects_trend,
        "new_clients_trend": new_clients_trend,
        "conversion_rate": conversion_rate,
        "prospects_converted_current": prospects_converted_current,
        "active_clients_overall": active_clients_overall,
        "active_pipeline_total": active_pipeline_total,
        "orders_closed_count": orders_closed_count,

        "sales_labels": sales_labels,
        "sales_data": sales_data,

        "top_clients_by_invoice_quantity": top_clients_by_invoice_quantity,
        "top_clients_by_invoice_value": top_clients_by_invoice_value,
        "top_products": top_products,
    }

    return render(request, "sales/dashboard.html", context)


@login_required
def prospects(request):
    """
    Sales prospects pipeline:
    - GET: list prospects with search, stage filter, and status filter.
    - No sample filtering or sample stats.
    """

    qs = (
        Prospect.objects
        .select_related("owner")
    )

    # -------------------------------------------------
    # SEARCH
    # -------------------------------------------------
    q = (request.GET.get("q") or "").strip()

    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(organization__icontains=q)
            | Q(contact_name__icontains=q)
            | Q(notes__icontains=q)
            | Q(suburb__icontains=q)
            | Q(city__icontains=q)
        )

    # -------------------------------------------------
    # STAGE FILTER
    # -------------------------------------------------
    stage_filter = (request.GET.get("stage") or "").strip().upper()

    valid_stages = {
        code
        for code, _ in Prospect.STAGE_CHOICES
    }

    if stage_filter and stage_filter in valid_stages:
        qs = qs.filter(stage=stage_filter)

    # -------------------------------------------------
    # STATUS FILTER
    # -------------------------------------------------
    status_filter = (request.GET.get("status") or "").strip().upper()

    valid_statuses = {
        code
        for code, _ in Prospect.STATUS_CHOICES
    }

    if status_filter and status_filter in valid_statuses:
        qs = qs.filter(status=status_filter)

    # -------------------------------------------------
    # TOTAL AFTER FILTERS
    # -------------------------------------------------
    prospects_total = qs.count()

    # -------------------------------------------------
    # PIPELINE SUMMARY
    # -------------------------------------------------
    stage_label_map = dict(Prospect.STAGE_CHOICES)

    pipeline_raw = (
        qs.values("stage")
        .annotate(count=Count("id"))
        .order_by("stage")
    )

    pipeline_summary = [
        {
            "stage": row["stage"],
            "stage_label": stage_label_map.get(
                row["stage"],
                row["stage"],
            ),
            "count": row["count"],
        }
        for row in pipeline_raw
    ]

    # -------------------------------------------------
    # FINAL QUERYSET
    # -------------------------------------------------
    prospects_qs = (
        qs
        .order_by("-created_at")
        .distinct()
    )

    context = {
        "prospects": prospects_qs,
        "prospects_total": prospects_total,
        "pipeline_summary": pipeline_summary,
        "today": timezone.localdate(),
    }

    return render(
        request,
        "prospects/prospects.html",
        context,
    )


@login_required
def prospect_create(request):
    """
    Create a new prospect.

    - Sets owner and created_by to the current user
    - Saves ProspectOperatingHours correctly via ProspectForm.save()
    - Logs an initial ProspectUpdate entry
    """

    if request.method == "POST":
        form = ProspectForm(request.POST)

        if form.is_valid():

            # -----------------------------------
            # Set ownership BEFORE saving
            # -----------------------------------
            form.instance.owner = form.instance.owner or request.user
            form.instance.created_by = form.instance.created_by or request.user

            # Prevent accidental direct WON creation
            if form.instance.stage == "WON":
                form.instance.stage = "NEW"

            # -----------------------------------
            # Save through form so operating hours
            # and m2m fields are handled properly
            # -----------------------------------
            prospect = form.save()

            # Ensure ownership persisted
            if not prospect.owner_id or not prospect.created_by_id:
                prospect.owner = prospect.owner or request.user
                prospect.created_by = prospect.created_by or request.user
                prospect.save(update_fields=[
                    "owner",
                    "created_by",
                    "updated_at",
                ])

            # -----------------------------------
            # Log creation in timeline
            # -----------------------------------
            ProspectUpdate.objects.create(
                prospect=prospect,
                user=request.user,
                action_type="OTHER",
                outcome="OTHER",
                notes="Prospect created.",
                action_at=timezone.now(),
                old_stage=prospect.stage,
            )

            messages.success(
                request,
                "Prospect created successfully."
            )

            return redirect("sales:sales-prospects")

    else:
        form = ProspectForm(initial={
            "stage": "NEW",
            "status": "ACTIVE",
        })

    return render(
        request,
        "prospects/prospect_form.html",
        {
            "form": form,
        }
    )



@login_required
def prospect_detail(request, pk: int):
    """
    Single prospect view with:
    - pipeline progress bar
    - current stage + owner
    - activity timeline
    - data for the tabs on the detail page
    """
    # Load prospect + related objects efficiently
    prospect = get_object_or_404(
        Prospect.objects
        .select_related("owner", "client")          # owner + linked client
        .prefetch_related("updates__user"),         # all updates + who logged them
        pk=pk,
    )

    # Full timeline of updates, newest first (used in Contact / Site / Negotiation)
    updates = (
        prospect.updates
        .select_related("user")
        .order_by("-action_at", "-created_at")
    )

    # Timeline for the "Timeline" tab: oldest → newest
    updates_timeline = (
        prospect.updates
        .select_related("user")
        .order_by("action_at", "created_at")
    )

    # Generic form (if/when you use it)
    update_form = ProspectUpdateForm(current_stage=prospect.stage)

    # -------------------------------
    # Stage / pipeline progress data
    # -------------------------------
    stage_order = ["NEW", "CONTACTED", "SITE_VISIT", "NEGOTIATION", "WON"]
    stage_labels = dict(Prospect.STAGE_CHOICES)

    try:
        current_idx = stage_order.index(prospect.stage)
    except ValueError:
        current_idx = -1  # e.g. LOST

    max_idx = len(stage_order) - 1
    if current_idx >= 0 and max_idx > 0:
        progress_percent = int(round((current_idx / max_idx) * 100))
    else:
        progress_percent = 0

    stage_states = []
    for idx, code in enumerate(stage_order):
        label = stage_labels.get(code, code.title())
        if current_idx == -1:
            state = "pending"
        elif idx < current_idx:
            state = "done"
        elif idx == current_idx:
            state = "active"
        else:
            state = "pending"

        stage_states.append({
            "code": code,
            "label": label,
            "state": state,
        })

    # -------------------------------
    # Subsets for stage tabs
    # -------------------------------
    contact_updates = updates.filter(action_type__in=["CALL", "WHATSAPP", "EMAIL"])
    site_visit_updates = updates.filter(action_type__in=["VISIT", "SAMPLE"])
    negotiation_updates = updates.filter(action_type="NEGOTIATION")

    # -------------------------------
    # Reopen + button-enable logic
    # -------------------------------
    # Reopen allowed only when WON/LOST and not yet a client
    can_reopen = (prospect.stage in ["WON", "LOST"]) and (prospect.client is None)

    # Stage outcome buttons:
    # - Contact buttons active only while stage is NEW or CONTACTED and not closed
    # - Site-visit buttons active only while stage is SITE_VISIT and not closed
    # - Negotiation buttons active only while stage is NEGOTIATION and not closed
    can_use_contact_stage_buttons = (not prospect.is_closed) and (
        prospect.stage in ["NEW", "CONTACTED"]
    )
    can_use_site_visit_stage_buttons = (not prospect.is_closed) and (
        prospect.stage == "SITE_VISIT"
    )
    can_use_negotiation_stage_buttons = (not prospect.is_closed) and (
        prospect.stage == "NEGOTIATION"
    )

    context = {
        "prospect": prospect,
        "updates": updates,
        "updates_timeline": updates_timeline,
        "update_form": update_form,
        "stage_states": stage_states,
        "progress_percent": progress_percent,
        "today": timezone.localdate(),

        # subsets
        "contact_updates": contact_updates,
        "site_visit_updates": site_visit_updates,
        "negotiation_updates": negotiation_updates,

        # button flags
        "can_reopen": can_reopen,
        "can_use_contact_stage_buttons": can_use_contact_stage_buttons,
        "can_use_site_visit_stage_buttons": can_use_site_visit_stage_buttons,
        "can_use_negotiation_stage_buttons": can_use_negotiation_stage_buttons,
    }
    return render(request, "prospects/prospect_detail.html", context)


@login_required
def prospect_update_create(request, pk: int):
    """
    Handle 'Log activity' POST from the prospect detail page.

    - Uses ProspectUpdateForm for validation.
    - Delegates actual logging to prospect.log_update(...)
    - On success: redirect back to the prospect detail.
    - On validation error: re-render the detail page with form errors.
    """
    prospect = get_object_or_404(
        Prospect.objects
        .select_related("owner", "client")
        .prefetch_related("updates__user"),
        pk=pk,
    )

    # If someone hits this URL with GET, just bounce them back to detail
    if request.method != "POST":
        return redirect("sales:sales-prospect-detail", pk=prospect.pk)

    form = ProspectUpdateForm(request.POST, current_stage=prospect.stage)

    if form.is_valid():
        cd = form.cleaned_data

        # Use the helper on the model so all logging is consistent
        prospect.log_update(
            user=request.user,
            action_type=cd["action_type"],
            outcome=cd.get("outcome") or "",
            action_at=cd.get("action_at") or timezone.now(),
            new_stage=cd.get("new_stage") or None,
            notes=cd.get("notes") or "",
        )

        return redirect("sales:sales-prospect-detail", pk=prospect.pk)

    # -------------------------------
    # If we get here, form is invalid
    # -> re-render the detail page with errors
    # -------------------------------

    updates = (
        prospect.updates
        .select_related("user")
        .order_by("-action_at", "-created_at")
    )

    # Rebuild the same stage progress data used in prospect_detail
    stage_order = ["NEW", "CONTACTED", "SITE_VISIT", "NEGOTIATION", "WON"]
    stage_labels = dict(Prospect.STAGE_CHOICES)

    try:
        current_idx = stage_order.index(prospect.stage)
    except ValueError:
        current_idx = -1

    max_idx = len(stage_order) - 1
    if current_idx >= 0 and max_idx > 0:
        progress_percent = int(round((current_idx / max_idx) * 100))
    else:
        progress_percent = 0

    stage_states = []
    for idx, code in enumerate(stage_order):
        label = stage_labels.get(code, code.title())
        if current_idx == -1:
            state = "pending"
        elif idx < current_idx:
            state = "done"
        elif idx == current_idx:
            state = "active"
        else:
            state = "pending"

        stage_states.append(
            {
                "code": code,
                "label": label,
                "state": state,
            }
        )

    context = {
        "prospect": prospect,
        "updates": updates,
        "update_form": form,  # with errors
        "stage_states": stage_states,
        "progress_percent": progress_percent,
        "today": timezone.localdate(),
    }
    return render(request, "prospects/prospect_detail.html", context)


@login_required
def prospect_stage_action(request, pk: int):
    """
    Handle stage action buttons from the prospect detail page.

    Expected POST param: stage_action

    Actions:
      - CONTACT_PASS      -> move to CONTACTED
      - CONTACT_LOST      -> mark LOST (died in contact stage)
      - SITE_VISIT_PASS   -> move to SITE_VISIT
      - SITE_VISIT_LOST   -> LOST (died after visit)
      - NEGOTIATION_PASS  -> move to NEGOTIATION
      - NEGOTIATION_WON   -> WON
      - NEGOTIATION_LOST  -> LOST

    All actions:
      - create a ProspectUpdate (via prospect.log_update)
      - update Prospect.stage + last_contact_at
      - redirect back to the detail page
    """
    prospect = get_object_or_404(Prospect, pk=pk)

    if request.method != "POST":
        return redirect("sales:sales-prospect-detail", pk=pk)

    action = (request.POST.get("stage_action") or "").strip()
    now = timezone.now()

    # Helper that uses the model's log_update
    def log_stage(action_type, outcome, new_stage, notes):
        prospect.log_update(
            user=request.user,
            action_type=action_type,
            outcome=outcome,
            notes=notes,
            action_at=now,
            new_stage=new_stage,
            touch_last_contact=True,
        )

    # ------- map actions to stage changes -------

    if action == "CONTACT_PASS":
        log_stage(
            action_type="CALL",
            outcome="ANSWERED",
            new_stage="CONTACTED",
            notes="Passed contact stage (successful contact).",
        )

    elif action == "CONTACT_LOST":
        log_stage(
            action_type="CALL",
            outcome="DEAL_LOST",
            new_stage="LOST",
            notes="Marked lost during contact stage.",
        )

    elif action == "SITE_VISIT_PASS":
        # Using SAMPLE as the unified code for site visit + samples
        log_stage(
            action_type="SAMPLE",
            outcome="FOLLOW_UP_AGREED",
            new_stage="SITE_VISIT",
            notes="Passed to site visit stage.",
        )

    elif action == "SITE_VISIT_LOST":
        log_stage(
            action_type="SAMPLE",
            outcome="DEAL_LOST",
            new_stage="LOST",
            notes="Marked lost after site visit.",
        )

    elif action == "NEGOTIATION_PASS":
        log_stage(
            action_type="NEGOTIATION",
            outcome="INTERESTED",
            new_stage="NEGOTIATION",
            notes="Moved into negotiation stage.",
        )

    elif action == "NEGOTIATION_WON":
        log_stage(
            action_type="NEGOTIATION",
            outcome="DEAL_WON",
            new_stage="WON",
            notes="Deal won at negotiation stage.",
        )

    elif action == "NEGOTIATION_LOST":
        log_stage(
            action_type="NEGOTIATION",
            outcome="DEAL_LOST",
            new_stage="LOST",
            notes="Marked lost at negotiation stage.",
        )

    # If unknown action, just go back without doing anything
    return redirect("sales:sales-prospect-detail", pk=pk)

@login_required
def prospect_edit(request, pk: int):
    """
    Edit an existing prospect.

    Uses ProspectForm so:
    - operating hours save correctly
    - categories save correctly
    - delivery slots save correctly

    Does NOT change:
    - owner
    - created_by
    """

    prospect = get_object_or_404(
        Prospect.objects.select_related(
            "owner",
            "client",
        ).prefetch_related(
            "categories",
        ),
        pk=pk,
    )

    if request.method == "POST":

        # Capture original stage BEFORE save
        original_stage = prospect.stage

        form = ProspectForm(
            request.POST,
            instance=prospect,
        )

        if form.is_valid():

            # -----------------------------------
            # Save through form
            # (important for operating hours)
            # -----------------------------------
            updated_prospect = form.save()

            # -----------------------------------
            # Log stage changes
            # -----------------------------------
            if original_stage != updated_prospect.stage:

                ProspectUpdate.objects.create(
                    prospect=updated_prospect,
                    user=request.user,
                    action_type="OTHER",
                    outcome="OTHER",
                    notes=(
                        f"Prospect stage changed from "
                        f"{original_stage} to "
                        f"{updated_prospect.stage}."
                    ),
                    action_at=timezone.now(),
                    old_stage=original_stage,
                    new_stage=updated_prospect.stage,
                )

            messages.success(
                request,
                "Prospect info updated successfully."
            )

            return redirect(
                "sales:sales-prospect-detail",
                pk=updated_prospect.pk
            )

        messages.error(
            request,
            "Please fix the errors below."
        )

    else:

        form = ProspectForm(
            instance=prospect,
        )

    context = {
        "form": form,
        "prospect": prospect,
    }

    return render(
        request,
        "prospects/prospect_form.html",
        context,
    )


@login_required
def prospect_contact_log(request, pk: int):
    """
    Log a contact-stage interaction (call / WhatsApp / etc.).
    Moves NEW -> CONTACTED automatically on first successful contact.
    """
    prospect = get_object_or_404(Prospect, pk=pk)

    if request.method != "POST":
        return redirect("sales:sales-prospect-detail", pk=pk)

    outcome = (request.POST.get("outcome") or "").strip()
    # we used a single datetime field in the form called contact_datetime
    contact_dt_str = (request.POST.get("contact_datetime") or "").strip()
    notes = (request.POST.get("notes") or "").strip()

    # parse contact datetime
    action_at = timezone.now()
    if contact_dt_str:
        try:
            naive_dt = datetime.fromisoformat(contact_dt_str)
            action_at = timezone.make_aware(naive_dt) if timezone.is_naive(naive_dt) else naive_dt
        except ValueError:
            pass

    # Decide if we should move the stage to CONTACTED
    new_stage = None
    if prospect.stage == "NEW":
        new_stage = "CONTACTED"

    # Use the helper on the model for consistency
    prospect.log_update(
        user=request.user,
        action_type="CALL",
        outcome=outcome,
        notes=notes,
        action_at=action_at,
        new_stage=new_stage,
    )

    messages.success(request, "Contact update logged.")
    return redirect("sales:sales-prospect-detail", pk=pk)


@login_required
def prospect_site_visit_log(request, pk: int):
    """
    Log a site visit update for a prospect.
    Captures:
      - visit date
      - time arrived / time left
      - contact person met
      - notes
      - optional photo
    Also moves stage to SITE_VISIT (from NEW/CONTACTED) if appropriate.
    """
    prospect = get_object_or_404(Prospect, pk=pk)

    if request.method != "POST":
        return redirect("sales:sales-prospect-detail", pk=pk)

    visit_date_str = (request.POST.get("visit_date") or "").strip()
    time_arrived_str = (request.POST.get("visit_time_arrived") or "").strip()
    time_left_str = (request.POST.get("visit_time_left") or "").strip()
    visit_contact_name = (request.POST.get("visit_contact_name") or "").strip()
    visit_notes = (request.POST.get("visit_notes") or "").strip()
    outcome = (request.POST.get("outcome") or "").strip()

    visit_photo = request.FILES.get("visit_photo")

    # Build action_at from visit_date + time_arrived if possible
    action_at = timezone.now()
    if visit_date_str:
        # if no time, default to 09:00
        if not time_arrived_str:
            time_arrived_str = "09:00"
        try:
            naive_dt = datetime.fromisoformat(f"{visit_date_str}T{time_arrived_str}")
            action_at = timezone.make_aware(naive_dt) if timezone.is_naive(naive_dt) else naive_dt
        except ValueError:
            pass

    # Stage transition: if still NEW/CONTACTED, push to SITE_VISIT
    old_stage = prospect.stage
    new_stage = old_stage
    if old_stage in ["NEW", "CONTACTED"]:
        new_stage = "SITE_VISIT"

    # Create the update with the extra site-visit fields
    update = ProspectUpdate.objects.create(
        prospect=prospect,
        user=request.user,
        action_type="VISIT",
        outcome=outcome,
        action_at=action_at,
        old_stage=old_stage,
        new_stage=new_stage,
        notes=visit_notes,
        visit_date=visit_date_str or None,
        visit_time_arrived=time_arrived_str or None,
        visit_time_left=time_left_str or None,
        visit_contact_name=visit_contact_name,
        visit_photo=visit_photo,
    )

    # Update prospect stage and last_contact_at if changed
    prospect.stage = new_stage
    prospect.last_contact_at = action_at
    prospect.save(update_fields=["stage", "last_contact_at", "updated_at"])

    messages.success(request, "Site visit logged.")
    return redirect("sales:sales-prospect-detail", pk=pk)


@login_required
def prospect_negotiation_log(request, pk: int):
    """
    Log a negotiation update:
      - outcome
      - date
      - products they want now
      - future menu opportunities
      - competitor info
      - extra notes
    Typically ensures stage is NEGOTIATION (unless already WON/LOST).
    """
    prospect = get_object_or_404(Prospect, pk=pk)

    if request.method != "POST":
        return redirect("sales:sales-prospect-detail", pk=pk)

    outcome = (request.POST.get("outcome") or "").strip()
    negotiation_date_str = (request.POST.get("negotiation_date") or "").strip()

    products_now = (request.POST.get("negotiation_products") or "").strip()
    menu_ops = (request.POST.get("negotiation_menu_opportunities") or "").strip()
    competitor_info = (request.POST.get("negotiation_competitor_info") or "").strip()
    notes = (request.POST.get("negotiation_notes") or "").strip()

    # Build action_at from negotiation_date
    action_at = timezone.now()
    if negotiation_date_str:
        try:
            # date only -> default time 10:00
            naive_dt = datetime.fromisoformat(f"{negotiation_date_str}T10:00")
            action_at = timezone.make_aware(naive_dt) if timezone.is_naive(naive_dt) else naive_dt
        except ValueError:
            pass

    old_stage = prospect.stage
    new_stage = old_stage
    if old_stage not in ["WON", "LOST"]:
        new_stage = "NEGOTIATION"

    update = ProspectUpdate.objects.create(
        prospect=prospect,
        user=request.user,
        action_type="NEGOTIATION",
        outcome=outcome,
        action_at=action_at,
        old_stage=old_stage,
        new_stage=new_stage,
        notes=notes,
        negotiation_products=products_now,
        negotiation_menu_opportunities=menu_ops,
        negotiation_competitor_info=competitor_info,
    )

    prospect.stage = new_stage
    prospect.last_contact_at = action_at
    prospect.save(update_fields=["stage", "last_contact_at", "updated_at"])

    messages.success(request, "Negotiation update logged.")
    return redirect("sales:sales-prospect-detail", pk=pk)

@login_required
def prospect_reopen(request, pk: int):
    """
    Re-open a previously closed prospect (WON or LOST).

    - Sets stage back to CONTACTED (or NEW, if you prefer)
    - Logs a ProspectUpdate entry so the timeline is accurate
    - Leaves created_at as original (so age_days & SLA still reflect reality)
    """
    prospect = get_object_or_404(Prospect, pk=pk)

    if request.method != "POST":
        # Only allow POST (from the button in the detail page)
        return redirect("sales:sales-prospect-detail", pk=pk)

    # If it's already open, just ignore and go back
    if not prospect.is_closed:
        messages.info(request, "This prospect is already open.")
        return redirect("sales:sales-prospect-detail", pk=pk)

    old_stage = prospect.stage
    new_stage = "CONTACTED"  # you could change this to "NEW" if you prefer
    now = timezone.now()

    # If you want to go through the helper on the model:
    prospect.log_update(
        user=request.user,
        action_type="OTHER",
        outcome="INTERESTED",
        notes="Prospect reopened after previous decision.",
        action_at=now,
        new_stage=new_stage,
    )

    messages.success(request, "Prospect has been reopened and moved to Contacted.")
    return redirect("sales:sales-prospect-detail", pk=pk)

# -------------------------------------------------------------------
# Placeholder views for other sales sections (can be filled in later)
# -------------------------------------------------------------------
@login_required
def clients(request):
    qs = (Client.objects
          .select_related("account_manager")
          .prefetch_related("categories")
          .order_by("name"))

    # Dropdown data (pulled from model choices so it stays in sync)
    client_types = Client.CLIENT_TYPES
    provinces = Client.PROVINCES
    account_types = Client.ACCOUNT_TYPES
    credit_statuses = Client.CREDIT_STATUS
    statuses = Client.STATUS
    filter_categories = Category.objects.filter(is_active=True).order_by("name")

    # GET params
    search = (request.GET.get("search") or "").strip()
    client_type = request.GET.get("client_type") or ""
    province = request.GET.get("province") or ""
    account_type = request.GET.get("account_type") or ""
    credit_status = request.GET.get("credit_status") or ""
    status = request.GET.get("status") or ""
    category_id = request.GET.get("category") or ""

    # Search
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(organization__icontains=search) |
            Q(contact_person__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search) |
            Q(whatsapp__icontains=search) |
            Q(suburb__icontains=search) |
            Q(city__icontains=search)
        )

    # Filters
    if client_type:
        qs = qs.filter(client_type=client_type)
    if province:
        qs = qs.filter(province=province)
    if account_type:
        qs = qs.filter(account_type=account_type)
    if credit_status:
        qs = qs.filter(credit_status=credit_status)
    if status:
        qs = qs.filter(status=status)
    if category_id.isdigit():
        qs = qs.filter(categories__id=int(category_id))

    clients = qs.distinct()

    return render(request, "clients/clients.html", {
        "clients": clients,
        "filter_categories": filter_categories,
        "client_types": client_types,
        "provinces": provinces,
        "account_types": account_types,
        "credit_statuses": credit_statuses,
        "statuses": statuses,
    })
    


def view_client(request, pk):
    # ---------------------------
    # Core client
    # ---------------------------
    client = get_object_or_404(
        Client.objects
        .select_related("account_manager", "funder")
        .prefetch_related("categories"),
        pk=pk
    )

    # ---------------------------
    # Orders (tab)
    # ---------------------------
    orders = (
        Order.objects
        .filter(client=client)
        .only("id", "order_date", "status", "grand_total_inc")
        .order_by("-order_date")[:10]
    )

    # ---------------------------
    # Credit (tab)
    # ---------------------------
    credit_account = None
    credit_utilization_pct = None
    credit_utilization_status = None

    if client.account_type == "CREDIT":
        credit_account = CreditAccount.objects.filter(client=client).first()

        if credit_account and credit_account.credit_limit > 0:
            credit_utilization_pct = (
                credit_account.credit_used / credit_account.credit_limit
            ) * Decimal("100.00")

            if credit_utilization_pct < 50:
                credit_utilization_status = "Healthy"
            elif credit_utilization_pct < 80:
                credit_utilization_status = "Watch"
            elif credit_utilization_pct <= 100:
                credit_utilization_status = "High Risk"
            else:
                credit_utilization_status = "Over Limit"

    # ---------------------------
    # Compliance (tab)
    # ---------------------------
    compliance = getattr(client, "compliance", None)

    compliance_documents = []
    compliance_completion_pct = Decimal("0.00")

    if compliance:
        compliance_documents = (
            compliance.documents
            .all()
            .order_by("document_type")
        )

        total_docs = compliance_documents.count()

        approved_docs = compliance_documents.filter(
            status="APPROVED"
        ).count()

        if total_docs > 0:
            compliance_completion_pct = (
                Decimal(approved_docs) / Decimal(total_docs)
            ) * Decimal("100.00")

    # ---------------------------
    # Overview KPIs
    # ---------------------------
    total_spend = (
        Order.objects
        .filter(client=client)
        .aggregate(
            s=Coalesce(Sum("grand_total_inc"), Decimal("0.00"))
        )["s"]
    )

    days_active = (
        timezone.now().date() - client.created_at.date()
    ).days

    # ---------------------------
    # Spend Rank
    # ---------------------------
    ranked_clients = (
        Client.objects
        .annotate(
            total_spend=Coalesce(
                Sum("orders__grand_total_inc"),
                Decimal("0.00")
            )
        )
        .order_by("-total_spend", "id")
        .values_list("id", flat=True)
    )

    ranked_ids = list(ranked_clients)
    total_clients = len(ranked_ids)

    spend_rank = (
        ranked_ids.index(client.id) + 1
        if client.id in ranked_ids
        else None
    )

    # ---------------------------
    # Context
    # ---------------------------
    context = {
        "client": client,

        # Overview KPIs
        "days_active": days_active,
        "total_spend": total_spend,
        "spend_rank": spend_rank,
        "total_clients": total_clients,

        # Orders
        "orders": orders,

        # Credit
        "credit_account": credit_account,
        "credit_utilization_pct": credit_utilization_pct,
        "credit_utilization_status": credit_utilization_status,

        # Compliance
        "compliance": compliance,
        "compliance_documents": compliance_documents,
        "compliance_completion_pct": compliance_completion_pct,

        # UI feedback
        "success_message": request.GET.get("ok", ""),
        "error_message": request.GET.get("err", ""),
    }

    return render(
        request,
        "clients/client_detail.html",
        context
    )



def edit_client(request, pk):
    # Fetch client with related objects efficiently
    client = get_object_or_404(
        Client.objects.select_related("account_manager")
                      .prefetch_related("categories"),
        pk=pk
    )

    original_status = client.status  # capture status before changes

    if request.method == "POST":
        form = ClientEditForm(request.POST, instance=client)

        if form.is_valid():
            with transaction.atomic():
                updated_client = form.save()

                # 1️⃣ Close the latest task associated with this client
                content_type = ContentType.objects.get_for_model(updated_client)
                latest_task = Task.objects.filter(
                    content_type=content_type,
                    object_id=updated_client.id
                ).order_by("-created_at").first()

                if latest_task:
                    latest_task.status = Task.Status.CLOSED
                    latest_task.completed_at = timezone.now()
                    latest_task.save(update_fields=["status", "completed_at", "updated_at"])

                # 2️⃣ Send client status change email
                customer_profile = updated_client.customer_profiles.select_related("user").first()
                user = getattr(customer_profile, "user", None)

                if user and user.email and original_status != updated_client.status:
                    if original_status == "PENDING" and updated_client.status == "ACTIVE":
                        send_email_pending_to_active(updated_client, user)
                    elif original_status == "ACTIVE" and updated_client.status == "INACTIVE":
                        send_email_active_to_inactive(updated_client, user)
                    elif original_status == "INACTIVE" and updated_client.status == "ACTIVE":
                        send_email_inactive_to_active(updated_client, user)

            messages.success(request, "Client updated successfully.")
            return redirect("client-view", pk=updated_client.pk)

        messages.error(request, "Please fix the errors below.")
    else:
        form = ClientEditForm(instance=client)

    return render(request, "clients/edit_client.html", {"form": form, "client": client})


@login_required
def quotations(request):

    qs = (
        Quotation.objects
        .select_related(
            "client",
            "prospect",
            "created_by",
            "accepted_by",
            "converted_order",
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    # -------------------------------------------------
    # FILTER DROPDOWNS
    # -------------------------------------------------

    statuses = Quotation.STATUS_CHOICES

    # -------------------------------------------------
    # GET PARAMS
    # -------------------------------------------------

    search = (request.GET.get("search") or "").strip()

    status = request.GET.get("status") or ""

    has_order = request.GET.get("has_order") or ""

    target_type = request.GET.get("target_type") or ""

    created_by = request.GET.get("created_by") or ""

    # -------------------------------------------------
    # SEARCH
    # -------------------------------------------------

    if search:

        qs = qs.filter(

            Q(id__icontains=search) |

            Q(client__name__icontains=search) |
            Q(client__organization__icontains=search) |
            Q(client__contact_person__icontains=search) |
            Q(client__email__icontains=search) |
            Q(client__phone__icontains=search) |

            Q(prospect__name__icontains=search) |
            Q(prospect__organization__icontains=search) |
            Q(prospect__email__icontains=search) |
            Q(prospect__phone__icontains=search)

        )

    # -------------------------------------------------
    # STATUS
    # -------------------------------------------------

    if status:
        qs = qs.filter(status=status)

    # -------------------------------------------------
    # HAS CONVERTED ORDER
    # -------------------------------------------------

    if has_order == "yes":
        qs = qs.filter(converted_order__isnull=False)

    elif has_order == "no":
        qs = qs.filter(converted_order__isnull=True)

    # -------------------------------------------------
    # TARGET TYPE
    # -------------------------------------------------

    if target_type == "client":
        qs = qs.filter(client__isnull=False)

    elif target_type == "prospect":
        qs = qs.filter(prospect__isnull=False)

    # -------------------------------------------------
    # CREATED BY
    # -------------------------------------------------

    if created_by.isdigit():
        qs = qs.filter(created_by_id=int(created_by))

    # -------------------------------------------------
    # FINAL DISTINCT
    # -------------------------------------------------

    quotations = qs.distinct()

    return render(request, "quotations/quotations.html", {

        "quotations": quotations,

        "statuses": statuses,

        "selected_status": status,
        "selected_has_order": has_order,
        "selected_target_type": target_type,
        "selected_created_by": created_by,
        "search": search,

    })
    



class QuotationCreateForm(forms.ModelForm):
    quotation_for = forms.ChoiceField(
        choices=[
            ("client", "Existing Client"),
            ("prospect", "Prospect"),
        ],
        widget=forms.RadioSelect,
        initial="client",
        required=True,
    )

    class Meta:
        model = Quotation
        fields = [
            "quotation_for",
            "client",
            "prospect",
            "customer_notes",
        ]

        widgets = {
            "client": forms.Select(attrs={"class": "form-select"}),
            "prospect": forms.Select(attrs={"class": "form-select"}),
            "customer_notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["client"].queryset = (
            Client.objects
            .filter(status="ACTIVE")
            .order_by("name")
        )

        self.fields["prospect"].queryset = (
            Prospect.objects
            .filter(client__isnull=True)
            .exclude(stage="WON")
            .order_by("name")
        )

        self.fields["client"].required = False
        self.fields["prospect"].required = False

    def clean(self):
        cleaned_data = super().clean()

        quotation_for = cleaned_data.get("quotation_for")
        client = cleaned_data.get("client")
        prospect = cleaned_data.get("prospect")

        if quotation_for == "client":
            if not client:
                raise forms.ValidationError("Please select an existing client.")
            cleaned_data["prospect"] = None

        elif quotation_for == "prospect":
            if not prospect:
                raise forms.ValidationError("Please select a prospect.")
            cleaned_data["client"] = None

        return cleaned_data


class QuotationItemForm(forms.ModelForm):
    class Meta:
        model = QuotationItem
        fields = [
            "category",
            "product",
            "quantity",
            "unit_price_excl",
            "discount_excl",
            "vat_percent",
        ]

        widgets = {
            "category": forms.Select(attrs={"class": "form-select quotation-category"}),
            "product": forms.Select(attrs={"class": "form-select quotation-product"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "unit_price_excl": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "discount_excl": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "vat_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}),
        }


QuotationItemFormSet = inlineformset_factory(
    parent_model=Quotation,
    model=QuotationItem,
    form=QuotationItemForm,
    fields=[
        "category",
        "product",
        "quantity",
        "unit_price_excl",
        "discount_excl",
        "vat_percent",
    ],
    extra=0,
    can_delete=True,
    validate_min=True,
    min_num=1,
)


@login_required
def create_quotation(request):

    if request.method == "POST":

        form = QuotationCreateForm(request.POST)

        formset = QuotationItemFormSet(
            request.POST,
            prefix="items"
        )

        if form.is_valid() and formset.is_valid():

            try:
                with transaction.atomic():

                    quotation = form.save(commit=False)

                    quotation.created_by = request.user
                    quotation.status = "draft"
                    quotation.quotation_date = timezone.now()
                    quotation.valid_until = (
                        timezone.now() + timedelta(hours=72)
                    ).date()

                    quotation.save()

                    items = formset.save(commit=False)

                    for item in items:
                        item.quotation = quotation
                        item.save()

                    for deleted in formset.deleted_objects:
                        deleted.delete()

                    quotation.recalc_totals(save=True)

                messages.success(
                    request,
                    f"Quotation #{quotation.id} created."
                )

                return redirect(
                    "sales:sales-view-quotation",
                    pk=quotation.id
                )

            except Exception as e:
                messages.error(
                    request,
                    f"Quotation could not be created: {e}"
                )

        else:
            messages.error(
                request,
                "Please correct the errors below."
            )

    else:
        form = QuotationCreateForm()

        formset = QuotationItemFormSet(
            prefix="items"
        )

    return render(
        request,
        "quotations/create_quotation.html",
        {
            "form": form,
            "formset": formset,
            "prefix": "items",
        },
    )


@login_required
def edit_quotation(request, pk):

    quotation = get_object_or_404(
        Quotation.objects.prefetch_related("items"),
        pk=pk,
    )

    # -----------------------------------
    # LOCKED CHECK
    # -----------------------------------
    locked_statuses = [
        "accepted",
        "rejected",
        "expired",
    ]

    if quotation.status in locked_statuses:
        messages.warning(
            request,
            "This quotation is locked and can no longer be edited."
        )

        return redirect(
            "sales:sales-view-quotation",
            pk=quotation.id,
        )

    if request.method == "POST":

        form = QuotationCreateForm(
            request.POST,
            instance=quotation,
        )

        formset = QuotationItemFormSet(
            request.POST,
            instance=quotation,
            prefix="items",
        )

        if form.is_valid() and formset.is_valid():

            try:

                with transaction.atomic():

                    quotation = form.save(commit=False)
                    quotation.save()

                    items = formset.save(commit=False)

                    for item in items:
                        item.quotation = quotation
                        item.save()

                    for deleted in formset.deleted_objects:
                        deleted.delete()

                    quotation.recalc_totals(save=True)

                messages.success(
                    request,
                    f"Quotation #{quotation.id} updated successfully."
                )

                return redirect(
                    "sales:sales-view-quotation",
                    pk=quotation.id,
                )

            except Exception as e:

                messages.error(
                    request,
                    f"Quotation could not be updated: {e}"
                )

        else:

            messages.error(
                request,
                "Please correct the errors below."
            )

    else:

        form = QuotationCreateForm(instance=quotation)

        if quotation.client:
            form.initial["quotation_for"] = "client"

        elif quotation.prospect:
            form.initial["quotation_for"] = "prospect"

        formset = QuotationItemFormSet(
            instance=quotation,
            prefix="items",
        )

    return render(
        request,
        "quotations/create_quotation.html",
        {
            "form": form,
            "formset": formset,
            "quotation": quotation,
            "is_edit": True,
        },
    )


@login_required
@require_POST
def send_quotation_whatsapp_view(request, pk):

    quotation = get_object_or_404(
        Quotation.objects.select_related(
            "client",
            "prospect",
        ),
        pk=pk,
    )

    recipient = quotation.client or quotation.prospect

    if not recipient:
        return JsonResponse({
            "success": False,
            "error": "No client/prospect found."
        }, status=400)

    phone = (
        request.POST.get("phone")
        or getattr(recipient, "phone", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "error": "No WhatsApp number found."
        }, status=400)

    phone = (
        phone
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )

    client_name = (
        getattr(recipient, "organization", None)
        or getattr(recipient, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/orders/q/"
        f"{quotation.public_token}/"
    )

    result = send_quotation_whatsapp(
        to=phone,
        client_name=client_name,
        quotation_number=f"QT-{quotation.id}",
        amount=quotation.grand_total_inc,
        link=link,
        quotation=quotation,
    )

    if not result.get("messages"):

        error_message = (
            result.get("error", {})
            .get("message", "Unknown WhatsApp error")
        )

        CommunicationLog.objects.create(
            channel=CommunicationLog.CHANNEL_WHATSAPP,
            status=CommunicationLog.STATUS_FAILED,
            recipient_name=client_name,
            recipient_contact=phone,
            subject=f"Quotation QT-{quotation.id}",
            message=f"Failed WhatsApp quotation send.\nQuotation ID: {quotation.id}\nLink: {link}",
            related_model="Quotation",
            related_object_id=quotation.id,
            provider="Meta WhatsApp Cloud API",
            provider_response=result,
            error_message=error_message,
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "error": error_message,
            "result": result,
        }, status=400)

    message_id = result["messages"][0].get("id")

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_WHATSAPP,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Quotation QT-{quotation.id}",
        message=f"Quotation sent via WhatsApp.\nQuotation ID: {quotation.id}\nLink: {link}",
        related_model="Quotation",
        related_object_id=quotation.id,
        provider="Meta WhatsApp Cloud API",
        provider_message_id=message_id,
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    quotation.status = "sent"

    quotation.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return JsonResponse({
        "success": True,
        "message": "Quotation sent successfully.",
        "whatsapp_message_id": message_id,
        "result": result,
    })


@login_required
def view_quotation(request, pk):

    quotation = get_object_or_404(
        Quotation.objects
        .select_related(
            "client",
            "prospect",
            "created_by",
            "accepted_by",
            "converted_order",
        )
        .prefetch_related(
            "items__product",
            "items__category",
        ),
        pk=pk,
    )

    quotation.recalc_totals(save=False)

    item_rows = []

    for item in quotation.items.all().order_by("id"):

        qty = item.quantity or Decimal("0.00")
        unit_excl = item.unit_price_excl or Decimal("0.00")
        discount_per_unit = item.discount_excl or Decimal("0.00")
        vat_pct = item.vat_percent or Decimal("0.00")

        gross_excl = unit_excl * qty
        discount_total = discount_per_unit * qty
        line_excl = gross_excl - discount_total
        vat_amount = line_excl * (vat_pct / Decimal("100.00"))
        line_inc = line_excl + vat_amount

        discount_pct = Decimal("0.00")

        if unit_excl > 0 and discount_per_unit > 0:
            discount_pct = (discount_per_unit / unit_excl) * Decimal("100.00")

        item_rows.append({
            "item": item,
            "qty": qty,
            "unit_excl": unit_excl,
            "discount_per_unit": discount_per_unit,
            "discount_total": discount_total,
            "discount_pct": discount_pct,
            "vat_pct": vat_pct,
            "line_excl": line_excl,
            "vat_amount": vat_amount,
            "line_inc": line_inc,
        })

    return render(
        request,
        "quotations/view_quotation.html",
        {
            "quotation": quotation,
            "item_rows": item_rows,
        },
    )





def send_email_pending_to_active(client, user):
    subject = "The Daily Market – Your account is now active"

    ctx = {
        "user": user,
        "client": client,
        "login_url": reverse("client-login"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
    }

    text_body = render_to_string(
        "email/client_pending_to_active.txt", ctx
    )
    html_body = render_to_string(
        "email/client_pending_to_active.html", ctx
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


def send_email_active_to_inactive(client, user):
    subject = "The Daily Market – Your account is now inactive"

    ctx = {
        "user": user,
        "client": client,
        "login_url": reverse("client-login"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
    }

    text_body = render_to_string(
        "email/client_active_to_inactive.txt", ctx
    )
    html_body = render_to_string(
        "email/client_active_to_inactive.html", ctx
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



def send_email_inactive_to_active(client, user):
    subject = "The Daily Market – Your account is now active"

    ctx = {
        "user": user,
        "client": client,
        "login_url": reverse("client-login"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
    }

    text_body = render_to_string(
        "email/client_inactive_to_active.txt", ctx
    )
    html_body = render_to_string(
        "email/client_inactive_to_active.html", ctx
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



class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            # Identity & Ownership
            "name", "organization", "client_type", "account_manager",
            "price_type",  # <-- added
            # Contact
            "contact_person", "email", "phone", "whatsapp",
            # Address
            "address_line1", "address_line2", "suburb", "city", "province",
            "postal_code", "country",
            # Compliance
            "vat_number", "registration_identifier",
            # Categorisation & Account
            "categories", "status", "account_type", "credit_status",
            # Spend & Notes
            "estimated_weekly_spend", "notes",
        ]
        widgets = {
            # text inputs
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "organization": forms.TextInput(attrs={"class": "form-control"}),
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "whatsapp": forms.TextInput(attrs={"class": "form-control"}),
            "address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "suburb": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "vat_number": forms.TextInput(attrs={"class": "form-control"}),
            "registration_identifier": forms.TextInput(attrs={"class": "form-control"}),
            "estimated_weekly_spend": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            # selects
            "client_type": forms.Select(attrs={"class": "form-select"}),
            "account_manager": forms.Select(attrs={"class": "form-select"}),
            "province": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "account_type": forms.Select(attrs={"class": "form-select"}),
            "credit_status": forms.Select(attrs={"class": "form-select"}),
            "price_type": forms.Select(attrs={"class": "form-select"}),  # <-- added
            # many-to-many
            "categories": forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only active categories in a nice order
        self.fields["categories"].queryset = Category.objects.filter(is_active=True).order_by("name")

        # Placeholders
        self.fields["email"].widget.attrs.setdefault("placeholder", "name@example.com")
        self.fields["phone"].widget.attrs.setdefault("placeholder", "e.g. 072 123 4567")
        self.fields["whatsapp"].widget.attrs.setdefault("placeholder", "e.g. 072 123 4567")

        # Optional: default to Retail if none chosen yet
        if not self.instance.pk and not self.initial.get("price_type"):
            self.fields["price_type"].initial = "Retail"


@login_required
def orders(request):
    qs = (
        Order.objects
        .select_related("client")
        .prefetch_related("items")
    )

    # Optional filters
    status = request.GET.get("status")
    channel = request.GET.get("channel")
    q = request.GET.get("q")

    if status:
        qs = qs.filter(status=status)
    if channel:
        qs = qs.filter(channel=channel)
    if q:
        qs = qs.filter(
            Q(client__name__icontains=q) |
            Q(client__organization__icontains=q) |
            Q(customer_notes__icontains=q) |
            Q(notes__icontains=q)
        )

    # Safe decimal fallbacks
    ZERO_DEC = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))
    ZERO_INT = Value(0, output_field=IntegerField())

    # A computed fallback for total (inc) if grand_total_inc is 0.00
    computed_total_fallback = ExpressionWrapper(
        Coalesce(F("subtotal_excl"), ZERO_DEC) +
        Coalesce(F("vat_total"), ZERO_DEC) +
        Coalesce(F("delivery_fee_excl"), ZERO_DEC),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    qs = qs.annotate(
        total_quantity=Coalesce(Sum("items__quantity"), ZERO_DEC, output_field=DecimalField(max_digits=12, decimal_places=2)),
        item_count=Coalesce(Count("items", distinct=True), ZERO_INT, output_field=IntegerField()),
        total_amount=Coalesce(
            F("grand_total_inc"),
            computed_total_fallback,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    ).order_by("-submitted_at").distinct()

    return render(request, "orders/orders.html", {
        "orders": qs,
        "filter_status": status or "",
        "filter_channel": channel or "",
        "search": q or "",
    })


class OrderForm(ModelForm):
    class Meta:
        model = Order
        fields = [
            "client",
            "order_date",
            "channel",
            "status",
            "customer_notes",
            "discount_total_excl",
            "delivery_fee_excl",
            "delivery_fee_vat_percent",
            "notes",
        ]
        widgets = {
            "client": widgets.Select(attrs={"class": "form-select"}),
            "order_date": widgets.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "channel": widgets.Select(attrs={"class": "form-select"}),
            "status": widgets.Select(attrs={"class": "form-select"}),
            "customer_notes": widgets.Textarea(attrs={"class": "form-control", "rows": 3}),
            "discount_total_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "delivery_fee_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "delivery_fee_vat_percent": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}),
            "notes": widgets.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class OrderItemForm(ModelForm):
    class Meta:
        model = OrderItem
        fields = [
            "category",
            "product",
            "quantity",
            "unit_price_excl",
            "discount_excl",
            "vat_percent",
        ]
        widgets = {
            "category": widgets.Select(attrs={"class": "form-select"}),
            "product": widgets.Select(attrs={"class": "form-select"}),
            "quantity": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "unit_price_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "discount_excl": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "vat_percent": widgets.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "max": "100"}),
        }


OrderItemFormSet = inlineformset_factory(
    parent_model=Order,
    model=OrderItem,
    form=OrderItemForm,
    fields=["category", "product", "quantity", "unit_price_excl", "discount_excl", "vat_percent"],
    extra=0,               # rows added via JS using empty_form
    can_delete=True,
    validate_min=False,
    min_num=0,
)


# --- Views ---
@login_required
def create_order(request):
    """
    Create an order + items with dynamic add/remove via formset.
    """
    if request.method == "POST":
        form = OrderForm(request.POST)
        # validate items against a dummy instance; we’ll attach the saved order before saving items
        dummy_parent = Order()
        formset = OrderItemFormSet(request.POST, instance=dummy_parent, prefix="items")

        if form.is_valid() and formset.is_valid():
            order = form.save(commit=False)
            if request.user.is_authenticated:
                order.created_by = request.user
            order.save()

            formset.instance = order
            formset.save()

            # roll-up totals after items saved
            order.recalc_totals(save=True)

            messages.success(request, f"Order #{order.id} created.")
            return redirect("view-order", pk=order.id)
    else:
        form = OrderForm()
        formset = OrderItemFormSet(instance=Order(), prefix="items")  # empty; rows added with JS

    return render(
        request,
        "orders/create_order.html",
        {
            "form": form,
            "formset": formset,
            "prefix": "items",   # used by the template JS as a fallback
        },
    )


@login_required
def edit_order(request, pk):
    """
    Edit an order and its items.
    """
    order = get_object_or_404(
        Order.objects.select_related("client").prefetch_related("items__product", "items__category"),
        pk=pk,
    )

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(request.POST, instance=order, prefix="items")

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()

            # keep totals in sync
            order.recalc_totals(save=True)

            messages.success(request, f"Order #{order.id} updated.")
            return redirect("view-order", pk=order.id)
    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(instance=order, prefix="items")

    return render(
        request,
        "orders/edit_order.html",
        {
            "order": order,
            "form": form,
            "formset": formset,
            "prefix": "items",
        },
    )


@login_required
def view_order(request, pk):
    """
    Order detail view — shows order, items and related invoice (if any).
    Recalculates totals in-memory (no DB write) so displayed totals are fresh.
    """
    order = get_object_or_404(
        Order.objects
             .select_related("client", "created_by", "reviewed_by", "approved_by")
             .prefetch_related("items__product", "items__category"),
        pk=pk
    )

    # keep totals fresh (no DB write)
    # (assumes Order.recalc_totals(save=False) exists)
    try:
        order.recalc_totals(save=False)
    except Exception:
        # If recalc_totals doesn't exist or fails, we continue — it's not fatal for view rendering
        pass

    # invoice (if one-to-one exists)
    invoice = None
    try:
        invoice = order.invoice  # uses OneToOne relation if present
    except AttributeError:
        invoice = None
    except Exception:
        # fallback: if some other error occurs, don't crash the view
        invoice = None

    items = order.items.all().order_by("id")
    return render(request, "orders/view_order.html", {
        "order": order,
        "items": items,
        "invoice": invoice,
    })



@login_required
def delete_order(request, pk):
    """
    Delete an order only if the logged-in user's StaffProfile auth code matches
    the code typed into the confirmation modal. Uses StaffProfile.check_auth_code()
    if available; otherwise falls back to a plain string comparison (constant-time).
    """
    order = get_object_or_404(Order.objects.select_related("client"), pk=pk)

    if request.method != "POST":
        messages.error(request, "Please confirm deletion using the Delete button.")
        return redirect("view-order", pk=order.pk)

    auth_code = (request.POST.get("auth_code") or "").strip()
    if not auth_code:
        messages.error(request, "Authorisation code is required.")
        return redirect("view-order", pk=order.pk)

    profile = getattr(request.user, "staff_profile", None)
    if not profile:
        messages.error(
            request,
            "No staff profile found for your account. Ask an admin to set up your staff profile and authorisation code."
        )
        return redirect("view=order", pk=order.pk)

    # Validate the code
    is_valid = False
    # Preferred: secure check if your model provides it
    if hasattr(profile, "check_auth_code"):
        try:
            is_valid = profile.check_auth_code(auth_code)
        except Exception:
            is_valid = False
    else:
        # Fallback if you stored a plain code field named 'employee_auth_code'
        stored = getattr(profile, "employee_auth_code", "") or ""
        # constant-time compare
        is_valid = bool(stored) and hmac.compare_digest(stored, auth_code)

    if not is_valid:
        messages.error(request, "Invalid authorisation code.")
        return redirect("order-view", pk=order.pk)

    # All good – delete the order
    oid = order.pk
    client_label = str(order.client)
    try:
        with transaction.atomic():
            order.delete_with_audit(
            request=request,
            reason=request.POST.get("reason", ""),
            auth_verified=True,            # you already validated the staff code
            auth_method="staff_code",
        )

        messages.success(request, f"Order #{oid} ({client_label}) was deleted.")
        return redirect("staff-orders")
    except Exception as e:
        messages.error(request, f"Could not delete order: {e}")
        return redirect("order-view", pk=oid)
        order.delete



@login_required
def ajax_products_by_category(request):
    cat_id = request.GET.get("category_id")

    if not cat_id:
        return JsonResponse({"results": []})

    products = (
        Product.objects
        .filter(category_id=cat_id)
        .prefetch_related("pricing_rows")
        .order_by("name")
    )

    results = []

    for product in products:
        best_price_excl = None
        best_vat_percent = None

        active_pricing_rows = product.pricing_rows.filter(is_active=True)

        for pricing in active_pricing_rows:
            price_excl = pricing.wholesale_price_excl
            vat_percent = pricing.wholesale_vat_percent

            if price_excl is None or price_excl <= Decimal("0.00"):
                continue

            if best_price_excl is None or price_excl < best_price_excl:
                best_price_excl = price_excl
                best_vat_percent = vat_percent

        if best_price_excl is not None:
            vat_multiplier = Decimal("1.00") + (
                best_vat_percent / Decimal("100.00")
            )

            best_price_incl = (
                best_price_excl * vat_multiplier
            ).quantize(Decimal("0.01"))

            text = (
                f"{product.sku} · {product.name} "
                f"({product.uom}) — "
                f"R{best_price_excl:.2f} excl · "
                f"R{best_price_incl:.2f} incl"
            )
        else:
            text = (
                f"{product.sku} · {product.name} "
                f"({product.uom}) — No active price"
            )

        results.append({
            "id": product.id,
            "text": text,
            "price_excl": str(best_price_excl or Decimal("0.00")),
            "vat_percent": str(best_vat_percent or Decimal("0.00")),
        })

    return JsonResponse({"results": results})



@login_required
def invoices(request):
    """
    List invoices with optional filters:
      - q: search across client name, client organization, order CL number
      - status: invoice status (unpaid/partial/paid/overdue)
      - from / to: invoice_date range (YYYY-MM-DD)
      - page: paginator page
    """
    qs = Invoice.objects.select_related("client", "order").all().order_by("-invoice_date", "-created_at")

    # --- Filters from GET ---
    search = request.GET.get("q", "").strip()
    filter_status = request.GET.get("status", "").strip()
    date_from = request.GET.get("from", "").strip()
    date_to = request.GET.get("to", "").strip()

    if search:
        qs = qs.filter(
            Q(client__name__icontains=search) |
            Q(client__organization__icontains=search) |
            Q(order__cl_number__icontains=search)
        )

    if filter_status:
        qs = qs.filter(status=filter_status)

    if date_from:
        try:
            qs = qs.filter(invoice_date__gte=date_from)
        except Exception:
            # ignore invalid date formats (template will just show nothing)
            pass

    if date_to:
        try:
            qs = qs.filter(invoice_date__lte=date_to)
        except Exception:
            pass

    # --- Pagination (optional) ---
    per_page = 25
    page = request.GET.get("page", 1)
    paginator = Paginator(qs, per_page)
    try:
        invoices_page = paginator.page(page)
    except PageNotAnInteger:
        invoices_page = paginator.page(1)
    except EmptyPage:
        invoices_page = paginator.page(paginator.num_pages)

    # --- status choices for template ---
    status_choices = Invoice.STATUS_CHOICES  # tuples (val, label)

    context = {
        "invoices": invoices_page,        # page object (iterable in template)
        "search": search,
        "status_choices": status_choices,
        "filter_status": filter_status,
        "date_from": date_from,
        "date_to": date_to,
        "paginator": paginator,
        "page_obj": invoices_page,
    }

    return render(request, "invoices/invoices.html", context)
    

@login_required
def view_invoice(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "client", "order", "order__client", "order__created_by"
        ).prefetch_related(
            "order__items", "order__items__product", "order__items__category"
        ),
        pk=pk,
    )

    order = invoice.order
    client = invoice.client
    items = order.items.all()

    today = localdate()
    is_overdue = (
        invoice.status != "paid"
        and invoice.due_date is not None
        and invoice.due_date < today
    )
    deposit_outstanding = max(invoice.amount_due - (invoice.deposit_paid or 0), 0)

    return render(
        request,
        "invoices/view_invoice.html",
        {
            "invoice": invoice,
            "order": order,
            "client": client,
            "items": items,
            "is_overdue": is_overdue,
            "deposit_outstanding": deposit_outstanding,
        },
    )



def prev_year_month(year, month, offset=1):
    """
    Return (year, month) offset months before the given year/month.
    offset=0 => same month
    offset=1 => previous month
    """
    m = month - offset
    y = year
    while m <= 0:
        m += 12
        y -= 1
    return y, m





@login_required
def commission(request):
    today = localdate()

    selected_month = int(request.GET.get("month", today.month))
    selected_year = int(request.GET.get("year", today.year))
    selected_area = request.GET.get("area", "")

    month_code = calendar.month_abbr[selected_month].upper()

    first_day = date(selected_year, selected_month, 1)
    last_day = date(
        selected_year,
        selected_month,
        calendar.monthrange(selected_year, selected_month)[1],
    )

    # =========================
    # PREVIOUS PERIOD SETUP
    # =========================
    prev_month = selected_month - 1 or 12
    prev_year = selected_year if selected_month != 1 else selected_year - 1

    prev_first_day = date(prev_year, prev_month, 1)
    prev_last_day = date(
        prev_year,
        prev_month,
        calendar.monthrange(prev_year, prev_month)[1],
    )

    if selected_year == today.year and selected_month == today.month:
        comparison_start = prev_first_day
        comparison_day = min(
            today.day,
            calendar.monthrange(prev_year, prev_month)[1],
        )
        comparison_end = date(prev_year, prev_month, comparison_day)
    else:
        comparison_start = prev_first_day
        comparison_end = prev_last_day

    def build_change(current, previous):
        current = current or Decimal("0.00")
        previous = previous or Decimal("0.00")

        if not isinstance(current, Decimal):
            current = Decimal(str(current))

        if not isinstance(previous, Decimal):
            previous = Decimal(str(previous))

        diff = current - previous

        if previous > 0:
            pct = ((diff / previous) * Decimal("100")).quantize(Decimal("0.01"))
        elif current > 0:
            pct = Decimal("100.00")
        else:
            pct = Decimal("0.00")

        if diff > 0:
            direction = "up"
        elif diff < 0:
            direction = "down"
        else:
            direction = "flat"

        return {
            "direction": direction,
            "amount": diff.quantize(Decimal("0.01")),
            "percent": pct,
        }

    # =========================
    # BASE COMMISSION QUERY
    # =========================
    commission_entries = (
        CommissionEntry.objects
        .select_related(
            "invoice",
            "invoice__client",
            "client",
            "rep",
            "supervisor",
        )
        .filter(
            created_at__date__gte=first_day,
            created_at__date__lte=last_day,
        )
        .order_by("-created_at")
    )

    if selected_area:
        commission_entries = commission_entries.filter(
            client__area=selected_area
        )

    # =========================
    # PREVIOUS COMMISSION QUERY
    # =========================
    previous_commission_entries = (
        CommissionEntry.objects
        .select_related(
            "invoice",
            "invoice__client",
            "client",
            "rep",
            "supervisor",
        )
        .filter(
            created_at__date__gte=comparison_start,
            created_at__date__lte=comparison_end,
        )
    )

    if selected_area:
        previous_commission_entries = previous_commission_entries.filter(
            client__area=selected_area
        )

    # =========================
    # TARGETS
    # =========================
    monthly_targets = MonthlyTarget.objects.filter(
        year=selected_year,
        month=month_code,
    )

    if selected_area:
        monthly_targets = monthly_targets.filter(area=selected_area)

    monthly_target = (
        monthly_targets.aggregate(t=Sum("monthly_target"))["t"]
        or Decimal("0.00")
    )

    client_target = (
        monthly_targets.aggregate(t=Sum("total_client_target"))["t"]
        or 0
    )

    # =========================
    # TOTAL COMMISSION PAYABLE
    # =========================
    commission_totals = commission_entries.aggregate(
        rep_total=Coalesce(
            Sum("rep_amount"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        supervisor_total=Coalesce(
            Sum("supervisor_amount"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )

    total_commission_payable = (
        commission_totals["rep_total"]
        + commission_totals["supervisor_total"]
    ).quantize(Decimal("0.01"))

    new_business_bonus_total = (
        commission_entries
        .filter(is_new_business=True)
        .aggregate(t=Sum("rep_amount"))["t"]
        or Decimal("0.00")
    )

    total_revenue = (
        commission_entries.aggregate(
            t=Sum("invoice__order_total_inc")
        )["t"]
        or Decimal("0.00")
    )

    total_clients = (
        commission_entries
        .values("client_id")
        .exclude(client_id=None)
        .distinct()
        .count()
    )

    # =========================
    # PREVIOUS PERIOD KPI VALUES
    # =========================
    previous_commission_totals = previous_commission_entries.aggregate(
        rep_total=Coalesce(
            Sum("rep_amount"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        supervisor_total=Coalesce(
            Sum("supervisor_amount"),
            Decimal("0.00"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )

    previous_commission_payable = (
        previous_commission_totals["rep_total"]
        + previous_commission_totals["supervisor_total"]
    ).quantize(Decimal("0.01"))

    previous_revenue = (
        previous_commission_entries.aggregate(
            t=Sum("invoice__order_total_inc")
        )["t"]
        or Decimal("0.00")
    )

    previous_clients = (
        previous_commission_entries
        .values("client_id")
        .exclude(client_id=None)
        .distinct()
        .count()
    )

    previous_new_business_bonus = (
        previous_commission_entries
        .filter(is_new_business=True)
        .aggregate(t=Sum("rep_amount"))["t"]
        or Decimal("0.00")
    )

    commission_payable_change = build_change(
        total_commission_payable,
        previous_commission_payable,
    )

    revenue_change = build_change(
        total_revenue,
        previous_revenue,
    )

    clients_change = build_change(
        Decimal(total_clients),
        Decimal(previous_clients),
    )

    new_business_bonus_change = build_change(
        new_business_bonus_total,
        previous_new_business_bonus,
    )

    actual_revenue = total_revenue
    actual_clients = total_clients

    revenue_target_pct = (
        (actual_revenue / monthly_target) * Decimal("100")
        if monthly_target > 0 else Decimal("0.00")
    )

    client_target_pct = (
        (Decimal(actual_clients) / Decimal(client_target)) * Decimal("100")
        if client_target > 0 else Decimal("0.00")
    )

    revenue_gap = max(monthly_target - actual_revenue, Decimal("0.00"))
    clients_needed_for_bonus = max(client_target - actual_clients, 0)
    bonus_active = actual_clients > client_target if client_target else False

    # =========================
    # WORKING DAYS / DAILY PACING
    # =========================
    working_days = 0

    for target in monthly_targets:
        try:
            working_days = max(working_days, target.get_total_working_days())
        except Exception:
            pass

    if working_days <= 0:
        working_days = 1

    if today.year == selected_year and today.month == selected_month:
        current_day_limit = today.day
    else:
        current_day_limit = last_day.day

    days_passed = 0
    for d in range(1, current_day_limit + 1):
        current = date(selected_year, selected_month, d)
        if current.weekday() < 5:
            days_passed += 1

    days_remaining = max(working_days - days_passed, 0)

    weeks_in_month = Decimal("4.00")

    weekly_average = (
        actual_revenue / weeks_in_month
        if actual_revenue > 0 else Decimal("0.00")
    ).quantize(Decimal("0.01"))

    required_per_week = (
        revenue_gap / weeks_in_month
        if revenue_gap > 0 else Decimal("0.00")
    ).quantize(Decimal("0.01"))

    # =========================
    # REP PERFORMANCE TABLE
    # =========================
    rep_commission_summary = []

    allocations = (
        MonthlyTargetAllocation.objects
        .select_related("sales_rep", "monthly_target")
        .filter(
            monthly_target__year=selected_year,
            monthly_target__month=month_code,
        )
    )

    if selected_area:
        allocations = allocations.filter(monthly_target__area=selected_area)

    for allocation in allocations:
        rep = allocation.sales_rep

        if not rep:
            continue

        rep_entries = commission_entries.filter(rep=rep)

        rep_revenue = (
            rep_entries.aggregate(t=Sum("invoice__order_total_inc"))["t"]
            or Decimal("0.00")
        )

        rep_clients = (
            rep_entries
            .values("client_id")
            .exclude(client_id=None)
            .distinct()
            .count()
        )

        base_commission = (
            rep_entries
            .filter(is_new_business=False)
            .aggregate(t=Sum("rep_amount"))["t"]
            or Decimal("0.00")
        )

        bonus_commission = (
            rep_entries
            .filter(is_new_business=True)
            .aggregate(t=Sum("rep_amount"))["t"]
            or Decimal("0.00")
        )

        total_rep_commission = base_commission + bonus_commission

        revenue_pct = (
            (rep_revenue / allocation.monthly_target_value) * Decimal("100")
            if allocation.monthly_target_value > 0 else Decimal("0.00")
        )

        full_name = rep.get_full_name() or rep.username

        rep_commission_summary.append({
            "rep_id": rep.id,
            "rep_name": full_name,
            "role": "Sales Rep",
            "area": allocation.monthly_target.get_area_display(),
            "revenue": rep_revenue,
            "revenue_target": allocation.monthly_target_value,
            "revenue_pct": revenue_pct,
            "clients": rep_clients,
            "client_target": allocation.client_target,
            "base_commission": base_commission,
            "bonus_commission": bonus_commission,
            "total_commission": total_rep_commission,
        })

    rep_commission_summary = sorted(
        rep_commission_summary,
        key=lambda x: (
            x["total_commission"],
            x["bonus_commission"],
            x["revenue"],
            x["clients"],
        ),
        reverse=True,
    )

    for index, row in enumerate(rep_commission_summary, start=1):
        row["ranking"] = index

    # =========================
    # AREA PERFORMANCE VIEW
    # =========================
    area_performance_summary = []

    area_targets = monthly_targets

    for target in area_targets:
        area_code = target.area
        area_label = target.get_area_display()

        area_entries = commission_entries.filter(
            client__area=area_code
        )

        rep_count = (
            area_entries
            .exclude(rep=None)
            .values("rep_id")
            .distinct()
            .count()
        )

        total_clients_area = (
            area_entries
            .exclude(client=None)
            .values("client_id")
            .distinct()
            .count()
        )

        area_revenue = (
            area_entries.aggregate(t=Sum("invoice__order_total_inc"))["t"]
            or Decimal("0.00")
        )

        rep_commission_total = (
            area_entries.aggregate(t=Sum("rep_amount"))["t"]
            or Decimal("0.00")
        )

        supervisor_commission_total = (
            area_entries.aggregate(t=Sum("supervisor_amount"))["t"]
            or Decimal("0.00")
        )

        total_commission_area = (
            rep_commission_total + supervisor_commission_total
        ).quantize(Decimal("0.01"))

        area_performance_summary.append({
            "area": area_label,
            "rep_count": rep_count,
            "clients": total_clients_area,
            "revenue": area_revenue,
            "rep_commission_total": rep_commission_total,
            "supervisor_commission_total": supervisor_commission_total,
            "total_commission": total_commission_area,
        })

    # =========================
    # PERFORMANCE TREND GRAPH
    # Revenue / Commission / Active Clients / Orders
    # =========================
    performance_trend_labels = []
    performance_trend_revenue = []
    performance_trend_commission = []
    performance_trend_clients = []
    performance_trend_orders = []

    for month in range(1, 13):
        start = date(selected_year, month, 1)
        end = date(
            selected_year,
            month,
            calendar.monthrange(selected_year, month)[1],
        )

        month_entries = (
            CommissionEntry.objects
            .select_related("invoice", "client", "rep", "supervisor")
            .filter(
                created_at__date__gte=start,
                created_at__date__lte=end,
            )
        )

        if selected_area:
            month_entries = month_entries.filter(client__area=selected_area)

        month_revenue = (
            month_entries.aggregate(
                t=Sum("invoice__order_total_inc")
            )["t"]
            or Decimal("0.00")
        )

        month_commission_totals = month_entries.aggregate(
            rep_total=Coalesce(
                Sum("rep_amount"),
                Decimal("0.00"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            supervisor_total=Coalesce(
                Sum("supervisor_amount"),
                Decimal("0.00"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )

        month_commission = (
            month_commission_totals["rep_total"]
            + month_commission_totals["supervisor_total"]
        ).quantize(Decimal("0.01"))

        month_clients = (
            month_entries
            .exclude(client=None)
            .values("client_id")
            .distinct()
            .count()
        )

        month_orders = (
            month_entries
            .exclude(invoice=None)
            .values("invoice_id")
            .distinct()
            .count()
        )

        performance_trend_labels.append(calendar.month_abbr[month])
        performance_trend_revenue.append(float(month_revenue))
        performance_trend_commission.append(float(month_commission))
        performance_trend_clients.append(month_clients)
        performance_trend_orders.append(month_orders)

    # =========================
    # PAYROLL ROWS
    # =========================
    payroll_rows = []

    monthly_commissions = MonthlyCommission.objects.filter(
        year=selected_year,
        month=selected_month,
    ).select_related("rep")

    if selected_area:
        rep_ids_in_area = [
            row["rep_id"]
            for row in rep_commission_summary
        ]
        monthly_commissions = monthly_commissions.filter(rep_id__in=rep_ids_in_area)

    for mc in monthly_commissions:
        adjustments_total = (
            mc.adjustments.aggregate(t=Sum("amount"))["t"]
            or Decimal("0.00")
        )

        payroll_rows.append({
            "rep_id": mc.rep_id,
            "rep_name": mc.rep.get_full_name() or mc.rep.username,
            "base_commission": mc.recurring_commission_total,
            "bonus_commission": mc.new_business_commission,
            "adjustments": adjustments_total,
            "total_payout": mc.total_payout + adjustments_total,
            "paid": mc.paid,
            "paid_on": mc.paid_on,
        })

    # =========================
    # FILTER OPTIONS
    # =========================
    months = [
        {"value": i, "label": calendar.month_name[i]}
        for i in range(1, 13)
    ]

    years = list(range(today.year - 2, today.year + 3))

    areas = [
        {"value": code, "label": label}
        for code, label in MonthlyTarget.AREA_CHOICES
    ]

    # =========================
    # EMAIL MODAL COMPATIBILITY
    # =========================
    target_rep = None
    filter_date_from = first_day
    filter_date_to = last_day

    context = {
        "selected_month": selected_month,
        "selected_year": selected_year,
        "selected_area": selected_area,
        "months": months,
        "years": years,
        "areas": areas,

        "total_commission_payable": total_commission_payable,
        "total_revenue": total_revenue,
        "total_clients": total_clients,
        "new_business_bonus_total": new_business_bonus_total,

        "commission_payable_change": commission_payable_change,
        "revenue_change": revenue_change,
        "clients_change": clients_change,
        "new_business_bonus_change": new_business_bonus_change,
        "comparison_start": comparison_start,
        "comparison_end": comparison_end,

        "actual_revenue": actual_revenue,
        "monthly_target": monthly_target,
        "revenue_target_pct": revenue_target_pct,
        "revenue_gap": revenue_gap,
        "required_per_week": required_per_week,
        "weekly_average": weekly_average,

        "actual_clients": actual_clients,
        "client_target": client_target,
        "client_target_pct": client_target_pct,
        "bonus_active": bonus_active,
        "clients_needed_for_bonus": clients_needed_for_bonus,

        "rep_commission_summary": rep_commission_summary,
        "commission_entries": commission_entries[:20],
        "area_performance_summary": area_performance_summary,
        "payroll_rows": payroll_rows,

        "target_rep": target_rep,
        "filter_date_from": filter_date_from,
        "filter_date_to": filter_date_to,

        "performance_trend_labels": performance_trend_labels,
        "performance_trend_revenue": performance_trend_revenue,
        "performance_trend_commission": performance_trend_commission,
        "performance_trend_clients": performance_trend_clients,
        "performance_trend_orders": performance_trend_orders,
    }

    return render(request, "commission/commission.html", context)


@login_required
def supervisor_detail(request, user_id):

    # =========================
    # GET SUPERVISOR
    # =========================
    supervisor = get_object_or_404(User, id=user_id)

    reps = SalesRepProfile.objects.filter(
        supervisor=supervisor
    ).select_related("user")

    rep_ids = reps.values_list("user_id", flat=True)

    today = localdate()

    # =========================
    # FILTER (DATE RANGE FIRST)
    # =========================
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    if date_from and date_to:
        first_day = date.fromisoformat(date_from)
        last_day = date.fromisoformat(date_to)

        selected_month = first_day.month
        selected_year = first_day.year
    else:
        selected_month = int(request.GET.get("month", today.month))
        selected_year = int(request.GET.get("year", today.year))

        first_day = date(selected_year, selected_month, 1)
        last_day = date(
            selected_year,
            selected_month,
            calendar.monthrange(selected_year, selected_month)[1],
        )

        date_from = first_day
        date_to = last_day

    # =========================
    # PREVIOUS PERIOD (TREND)
    # =========================
    prev_month = selected_month - 1 or 12
    prev_year = selected_year if selected_month != 1 else selected_year - 1

    prev_first_day = date(prev_year, prev_month, 1)
    prev_last_day = date(
        prev_year,
        prev_month,
        calendar.monthrange(prev_year, prev_month)[1],
    )

    # =========================
    # QUERYSETS
    # =========================
    current_qs = CommissionEntry.objects.filter(
        rep__id__in=rep_ids,
        invoice__status="paid",
        invoice__paid_date__range=[first_day, last_day],
    )

    prev_qs = CommissionEntry.objects.filter(
        rep__id__in=rep_ids,
        invoice__status="paid",
        invoice__paid_date__range=[prev_first_day, prev_last_day],
    )

    # =========================
    # TEAM UTILIZATION
    # =========================
    team_total = current_qs.aggregate(t=Sum("cost_total"))["t"] or Decimal("0.00")
    prev_total = prev_qs.aggregate(t=Sum("cost_total"))["t"] or Decimal("0.00")

    # =========================
    # TARGET
    # =========================
    monthly_target_obj = MonthlyTarget.objects.filter(
        year=selected_year,
        month=calendar.month_abbr[selected_month].upper(),
    ).first()

    monthly_target = (
        monthly_target_obj.monthly_target
        if monthly_target_obj else Decimal("0.00")
    )

    # =========================
    # WORKING DAYS
    # =========================
    working_days = (
        monthly_target_obj.get_total_working_days()
        if monthly_target_obj else 0
    )

    # Days passed (respect period)
    days_passed = 0
    current_date = first_day

    while current_date <= min(today, last_day):
        if current_date.weekday() < 5:
            days_passed += 1
        current_date += timedelta(days=1)

    days_remaining = max(working_days - days_passed, 0)

    # =========================
    # DAILY AVERAGES
    # =========================
    team_avg = (
        team_total / Decimal(working_days)
        if working_days > 0 else Decimal("0.00")
    )

    prev_avg = (
        prev_total / Decimal(working_days)
        if working_days > 0 else Decimal("0.00")
    )

    # =========================
    # ACHIEVEMENT
    # =========================
    achievement_pct = (
        (team_total / monthly_target) * Decimal("100")
        if monthly_target > 0 else Decimal("0.00")
    )

    # =========================
    # TREND
    # =========================
    if prev_avg == 0:
        trend = "flat"
        trend_percent = Decimal("0.00")
    else:
        diff = team_avg - prev_avg
        trend_percent = (diff / prev_avg) * Decimal("100")

        if diff > 0:
            trend = "up"
        elif diff < 0:
            trend = "down"
        else:
            trend = "flat"

    # =========================
    # TARGET TRACKING
    # =========================
    target_remaining = monthly_target - team_total

    weeks_in_month = Decimal("4.00")

    weekly_average = (
        actual_revenue / weeks_in_month
        if actual_revenue > 0 else Decimal("0.00")
    ).quantize(Decimal("0.01"))

    required_per_week = (
        revenue_gap / weeks_in_month
        if revenue_gap > 0 else Decimal("0.00")
    ).quantize(Decimal("0.01"))

    # =========================
    # TEAM SIZE
    # =========================
    team_size = reps.count()

    # =========================
    # TEAM BREAKDOWN
    # =========================
    team_reps = []

    for rep in reps:
        rep_id = rep.user.id

        rep_total = (
            current_qs.filter(rep__id=rep_id)
            .aggregate(t=Sum("cost_total"))["t"]
            or Decimal("0.00")
        )

        rep_prev_total = (
            prev_qs.filter(rep__id=rep_id)
            .aggregate(t=Sum("cost_total"))["t"]
            or Decimal("0.00")
        )

        rep_avg = (
            rep_total / Decimal(working_days)
            if working_days > 0 else Decimal("0.00")
        )

        rep_prev_avg = (
            rep_prev_total / Decimal(working_days)
            if working_days > 0 else Decimal("0.00")
        )

        if rep_prev_avg == 0:
            rep_trend = "flat"
            rep_trend_percent = Decimal("0.00")
        else:
            diff = rep_avg - rep_prev_avg
            rep_trend_percent = (diff / rep_prev_avg) * Decimal("100")

            if diff > 0:
                rep_trend = "up"
            elif diff < 0:
                rep_trend = "down"
            else:
                rep_trend = "flat"

        team_reps.append({
            "user_id": rep.user.id,
            "first_name": rep.user.first_name,
            "last_name": rep.user.last_name,
            "daily_avg": rep_avg,
            "total": rep_total,
            "trend": rep_trend,
            "trend_percent": rep_trend_percent,
        })

    # =========================
    # TEAM INVOICES
    # =========================
    invoice_entries = CommissionEntry.objects.filter(
        rep__id__in=rep_ids,
        invoice__status="paid",
        invoice__paid_date__range=[first_day, last_day],
    ).select_related("invoice", "invoice__client", "rep")

    # =========================
    # CONTEXT
    # =========================
    context = {
        "supervisor": supervisor,

        "date_from": date_from,
        "date_to": date_to,

        "selected_month": selected_month,
        "selected_year": selected_year,
        "selected_month_name": calendar.month_name[selected_month],

        "team_total": team_total,
        "team_avg": team_avg,
        "achievement_pct": achievement_pct,

        "working_days": working_days,
        "days_passed": days_passed,
        "days_remaining": days_remaining,

        "prev_avg": prev_avg,
        "trend": trend,
        "trend_percent": trend_percent,

        "target_remaining": target_remaining,
        "required_per_week": required_per_week,
        "weekly_average": weekly_average,

        "team_size": team_size,
        "team_reps": team_reps,
        "invoice_entries": invoice_entries,

        "invoices": invoices,
    }

    return render(request, "commission/supervisor_detail.html", context)



@login_required
def rep_detail(request, user_id):

    # =========================
    # GET REP
    # =========================
    rep = get_object_or_404(
        SalesRepProfile.objects.select_related("user"),
        user__id=user_id
    )

    today = localdate()

    # =========================
    # FILTER (DATE RANGE FIRST)
    # =========================
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    if date_from and date_to:
        first_day = date.fromisoformat(date_from)
        last_day = date.fromisoformat(date_to)

        selected_month = first_day.month
        selected_year = first_day.year

    else:
        selected_month = int(request.GET.get("month", today.month))
        selected_year = int(request.GET.get("year", today.year))

        first_day = date(selected_year, selected_month, 1)
        last_day = date(
            selected_year,
            selected_month,
            calendar.monthrange(selected_year, selected_month)[1],
        )

        date_from = first_day
        date_to = last_day

    # =========================
    # PREVIOUS PERIOD (TREND)
    # =========================
    prev_month = selected_month - 1 or 12
    prev_year = selected_year if selected_month != 1 else selected_year - 1

    prev_first_day = date(prev_year, prev_month, 1)
    prev_last_day = date(
        prev_year,
        prev_month,
        calendar.monthrange(prev_year, prev_month)[1],
    )

    # =========================
    # QUERYSETS
    # =========================
    current_qs = CommissionEntry.objects.filter(
        rep__id=user_id,
        invoice__status="paid",
        invoice__paid_date__range=[first_day, last_day],
    )

    prev_qs = CommissionEntry.objects.filter(
        rep__id=user_id,
        invoice__status="paid",
        invoice__paid_date__range=[prev_first_day, prev_last_day],
    )

    # =========================
    # UTILIZATION
    # =========================
    current_total = current_qs.aggregate(t=Sum("cost_total"))["t"] or Decimal("0.00")
    prev_total = prev_qs.aggregate(t=Sum("cost_total"))["t"] or Decimal("0.00")

    # =========================
    # TARGET
    # =========================
    monthly_target_obj = MonthlyTarget.objects.filter(
        year=selected_year,
        month=calendar.month_abbr[selected_month].upper(),
    ).first()

    monthly_target = (
        monthly_target_obj.monthly_target
        if monthly_target_obj else Decimal("0.00")
    )

    # =========================
    # WORKING DAYS
    # =========================
    working_days = (
        monthly_target_obj.get_total_working_days()
        if monthly_target_obj else 0
    )

    # IMPORTANT: respect selected period
    days_passed = 0
    for d in range(1, today.day + 1):
        try:
            current_date = date(selected_year, selected_month, d)
            if current_date.weekday() < 5:
                days_passed += 1
        except:
            pass

    days_remaining = max(working_days - days_passed, 0)

    # =========================
    # DAILY AVERAGES
    # =========================
    current_avg = (
        current_total / Decimal(working_days)
        if working_days > 0 else Decimal("0.00")
    )

    prev_avg = (
        prev_total / Decimal(working_days)
        if working_days > 0 else Decimal("0.00")
    )

    # =========================
    # ACHIEVEMENT
    # =========================
    achievement_pct = (
        (current_total / monthly_target) * Decimal("100")
        if monthly_target > 0 else Decimal("0.00")
    )

    # =========================
    # TREND
    # =========================
    if prev_avg == 0:
        trend = "flat"
        trend_percent = Decimal("0.00")
    else:
        diff = current_avg - prev_avg
        trend_percent = (diff / prev_avg) * Decimal("100")

        if diff > 0:
            trend = "up"
        elif diff < 0:
            trend = "down"
        else:
            trend = "flat"

    # =========================
    # TARGET TRACKING
    # =========================
    target_remaining = monthly_target - current_total

    weeks_in_month = Decimal("4.00")

    weekly_average = (
        actual_revenue / weeks_in_month
        if actual_revenue > 0 else Decimal("0.00")
    ).quantize(Decimal("0.01"))

    required_per_week = (
        revenue_gap / weeks_in_month
        if revenue_gap > 0 else Decimal("0.00")
    ).quantize(Decimal("0.01"))

    # =========================
    # INVOICES (🔥 KEY PART)
    # =========================
    invoices = Invoice.objects.filter(
        client__account_manager=rep.user,
        created_at__date__range=[first_day, last_day]
    ).select_related("client").order_by("-created_at")

    # =========================
    # FILTER OPTIONS
    # =========================
    months = [
        {"value": i, "label": calendar.month_name[i]}
        for i in range(1, 13)
    ]

    years = list(range(today.year - 2, today.year + 2))

    # =========================
    # CONTEXT
    # =========================
    context = {
        "rep": rep,

        # FILTERS
        "selected_month": selected_month,
        "selected_year": selected_year,
        "selected_month_name": calendar.month_name[selected_month],
        "months": months,
        "years": years,

        "date_from": date_from,
        "date_to": date_to,

        # PERFORMANCE
        "current_total": current_total,
        "monthly_target": monthly_target,
        "achievement_pct": achievement_pct,

        "working_days": working_days,
        "days_passed": days_passed,
        "days_remaining": days_remaining,

        "current_avg": current_avg,
        "prev_avg": prev_avg,

        "trend": trend,
        "trend_percent": trend_percent,

        "target_remaining": target_remaining,
        "required_per_day": required_per_day,

        # INVOICES
        "invoices": invoices,
    }

    return render(request, "commission/rep_detail.html", context)


@login_required
def commission_view(request, pk):
    user = request.user
    user_groups = list(user.groups.values_list("name", flat=True))

    is_admin = "Administrator" in user_groups
    is_sales = "Sales" in user_groups

    # ------------------------------------------------------------------
    # Base queryset
    # ------------------------------------------------------------------
    qs = (
        CommissionEntry.objects
        .select_related(
            "invoice",
            "invoice__client",
            "rep",
            "supervisor",
        )
    )

    entry = get_object_or_404(qs, pk=pk)

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------
    if not is_admin:
        # Sales users may only see entries where they are involved
        if entry.rep_id != user.id and entry.supervisor_id != user.id:
            raise Http404("You do not have permission to view this commission.")

    # ------------------------------------------------------------------
    # Derived helpers for template
    # ------------------------------------------------------------------
    rep_is_supervisor = (
        entry.rep_id
        and entry.supervisor_id
        and entry.rep_id == entry.supervisor_id
    )

    total_commission = (
        (entry.rep_amount or Decimal("0.00")) +
        (entry.supervisor_amount or Decimal("0.00"))
    )

    context = {
        "entry": entry,
        "total_commission": total_commission,
        "invoice": entry.invoice,
        "client": entry.invoice.client if entry.invoice else None,

        "rep": entry.rep,
        "supervisor": entry.supervisor,
        "rep_is_supervisor": rep_is_supervisor,

        "is_admin_viewing": is_admin,
    }

    return render(
        request,
        "commission/commission_view.html",
        context,
    )



@login_required
def send_commission_statement_email(request):
    """
    Send commission statement email for a single rep over a filtered date range.
    Expects POST with JSON:
    {
        "email": "recipient@example.com",
        "recipient_name": "John Doe",
        "agent": 1,
        "from": "2026-01-01",
        "to": "2026-01-31"
    }
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON."}, status=400)

    email_to = data.get("email")
    recipient_name = data.get("recipient_name", "").strip()
    agent_id = data.get("agent")
    date_from = data.get("from")
    date_to = data.get("to")

    if not email_to:
        return JsonResponse({"success": False, "error": "No email provided."}, status=400)
    if not agent_id:
        return JsonResponse({"success": False, "error": "No agent selected."}, status=400)
    if not date_from or not date_to:
        return JsonResponse({"success": False, "error": "Date range is required."}, status=400)

    # Parse dates
    try:
        date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
        date_to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)  # include end day
    except ValueError:
        return JsonResponse({"success": False, "error": "Invalid date format."}, status=400)

    # Get rep
    rep = get_object_or_404(User, pk=agent_id)

    if not recipient_name:
        recipient_name = rep.get_full_name() or rep.username

    # Fetch commission entries for this rep & date range
    entries = CommissionEntry.objects.filter(
        rep=rep,
        invoice__paid_date__gte=date_from_dt,
        invoice__paid_date__lt=date_to_dt
    ).select_related("invoice", "invoice__client")

    if not entries.exists():
        return JsonResponse({"success": False, "error": "No commission entries for this period."}, status=400)

    # Calculate totals
    total_rep = sum(e.rep_amount for e in entries)
    total_supervisor = sum(e.supervisor_amount for e in entries)
    total_commission = total_rep + total_supervisor

    # Build context for email template
    ctx = {
        "entries": entries,
        "rep": rep,
        "recipient_name": recipient_name,
        "from_date": date_from_dt,
        "to_date": date_to_dt - timedelta(days=1),  # display actual end date
        "total_rep": total_rep,
        "total_supervisor": total_supervisor,
        "total_commission": total_commission,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
        "statement_url": request.build_absolute_uri(reverse("sales:commission")),  # optional link
    }

    # Render email
    text_body = render_to_string("email/commission_statement.txt", ctx)
    html_body = render_to_string("email/commission_statement.html", ctx)

    subject = f"Commission Statement – {rep.get_full_name() or rep.username}"
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


def _parse_date_local(date_str: str):
    """Parse YYYY-MM-DD to aware start/end of that day in local TZ."""
    try:
        d = datetime.fromisoformat(date_str).date()
        start_naive = datetime.combine(d, time.min)
        end_naive = datetime.combine(d, time.max)
        return timezone.make_aware(start_naive), timezone.make_aware(end_naive)
    except Exception:
        return None, None



@login_required
def tickets(request):
    qs = (
        Ticket.objects
        .select_related("client", "created_by", "closed_by")
        .order_by("-created_at")
    )

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    department = (request.GET.get("department") or "").strip()
    ticket_type = (request.GET.get("ticket_type") or "").strip()

    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(requester_name__icontains=q)
            | Q(requester_email__icontains=q)
            | Q(requester_phone__icontains=q)
            | Q(client__name__icontains=q)
            | Q(client__organization__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    if priority:
        qs = qs.filter(priority=priority)

    if department:
        qs = qs.filter(department=department)

    if ticket_type:
        qs = qs.filter(ticket_type=ticket_type)

    stats_qs = Ticket.objects.all()

    stats = {
        "total": stats_qs.count(),
        "new": stats_qs.filter(status=Ticket.Status.NEW).count(),
        "open": stats_qs.filter(status=Ticket.Status.OPEN).count(),
        "pending": stats_qs.filter(status=Ticket.Status.PENDING).count(),
        "resolved": stats_qs.filter(status=Ticket.Status.RESOLVED).count(),
        "closed": stats_qs.filter(status=Ticket.Status.CLOSED).count(),
    }

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "object_list": page_obj.object_list,
        "page_obj": page_obj,
        "stats": stats,
        "filters": {
            "q": q,
            "status": status,
            "priority": priority,
            "department": department,
            "ticket_type": ticket_type,
        },
        "choices": {
            "status": Ticket.Status.choices,
            "priority": Ticket.Priority.choices,
            "department": Ticket.Department.choices,
            "ticket_type": Ticket.TicketType.choices,
        },
    }

    return render(request, "tickets/tickets.html", context)



@login_required
def target_list(request):
    targets = (
        MonthlyTarget.objects
        .all()
        .order_by("-year", "-month")
    )

    return render(request, "commission/targets.html", {
        "targets": targets
    })


@login_required
def add_target(request):

    targets = MonthlyTarget.objects.all().order_by("-year", "-month")

    if request.method == "POST":
        form = MonthlyTargetForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("sales:sales-target-list")
    else:
        form = MonthlyTargetForm()

    return render(request, "commission/add_target.html", {
        "form": form
    })


# --- Optional quick actions (wire to buttons/links if needed) ---
@login_required
def task_close(request, pk: int):
    task = Task.objects.filter(pk=pk).first()
    if not task:
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Task+not+found")
    if not (request.user.is_staff or request.user == task.assigned_to or request.user == task.created_by):
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Not+authorized")
    task.status = Task.Status.CLOSED
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?ok=Task+closed")


@login_required
def task_reopen(request, pk: int):
    task = Task.objects.filter(pk=pk).first()
    if not task:
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Task+not+found")
    if not (request.user.is_staff or request.user == task.assigned_to or request.user == task.created_by):
        return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?err=Not+authorized")
    task.status = Task.Status.OPEN
    task.completed_at = None
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return redirect(f"{request.META.get('HTTP_REFERER','/tasks/')}?ok=Task+reopened")


@login_required
def view_ticket(request, pk):
    task = get_object_or_404(Task, pk=pk)

    # Optional: load comments if you have a TaskComment model with FK "task" and related_name "comments"
    try:
        comments_qs = task.comments.order_by("-created_at")
    except Exception:
        comments_qs = []

    # Optional: build a related URL if the linked object exposes get_absolute_url()
    related_url = None
    if task.related_object:
        try:
            if hasattr(task.related_object, "get_absolute_url"):
                related_url = task.related_object.get_absolute_url()
        except Exception:
            related_url = None

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        # Basic authorization: staff OR the assignee OR the creator
        is_authorized = (
            request.user.is_staff
            or request.user == getattr(task, "assigned_to", None)
            or request.user == getattr(task, "created_by", None)
        )
        if not is_authorized:
            messages.error(request, "Not authorized to update this task.")
            return redirect(request.path)

        if action == "close":
            task.status = Task.Status.CLOSED
            task.completed_at = timezone.now()
            task.save(update_fields=["status", "completed_at", "updated_at"])
            messages.success(request, "Task closed.")
            return redirect(request.path)

        elif action == "pending":
            task.status = Task.Status.PENDING
            # keep completed_at as-is (usually None or a past value)
            task.save(update_fields=["status", "updated_at"])
            messages.success(request, "Task marked as pending.")
            return redirect(request.path)

        elif action == "reopen":
            task.status = Task.Status.OPEN
            task.completed_at = None
            task.save(update_fields=["status", "completed_at", "updated_at"])
            messages.success(request, "Task reopened.")
            return redirect(request.path)

        elif action == "add_comment":
            body = (request.POST.get("comment") or "").strip()
            if not body:
                messages.error(request, "Comment cannot be empty.")
                return redirect(request.path)

            # Only if you have a TaskComment model
            try:
                from .models import TaskComment  # adjust import if located elsewhere
                TaskComment.objects.create(
                    task=task,
                    body=body,
                    author=request.user if request.user.is_authenticated else None,
                    author_name=str(request.user) if request.user.is_authenticated else "System",
                )
                messages.success(request, "Comment added.")
            except Exception:
                messages.error(request, "Comments are not enabled.")
            return redirect(request.path)

        elif action == "delete":
            # Optional: allow only staff or creator to delete
            if not (request.user.is_staff or request.user == getattr(task, "created_by", None)):
                messages.error(request, "Not authorized to delete this task.")
                return redirect(request.path)
            task.delete()
            messages.success(request, "Task deleted.")
            return redirect("tasks")  # back to list

        else:
            messages.error(request, "Unknown action.")
            return redirect(request.path)

    # GET: render page
    return render(
        request,
        "tickets/view_ticket.html",
        {
            "task": task,
            "comments": comments_qs,
            "related_url": related_url,
        },
    )



@login_required
def profile(request):
    return render(request, "profile/profile.html")


def sales_job(request):
    """
    Public job application page for The Daily Market sales roles.
    """

    if request.method == "POST":
        form = JobApplicationForm(request.POST)

        if form.is_valid():
            application = form.save()

            return render(
                request,
                "jobs/sales_job_thank_you.html",
                {
                    "application": application
                }
            )
    else:
        form = JobApplicationForm()

    return render(
        request,
        "jobs/sales_job.html",
        {"form": form},
    )


def sales_job_thank_you(request):
    return render(request, "jobs/sales_job_thank_you.html")


@login_required
@require_POST
def send_quotation_sms(request, pk):

    quotation = get_object_or_404(
        Quotation.objects.select_related("client", "prospect"),
        pk=pk,
    )

    recipient = quotation.client or quotation.prospect

    if not recipient:
        return JsonResponse({
            "success": False,
            "error": "No client/prospect found."
        }, status=400)

    phone = (
        request.POST.get("phone")
        or getattr(recipient, "phone", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "error": "No mobile number found."
        }, status=400)

    client_name = (
        getattr(recipient, "organization", None)
        or getattr(recipient, "name", None)
        or "Client"
    )

    link = f"{settings.SITE_URL}/orders/q/{quotation.public_token}/"

    message = (
        f"Hi {client_name}, your The Daily Market quotation QT-{quotation.id} "
        f"is ready. Total R{quotation.grand_total_inc:.2f}. "
        f"View/accept: {link}"
    )

    result = send_sms(
        to=phone,
        message=message,
    )

    if not result.get("success"):
        CommunicationLog.objects.create(
            channel=CommunicationLog.CHANNEL_SMS,
            status=CommunicationLog.STATUS_FAILED,
            recipient_name=client_name,
            recipient_contact=phone,
            subject=f"Quotation QT-{quotation.id}",
            message=message,
            related_model="Quotation",
            related_object_id=quotation.id,
            provider="SMSPortal",
            provider_response=result,
            error_message=str(result.get("response")),
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "error": "SMS failed to send.",
            "result": result,
        }, status=400)

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_SMS,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Quotation QT-{quotation.id}",
        message=message,
        related_model="Quotation",
        related_object_id=quotation.id,
        provider="SMSPortal",
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "SMS sent successfully.",
        "result": result,
    })



@login_required
@require_POST
def send_quotation_email_internal(request, pk):

    quotation = get_object_or_404(
        Quotation.objects
        .select_related("client", "prospect")
        .prefetch_related("items", "items__product", "items__category"),
        pk=pk,
    )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON."
        }, status=400)

    email_to = (data.get("email") or "").strip()
    recipient_name = (data.get("recipient_name") or "").strip()

    if not email_to:
        return JsonResponse({
            "success": False,
            "error": "No email provided."
        }, status=400)

    recipient = quotation.client or quotation.prospect

    if not recipient:
        return JsonResponse({
            "success": False,
            "error": "No client/prospect found."
        }, status=400)

    if not recipient_name:
        recipient_name = (
            getattr(recipient, "organization", None)
            or getattr(recipient, "name", None)
            or "Valued Customer"
        )

    items = list(quotation.items.all())

    for item in items:
        unit_price_excl = item.unit_price_excl or Decimal("0.00")
        vat_percent = item.vat_percent or Decimal("0.00")
        line_total_excl = item.line_total_excl or Decimal("0.00")
        line_vat_amount = item.line_vat_amount or Decimal("0.00")

        item.display_unit_price_inc = (
            unit_price_excl + (unit_price_excl * vat_percent / Decimal("100"))
        )

        item.display_line_total_inc = line_total_excl + line_vat_amount

    quotation_url = request.build_absolute_uri(
        reverse("public-quotation-view", args=[quotation.public_token])
    )

    ctx = {
        "quotation": quotation,
        "recipient": recipient,
        "items": items,
        "recipient_name": recipient_name,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"),
        "quotation_url": quotation_url,
    }

    text_body = render_to_string("email/quotation_email.txt", ctx)
    html_body = render_to_string("email/quotation_email.html", ctx)

    subject = f"The Daily Market – Quotation QT-{quotation.id}"

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "accounts@thedailymarket.co.za"),
        to=[email_to],
        headers={
            "Reply-To": getattr(settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za")
        },
    )

    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=recipient_name,
        recipient_contact=email_to,
        subject=subject,
        message=f"Quotation sent via email. Quotation ID: {quotation.id}",
        related_model="Quotation",
        related_object_id=quotation.id,
        provider="Django Email",
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({"success": True})


@login_required
@require_POST
def send_invoice_email_internal(request, pk):

    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "client",
            "order",
        ).prefetch_related(
            "order__items",
            "order__items__product",
        ),
        pk=pk,
    )

    try:
        data = json.loads(request.body)

    except json.JSONDecodeError:
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid JSON.",
            },
            status=400,
        )

    email_to = (data.get("email") or "").strip()
    recipient_name = (data.get("recipient_name") or "").strip()

    if not email_to:
        return JsonResponse(
            {
                "success": False,
                "error": "No email provided.",
            },
            status=400,
        )

    client = invoice.client

    items = list(invoice.order.items.all())

    for item in items:

        unit_price_excl = item.unit_price_excl or Decimal("0.00")
        vat_percent = item.vat_percent or Decimal("0.00")
        line_total_excl = item.line_total_excl or Decimal("0.00")
        line_vat_amount = item.line_vat_amount or Decimal("0.00")

        item.display_unit_price_inc = (
            unit_price_excl
            + (
                unit_price_excl
                * vat_percent
                / Decimal("100")
            )
        )

        item.display_line_total_inc = (
            line_total_excl
            + line_vat_amount
        )

    if not recipient_name:

        profile = client.customer_profiles.select_related("user").first()

        if profile and profile.user:
            recipient_name = (
                profile.user.get_full_name()
                or profile.user.username
            )

        else:
            recipient_name = client.name or "Valued Customer"

    ctx = {
        "invoice": invoice,
        "client": client,
        "items": items,
        "recipient_name": recipient_name,
        "support_email": getattr(
            settings,
            "SUPPORT_EMAIL",
            "support@thedailymarket.co.za",
        ),
        "invoice_url": request.build_absolute_uri(
            reverse(
                "public-invoice-view",
                args=[invoice.public_token],
            )
        ),
    }

    text_body = render_to_string(
        "email/invoice_email.txt",
        ctx,
    )

    html_body = render_to_string(
        "email/invoice_email.html",
        ctx,
    )

    subject = f"The Daily Market – Invoice INV-{invoice.id}"

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(
            settings,
            "DEFAULT_FROM_EMAIL",
            "accounts@thedailymarket.co.za",
        ),
        to=[email_to],
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

    msg.send(
        fail_silently=False,
    )

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=recipient_name,
        recipient_contact=email_to,
        subject=subject,
        message=f"Invoice sent via email. Invoice ID: {invoice.id}",
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="Django Email",
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse(
        {
            "success": True,
        }
    )

@login_required
@require_POST
def send_invoice_whatsapp_view(request, pk):

    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "order"),
        pk=pk,
    )

    client = invoice.client

    phone = (
        request.POST.get("phone")
        or getattr(client, "whatsapp", "")
        or getattr(client, "phone", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "error": "No WhatsApp number found."
        }, status=400)

    phone = (
        phone
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
    )

    client_name = (
        getattr(client, "organization", None)
        or getattr(client, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/invoices/public/"
        f"{invoice.public_token}/"
    )

    result = send_invoice_whatsapp(
        to=phone,
        client_name=client_name,
        invoice_number=f"INV-{invoice.id}",
        amount=invoice.amount_due,
        link=link,
        invoice=invoice,
    )

    if not result.get("messages"):

        error_message = (
            result.get("error", {})
            .get("message", "Unknown WhatsApp error")
        )

        CommunicationLog.objects.create(
            channel=CommunicationLog.CHANNEL_WHATSAPP,
            status=CommunicationLog.STATUS_FAILED,
            recipient_name=client_name,
            recipient_contact=phone,
            subject=f"Invoice INV-{invoice.id}",
            message=(
                f"Failed WhatsApp invoice send.\n"
                f"Invoice ID: {invoice.id}\n"
                f"Link: {link}"
            ),
            related_model="Invoice",
            related_object_id=invoice.id,
            provider="Meta WhatsApp Cloud API",
            provider_response=result,
            error_message=error_message,
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "error": error_message,
            "result": result,
        }, status=400)

    message_id = result["messages"][0].get("id")

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_WHATSAPP,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Invoice INV-{invoice.id}",
        message=(
            f"Invoice sent via WhatsApp.\n"
            f"Invoice ID: {invoice.id}\n"
            f"Link: {link}"
        ),
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="Meta WhatsApp Cloud API",
        provider_message_id=message_id,
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Invoice sent successfully.",
        "whatsapp_message_id": message_id,
        "result": result,
    })


@login_required
@require_POST
def send_invoice_sms_view(request, pk):

    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "order"),
        pk=pk,
    )

    client = invoice.client

    phone = (
        request.POST.get("phone")
        or getattr(client, "phone", "")
        or getattr(client, "whatsapp", "")
        or ""
    ).strip()

    if not phone:
        return JsonResponse({
            "success": False,
            "error": "No mobile number found."
        }, status=400)

    client_name = (
        getattr(client, "organization", None)
        or getattr(client, "name", None)
        or "Client"
    )

    link = (
        f"{settings.SITE_URL}/invoices/public/"
        f"{invoice.public_token}/"
    )

    message = (
        f"Hi {client_name}, your The Daily Market invoice "
        f"INV-{invoice.id} is ready. "
        f"Amount due R{invoice.amount_due:.2f}. "
        f"View/pay: {link}"
    )

    result = send_sms(
        to=phone,
        message=message,
    )

    if not result.get("success"):

        CommunicationLog.objects.create(
            channel=CommunicationLog.CHANNEL_SMS,
            status=CommunicationLog.STATUS_FAILED,
            recipient_name=client_name,
            recipient_contact=phone,
            subject=f"Invoice INV-{invoice.id}",
            message=message,
            related_model="Invoice",
            related_object_id=invoice.id,
            provider="SMSPortal",
            provider_response=result,
            error_message=str(result.get("response")),
            sent_by=request.user,
        )

        return JsonResponse({
            "success": False,
            "error": "SMS failed to send.",
            "result": result,
        }, status=400)

    CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_SMS,
        status=CommunicationLog.STATUS_SENT,
        recipient_name=client_name,
        recipient_contact=phone,
        subject=f"Invoice INV-{invoice.id}",
        message=message,
        related_model="Invoice",
        related_object_id=invoice.id,
        provider="SMSPortal",
        provider_response=result,
        sent_by=request.user,
        sent_at=timezone.now(),
    )

    return JsonResponse({
        "success": True,
        "message": "Invoice sent successfully via SMS.",
        "result": result,
    })



@login_required
def commission_rep_detail(request, user_id):
    today = localdate()

    selected_month = int(request.GET.get("month", today.month))
    selected_year = int(request.GET.get("year", today.year))
    selected_area = request.GET.get("area", "")

    month_code = calendar.month_abbr[selected_month].upper()

    first_day = date(selected_year, selected_month, 1)
    last_day = date(
        selected_year,
        selected_month,
        calendar.monthrange(selected_year, selected_month)[1],
    )

    rep_user = get_object_or_404(User, id=user_id)

    commission_entries = (
        CommissionEntry.objects
        .select_related("invoice", "client", "rep", "supervisor")
        .filter(
            rep=rep_user,
            created_at__date__gte=first_day,
            created_at__date__lte=last_day,
        )
        .order_by("-created_at")
    )

    if selected_area:
        commission_entries = commission_entries.filter(client__area=selected_area)

    rep_total = (
        commission_entries.aggregate(t=Sum("rep_amount"))["t"]
        or Decimal("0.00")
    )

    bonus_total = (
        commission_entries
        .filter(is_new_business=True)
        .aggregate(t=Sum("rep_amount"))["t"]
        or Decimal("0.00")
    )

    revenue_total = (
        commission_entries.aggregate(t=Sum("invoice__order_total_inc"))["t"]
        or Decimal("0.00")
    )

    client_count = (
        commission_entries
        .values("client_id")
        .exclude(client_id=None)
        .distinct()
        .count()
    )

    # =========================
    # CLIENT TARGET PROGRESS
    # =========================
    allocation = (
        MonthlyTargetAllocation.objects
        .select_related("monthly_target")
        .filter(
            sales_rep=rep_user,
            monthly_target__year=selected_year,
            monthly_target__month=month_code,
        )
    )

    if selected_area:
        allocation = allocation.filter(monthly_target__area=selected_area)

    allocation = allocation.first()

    client_target = allocation.client_target if allocation else 0

    client_target_pct = (
        (Decimal(client_count) / Decimal(client_target)) * Decimal("100")
        if client_target > 0 else Decimal("0.00")
    )

    clients_needed_for_bonus = max(client_target - client_count, 0)
    bonus_active = client_count > client_target if client_target else False

    # =========================
    # COMMISSION TREND - FULL SELECTED YEAR
    # =========================
    commission_trend_labels = []
    commission_trend_data = []

    selected_trend_index = selected_month - 1

    for month in range(1, 13):
        start = date(selected_year, month, 1)
        end = date(selected_year, month, calendar.monthrange(selected_year, month)[1])

        qs = CommissionEntry.objects.filter(
            rep=rep_user,
            created_at__date__gte=start,
            created_at__date__lte=end,
        )

        totals = qs.aggregate(
            rep_total=Coalesce(
                Sum("rep_amount"),
                Decimal("0.00"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            supervisor_total=Coalesce(
                Sum("supervisor_amount"),
                Decimal("0.00"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )

        month_total = (
            totals["rep_total"] + totals["supervisor_total"]
        ).quantize(Decimal("0.01"))

        commission_trend_labels.append(
            f"{calendar.month_abbr[month]} {selected_year}"
        )

        commission_trend_data.append(float(month_total))

    # =========================
    # FILTER OPTIONS
    # =========================
    months = [
        {"value": i, "label": calendar.month_name[i]}
        for i in range(1, 13)
    ]

    years = list(range(today.year - 2, today.year + 3))

    context = {
        "rep_user": rep_user,
        "commission_entries": commission_entries,

        "selected_month": selected_month,
        "selected_year": selected_year,
        "selected_area": selected_area,
        "selected_month_name": calendar.month_name[selected_month],

        "months": months,
        "years": years,

        "rep_total": rep_total,
        "bonus_total": bonus_total,
        "revenue_total": revenue_total,
        "client_count": client_count,

        "client_target": client_target,
        "client_target_pct": client_target_pct,
        "clients_needed_for_bonus": clients_needed_for_bonus,
        "bonus_active": bonus_active,

        "commission_trend_labels": commission_trend_labels,
        "commission_trend_data": commission_trend_data,
        "selected_trend_index": selected_trend_index,
    }

    return render(request, "commission/commission_rep_detail.html", context)


@login_required
def create_ticket(request):

    if request.method == "POST":

        form = TicketCreateForm(
            request.POST
        )

        if form.is_valid():

            ticket = form.save(
                commit=False
            )

            ticket.created_by = request.user
            ticket.source = Ticket.Source.INTERNAL
            ticket.status = Ticket.Status.NEW

            if ticket.status == Ticket.Status.OPEN:
                ticket.opened_at = timezone.now()

            ticket.save()

            messages.success(
                request,
                "Ticket created successfully."
            )

            return redirect(
                "sales:view-ticket",
                pk=ticket.pk
            )

        messages.error(
            request,
            "Please correct the errors below."
        )

    else:

        sales_operator = None

        try:
            sales_rep_profile = request.user.sales_rep_profile

            sales_operator = getattr(
                sales_rep_profile,
                "sales_operator",
                None,
            )

        except Exception:
            sales_operator = None

        initial = {
            "requester_name": (
                request.user.get_full_name()
                or request.user.username
            ),
            "requester_email": request.user.email,
            "sales_operator": sales_operator,
        }

        form = TicketCreateForm(
            initial=initial
        )

    context = {
        "form": form,
        "page_title": "Create Ticket",
    }

    return render(
        request,
        "tickets/create_ticket.html",
        context,
    )