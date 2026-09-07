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
from clients.models import Prospect, ProspectUpdate, Client, Lead
from clients.forms import ProspectForm, ProspectUpdateForm
from django.utils.timezone import localdate
from invoices.models import CommissionEntry, Invoice, MonthlyTarget, MonthlyTargetAllocation, MonthlyCommission
from products.models import Category, Product, ProductKnowledge
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
from communications.models import CommunicationLog, CommunicationDocs
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
from clients.models import Client, Region, Territory, Area
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
from clients.models import (
    Lead,
    Territory,
    Area,
)
from clients.models import LeadActivity
from django.shortcuts import get_object_or_404, redirect, render
from invoices.models import CommissionEntry, MonthlyTarget
from profiles.models import SalesRepProfile
from clients.forms import ProspectForm, ProspectUpdateForm, LeadForm
User = get_user_model()
User = get_user_model()
DAY_OPTIONS = [7, 14, 30, 60]





@login_required
def sales_dashboard(request):
    user = request.user
    now_dt = timezone.now()
    today = timezone.localdate()

    # =====================================================
    # ROLE / VISIBILITY
    #
    # ONLY a user whose sole role is Representative is
    # restricted to their own data.
    #
    # Supervisor + Representative = unrestricted
    # Supervisor only              = unrestricted
    # Management                   = unrestricted
    # =====================================================

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # =====================================================
    # DATE RANGE
    # =====================================================

    range_param = request.GET.get("range", "today")

    def month_start(d):
        return d.replace(day=1)

    def previous_month_start(d):
        if d.month == 1:
            return d.replace(
                year=d.year - 1,
                month=12,
                day=1
            )

        return d.replace(
            month=d.month - 1,
            day=1
        )

    def next_month_start(d):
        if d.month == 12:
            return d.replace(
                year=d.year + 1,
                month=1,
                day=1
            )

        return d.replace(
            month=d.month + 1,
            day=1
        )

    if range_param == "7d":

        start_dt = now_dt - timedelta(days=7)
        end_dt = now_dt

        prev_start_dt = start_dt - timedelta(days=7)
        prev_end_dt = start_dt

        period_label = "Last 7 days"
        comparison_label = "Previous 7 days"

    elif range_param == "month":

        start_date = today.replace(day=1)

        start_dt = timezone.make_aware(
            datetime.combine(
                start_date,
                datetime.min.time()
            )
        )

        end_dt = now_dt

        prev_start_date = previous_month_start(
            start_date
        )

        prev_start_dt = timezone.make_aware(
            datetime.combine(
                prev_start_date,
                datetime.min.time()
            )
        )

        prev_end_dt = (
            prev_start_dt
            + (end_dt - start_dt)
        )

        period_label = "This month"
        comparison_label = "Previous month"

    elif range_param == "last_month":

        this_month_start = today.replace(day=1)

        last_month_start = previous_month_start(
            this_month_start
        )

        month_before_start = previous_month_start(
            last_month_start
        )

        start_dt = timezone.make_aware(
            datetime.combine(
                last_month_start,
                datetime.min.time()
            )
        )

        end_dt = timezone.make_aware(
            datetime.combine(
                this_month_start,
                datetime.min.time()
            )
        )

        prev_start_dt = timezone.make_aware(
            datetime.combine(
                month_before_start,
                datetime.min.time()
            )
        )

        prev_end_dt = start_dt

        period_label = "Last month"
        comparison_label = "Month before"

    else:

        range_param = "today"

        start_dt = now_dt.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

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

            percent = round(
                (diff / previous_value) * 100,
                1
            )

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
    #
    # REP ONLY:
    #     Own prospects
    #
    # SUPERVISOR / MANAGEMENT:
    #     All prospects
    # =====================================================

    prospects_current_qs = Prospect.objects.filter(
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )

    prospects_previous_qs = Prospect.objects.filter(
        created_at__gte=prev_start_dt,
        created_at__lt=prev_end_dt,
    )

    if rep_only:

        prospects_current_qs = (
            prospects_current_qs.filter(
                owner=user
            )
        )

        prospects_previous_qs = (
            prospects_previous_qs.filter(
                owner=user
            )
        )

    prospects_current = prospects_current_qs.count()
    prospects_previous = prospects_previous_qs.count()

    prospects_trend = build_trend(
        prospects_current,
        prospects_previous
    )

    active_pipeline_qs = (
        Prospect.objects
        .filter(status="ACTIVE")
        .exclude(
            stage__in=["WON", "LOST"]
        )
    )

    if rep_only:
        active_pipeline_qs = active_pipeline_qs.filter(
            owner=user
        )

    active_pipeline_total = (
        active_pipeline_qs.count()
    )

    # =====================================================
    # NEW CLIENTS
    #
    # REP ONLY:
    #     Clients assigned to rep
    #
    # SUPERVISOR / MANAGEMENT:
    #     All clients
    # =====================================================

    new_clients_current_qs = Client.objects.filter(
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )

    new_clients_previous_qs = Client.objects.filter(
        created_at__gte=prev_start_dt,
        created_at__lt=prev_end_dt,
    )

    active_clients_qs = Client.objects.filter(
        status="ACTIVE"
    )

    if rep_only:

        new_clients_current_qs = (
            new_clients_current_qs.filter(
                account_manager=user
            )
        )

        new_clients_previous_qs = (
            new_clients_previous_qs.filter(
                account_manager=user
            )
        )

        active_clients_qs = (
            active_clients_qs.filter(
                account_manager=user
            )
        )

    new_clients_current = (
        new_clients_current_qs.count()
    )

    new_clients_previous = (
        new_clients_previous_qs.count()
    )

    new_clients_trend = build_trend(
        new_clients_current,
        new_clients_previous
    )

    active_clients_overall = (
        active_clients_qs.count()
    )

    # =====================================================
    # CONVERSION RATE
    #
    # REP ONLY:
    #     Own prospects
    #
    # SUPERVISOR / MANAGEMENT:
    #     All prospects
    # =====================================================

    prospects_converted_current_qs = (
        Prospect.objects
        .filter(
            client__isnull=False,
            updated_at__gte=start_dt,
            updated_at__lt=end_dt,
        )
    )

    if rep_only:
        prospects_converted_current_qs = (
            prospects_converted_current_qs.filter(
                owner=user
            )
        )

    prospects_converted_current = (
        prospects_converted_current_qs.count()
    )

    if prospects_current > 0:

        conversion_rate = round(
            (
                prospects_converted_current
                / prospects_current
            ) * 100,
            1
        )

    else:

        conversion_rate = 0

    # =====================================================
    # ORDERS
    #
    # REP ONLY:
    #     Orders created by the rep
    #
    # SUPERVISOR / MANAGEMENT:
    #     ALL orders
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
            ts__gte=prev_start_dt,
            ts__lt=prev_end_dt,
        )
    )

    if rep_only:

        orders_qs = orders_qs.filter(
            created_by=user
        )

        previous_orders_qs = (
            previous_orders_qs.filter(
                created_by=user
            )
        )

    orders_closed_count = orders_qs.count()

    # =====================================================
    # ORDER TREND GRAPH
    # =====================================================

    day_counts = OrderedDict()

    day_cursor = start_dt.date()

    end_day = (
        end_dt - timedelta(seconds=1)
    ).date()

    while day_cursor <= end_day:

        day_counts[day_cursor] = 0

        day_cursor += timedelta(days=1)

    for ts in orders_qs.values_list(
        "ts",
        flat=True
    ):

        if ts:

            order_day = ts.date()

            if order_day in day_counts:

                day_counts[order_day] += 1

    sales_labels = [
        d.strftime("%d %b")
        for d in day_counts.keys()
    ]

    sales_data = list(
        day_counts.values()
    )

    # =====================================================
    # INVOICES
    #
    # REP ONLY:
    #     Invoices belonging to their clients
    #
    # SUPERVISOR / MANAGEMENT:
    #     ALL invoices
    # =====================================================

    invoices_qs = Invoice.objects.filter(
        invoice_date__gte=start_dt.date(),
        invoice_date__lt=(
            end_dt.date() + timedelta(days=1)
        ),
    )

    previous_invoices_qs = Invoice.objects.filter(
        invoice_date__gte=prev_start_dt.date(),
        invoice_date__lt=(
            prev_end_dt.date() + timedelta(days=1)
        ),
    )

    if rep_only:

        invoices_qs = invoices_qs.filter(
            client__account_manager=user
        )

        previous_invoices_qs = (
            previous_invoices_qs.filter(
                client__account_manager=user
            )
        )

    # =====================================================
    # CLIENT INVOICE DATA
    # =====================================================

    current_clients_invoice_data = (
        invoices_qs
        .values(
            "client_id",
            "client__name",
            "client__organization"
        )
        .annotate(
            invoice_count=Count("id"),

            invoice_value=Coalesce(
                Sum("order_total_inc"),
                Value(Decimal("0.00")),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2
                ),
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
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2
                ),
            ),
        )
    )

    previous_client_map = {
        row["client_id"]: row
        for row in previous_clients_invoice_data
    }

    client_rows = []

    for row in current_clients_invoice_data:

        previous = previous_client_map.get(
            row["client_id"],
            {}
        )

        invoice_count = (
            row["invoice_count"] or 0
        )

        previous_invoice_count = (
            previous.get(
                "invoice_count",
                0
            ) or 0
        )

        invoice_value = (
            row["invoice_value"]
            or Decimal("0.00")
        )

        previous_invoice_value = (
            previous.get(
                "invoice_value",
                Decimal("0.00")
            )
            or Decimal("0.00")
        )

        client_rows.append({

            "client_id":
                row["client_id"],

            "client_name":
                row["client__name"],

            "client_organization":
                row["client__organization"],

            "invoice_count":
                invoice_count,

            "invoice_value":
                invoice_value,

            "quantity_trend":
                build_trend(
                    invoice_count,
                    previous_invoice_count
                ),

            "value_trend":
                build_trend(
                    float(invoice_value),
                    float(previous_invoice_value)
                ),
        })

    # =====================================================
    # TOP CLIENTS
    # =====================================================

    top_clients_by_invoice_quantity = sorted(
        client_rows,
        key=lambda x: (
            x["invoice_count"],
            x["invoice_value"]
        ),
        reverse=True
    )[:5]

    top_clients_by_invoice_value = sorted(
        client_rows,
        key=lambda x: (
            x["invoice_value"],
            x["invoice_count"]
        ),
        reverse=True
    )[:5]

    # =====================================================
    # TOP PRODUCTS
    #
    # REP ONLY:
    #     Products from own orders
    #
    # SUPERVISOR / MANAGEMENT:
    #     Products from ALL orders
    # =====================================================

    current_products_data = (
        OrderItem.objects
        .filter(
            order_id__in=orders_qs.values("id")
        )
        .values(
            "product_id",
            "product_name"
        )
        .annotate(
            quantity_sold=Coalesce(
                Sum("quantity"),
                Value(Decimal("0.00")),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2
                ),
            ),
        )
    )

    previous_products_data = (
        OrderItem.objects
        .filter(
            order_id__in=previous_orders_qs.values("id")
        )
        .values("product_id")
        .annotate(
            quantity_sold=Coalesce(
                Sum("quantity"),
                Value(Decimal("0.00")),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2
                ),
            ),
        )
    )

    previous_product_map = {
        row["product_id"]:
            row["quantity_sold"]
            or Decimal("0.00")
        for row in previous_products_data
    }

    product_rows = []

    for row in current_products_data:

        current_qty = (
            row["quantity_sold"]
            or Decimal("0.00")
        )

        previous_qty = (
            previous_product_map.get(
                row["product_id"],
                Decimal("0.00")
            )
        )

        product_rows.append({

            "product_id":
                row["product_id"],

            "product_name":
                row["product_name"],

            "quantity_sold":
                current_qty,

            "quantity_trend":
                build_trend(
                    float(current_qty),
                    float(previous_qty)
                ),
        })

    top_products = sorted(
        product_rows,
        key=lambda x: x["quantity_sold"],
        reverse=True
    )[:5]

    # =====================================================
    # CONTEXT
    # =====================================================

    context = {

        # -------------------------------------------------
        # Date range
        # -------------------------------------------------

        "range":
            range_param,

        "period_label":
            period_label,

        "comparison_label":
            comparison_label,

        # -------------------------------------------------
        # Visibility
        # -------------------------------------------------

        "rep_only":
            rep_only,

        # -------------------------------------------------
        # Prospects
        # -------------------------------------------------

        "prospects_trend":
            prospects_trend,

        "prospects_converted_current":
            prospects_converted_current,

        "active_pipeline_total":
            active_pipeline_total,

        # -------------------------------------------------
        # Clients
        # -------------------------------------------------

        "new_clients_trend":
            new_clients_trend,

        "active_clients_overall":
            active_clients_overall,

        # -------------------------------------------------
        # Conversion
        # -------------------------------------------------

        "conversion_rate":
            conversion_rate,

        # -------------------------------------------------
        # Orders
        # -------------------------------------------------

        "orders_closed_count":
            orders_closed_count,

        "sales_labels":
            sales_labels,

        "sales_data":
            sales_data,

        # -------------------------------------------------
        # Top clients
        # -------------------------------------------------

        "top_clients_by_invoice_quantity":
            top_clients_by_invoice_quantity,

        "top_clients_by_invoice_value":
            top_clients_by_invoice_value,

        # -------------------------------------------------
        # Top products
        # -------------------------------------------------

        "top_products":
            top_products,
    }

    return render(
        request,
        "sales/dashboard.html",
        context
    )





@login_required
def leads(request):
    """
    Sales Leads pipeline.

    Leads are captured before they become Prospects.
    This is the Sales-facing view of the existing Lead model.

    Lead visibility rules:
        - A user whose ONLY role is Representative can see
          only leads assigned to themselves.
        - Users with any other role can see all leads.
    """

    # ==========================================================
    # CURRENT DATE
    # ==========================================================

    today = timezone.localdate()

    # Monday of the current week
    week_start = today - timedelta(days=today.weekday())

    # ==========================================================
    # DATE FILTERS
    # Default:
    #   From = Monday of current week
    #   To   = today
    # ==========================================================

    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()

    try:
        selected_date_from = date.fromisoformat(date_from)
    except (ValueError, TypeError):
        selected_date_from = week_start

    try:
        selected_date_to = date.fromisoformat(date_to)
    except (ValueError, TypeError):
        selected_date_to = today

    # If the user selects an invalid range,
    # return to the current week.
    if selected_date_from > selected_date_to:
        selected_date_from = week_start
        selected_date_to = today

    # ==========================================================
    # BASE QUERYSET
    # ==========================================================

    qs = (
        Lead.objects
        .select_related(
            "assigned_to",
            "created_by",
            "prospect",
            "region",
            "territory",
            "area",
        )
        .prefetch_related(
            "product_interests",
            "activities__user",
        )
        .order_by("-created_at")
    )

    # ==========================================================
    # REP-ONLY VISIBILITY
    #
    # If the logged-in user has ONLY the Representative role,
    # they may see ONLY leads assigned to themselves.
    #
    # If they have any other role as well, they can see all leads.
    # ==========================================================

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # User is a REP ONLY if:
    #
    #   1. They have a SalesRepProfile
    #   2. Their roles contain Representative
    #   3. They have no other role
    #
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    if rep_only:
        qs = qs.filter(
            assigned_to=request.user
        )

    # ==========================================================
    # DATE RANGE
    #
    # Use datetime boundaries instead of __date so that the
    # complete selected days are included.
    # ==========================================================

    start_datetime = datetime.combine(
        selected_date_from,
        datetime.min.time(),
    )

    end_datetime = datetime.combine(
        selected_date_to + timedelta(days=1),
        datetime.min.time(),
    )

    # Make the datetimes timezone-aware when USE_TZ=True
    if timezone.is_naive(start_datetime):
        start_datetime = timezone.make_aware(
            start_datetime,
            timezone.get_current_timezone(),
        )

    if timezone.is_naive(end_datetime):
        end_datetime = timezone.make_aware(
            end_datetime,
            timezone.get_current_timezone(),
        )

    qs = qs.filter(
        created_at__gte=start_datetime,
        created_at__lt=end_datetime,
    )

    # ==========================================================
    # SEARCH
    # ==========================================================

    q = (request.GET.get("q") or "").strip()

    if q:
        qs = qs.filter(
            Q(lead_number__icontains=q)
            | Q(business_name__icontains=q)
            | Q(contact_person__icontains=q)
            | Q(phone__icontains=q)
            | Q(whatsapp__icontains=q)
            | Q(email__icontains=q)
        )

    # ==========================================================
    # TERRITORY
    # ==========================================================

    territory_id = (request.GET.get("territory") or "").strip()

    if territory_id:
        qs = qs.filter(
            territory_id=territory_id
        )

    # ==========================================================
    # AREA
    # ==========================================================

    area_id = (request.GET.get("area") or "").strip()

    if area_id:
        qs = qs.filter(
            area_id=area_id
        )

    # ==========================================================
    # SALES REP / ACCOUNT MANAGER
    # ==========================================================

    assigned_to_id = (
        request.GET.get("assigned_to") or ""
    ).strip()

    if assigned_to_id:

        if rep_only:
            # A REP-ONLY user cannot override the visibility
            # restriction by changing the URL.
            qs = qs.filter(
                assigned_to=request.user
            )

        else:
            qs = qs.filter(
                assigned_to_id=assigned_to_id
            )

    # ==========================================================
    # STATUS
    # ==========================================================

    status = (
        request.GET.get("status") or ""
    ).strip().upper()

    valid_statuses = {
        code
        for code, _ in Lead.STATUS_CHOICES
    }

    if status and status in valid_statuses:
        qs = qs.filter(
            status=status
        )

    # ==========================================================
    # FILTER OPTIONS
    # ==========================================================

    # ----------------------------------------------------------
    # Territories
    # ----------------------------------------------------------

    filter_territories = (
        Territory.objects
        .filter(
            status="ACTIVE"
        )
        .select_related(
            "region"
        )
        .order_by(
            "region__name",
            "name",
        )
    )

    # ----------------------------------------------------------
    # Areas
    # ----------------------------------------------------------

    filter_areas = (
        Area.objects
        .filter(
            status="ACTIVE"
        )
        .select_related(
            "territory"
        )
        .order_by(
            "territory__name",
            "name",
        )
    )

    # ----------------------------------------------------------
    # Sales Reps / Account Managers
    #
    # Only users who:
    #   1. Are active
    #   2. Have a SalesRepProfile
    #   3. Have Representative OR Supervisor role
    #
    # For a REP-ONLY logged-in user:
    #   Only themselves are shown.
    # ----------------------------------------------------------

    if rep_only:

        filter_sales_reps = (
            SalesRepProfile.objects
            .filter(
                user=request.user,
                user__is_active=True,
            )
            .select_related(
                "user",
            )
            .prefetch_related(
                "roles",
            )
        )

    else:

        filter_sales_reps = (
            SalesRepProfile.objects
            .filter(
                user__is_active=True,
                roles__name__in=[
                    "Representative",
                    "Supervisor",
                ],
            )
            .select_related(
                "user",
            )
            .prefetch_related(
                "roles",
            )
            .distinct()
            .order_by(
                "user__first_name",
                "user__last_name",
                "user__username",
            )
        )

    # ==========================================================
    # SUMMARY
    # ==========================================================

    # These counts respect:
    #   - REP visibility
    #   - Date range
    #   - Search
    #   - Territory
    #   - Area
    #   - Assigned user
    #   - Status

    leads_total = qs.count()

    new_leads = qs.filter(
        status="NEW"
    ).count()

    contacted_leads = qs.filter(
        status="CONTACTED"
    ).count()

    qualified_leads = qs.filter(
        status="QUALIFIED"
    ).count()

    disqualified_leads = qs.filter(
        status="DISQUALIFIED"
    ).count()

    converted_leads = qs.filter(
        status="CONVERTED"
    ).count()

    # ==========================================================
    # CONTEXT
    # ==========================================================

    context = {
        "leads": qs,

        # ------------------------------------------------------
        # Summary
        # ------------------------------------------------------

        "leads_total": leads_total,
        "new_leads": new_leads,
        "contacted_leads": contacted_leads,
        "qualified_leads": qualified_leads,
        "disqualified_leads": disqualified_leads,
        "converted_leads": converted_leads,

        # ------------------------------------------------------
        # Filter choices
        # ------------------------------------------------------

        "statuses": Lead.STATUS_CHOICES,
        "sources": Lead.SOURCE_CHOICES,

        # ------------------------------------------------------
        # Filter options
        # ------------------------------------------------------

        "filter_territories": filter_territories,
        "filter_areas": filter_areas,
        "filter_sales_reps": filter_sales_reps,

        # ------------------------------------------------------
        # Selected filters
        # ------------------------------------------------------

        "selected_territory": territory_id,
        "selected_area": area_id,
        "selected_assigned_to": assigned_to_id,

        # ------------------------------------------------------
        # Date filters
        # ------------------------------------------------------

        "selected_date_from": selected_date_from,
        "selected_date_to": selected_date_to,
        "today": today,

        # ------------------------------------------------------
        # Visibility information
        # ------------------------------------------------------

        "rep_only": rep_only,
    }

    # ==========================================================
    # RENDER
    # ==========================================================

    return render(
        request,
        "leads/leads_list.html",
        context,
    )

@login_required
def lead_create(request):
    """
    Create a new Lead from the Sales portal.
    """

    if request.method == "POST":
        form = LeadForm(request.POST)

        if form.is_valid():
            lead = form.save(commit=False)

            # The person creating the lead
            lead.created_by = request.user

            # Default new leads to NEW unless the form explicitly
            # provides another valid status.
            if not lead.status:
                lead.status = "NEW"

            lead.save()

            messages.success(
                request,
                f"Lead {lead.lead_number} created successfully.",
            )

            return redirect(
                "sales:sales-lead-view",
                pk=lead.pk,
            )

        messages.error(
            request,
            "Please correct the errors below.",
        )

    else:
        form = LeadForm()

    return render(
        request,
        "leads/lead_create.html",
        {
            "form": form,
            "title": "Create Lead",
        },
    )



@login_required
def lead_view(request, pk):
    """
    Sales Lead detail page.
    """

    lead = get_object_or_404(
        Lead.objects.select_related(
            "assigned_to",
            "created_by",
            "prospect",
        ).prefetch_related(
            "product_interests",
            "activities__user",
        ),
        pk=pk,
    )

    return render(
        request,
        "leads/lead_detail.html",
        {
            "lead": lead,
        },
    )


@login_required
def lead_edit(request, pk):
    """
    Edit an existing sales lead.
    """

    lead = get_object_or_404(Lead, pk=pk)

    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead)

        if form.is_valid():
            lead = form.save()

            return redirect(
                "sales:sales-lead-view",
                pk=lead.pk,
            )

    else:
        form = LeadForm(instance=lead)

    return render(
        request,
        "leads/lead_edit.html",
        {
            "lead": lead,
            "form": form,
        },
    )


@login_required
def lead_convert_to_prospect(request, pk):

    lead = get_object_or_404(
        Lead,
        pk=pk,
    )

    prospect = lead.convert_to_prospect()

    messages.success(
        request,
        f"{lead.business_name or lead.contact_person} has been converted to a prospect.",
    )

    return redirect(
        "sales:sales-lead-view",
        pk=lead.pk,
    )




@login_required
def prospects(request):
    """
    Sales prospects pipeline.

    Visibility rules:
        - A user whose ONLY role is Representative can see
          only prospects assigned to themselves.
        - Users with any other role can see all prospects.

    Filters:
        - Date range
        - Search
        - Stage
        - Status
    """

    # ==========================================================
    # CURRENT USER / ROLE
    # ==========================================================

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(
                user=request.user
            )
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:

        current_profile = None
        current_role_names = set()

    # ==========================================================
    # REP-ONLY CHECK
    #
    # ONLY a user whose complete role set is:
    #
    #     {"Representative"}
    #
    # is restricted to their own prospects.
    #
    # Representative + Supervisor = ALL
    # Representative + Manager    = ALL
    # Supervisor                  = ALL
    # Manager                     = ALL
    # ==========================================================

    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # ==========================================================
    # CURRENT DATE
    # ==========================================================

    today = timezone.localdate()

    # Monday of the current week
    week_start = today - timedelta(
        days=today.weekday()
    )

    # ==========================================================
    # DATE FILTERS
    #
    # Default:
    #   From = Monday of current week
    #   To   = today
    # ==========================================================

    date_from = (
        request.GET.get("date_from") or ""
    ).strip()

    date_to = (
        request.GET.get("date_to") or ""
    ).strip()

    try:
        selected_date_from = date.fromisoformat(
            date_from
        )
    except (ValueError, TypeError):

        selected_date_from = week_start

    try:
        selected_date_to = date.fromisoformat(
            date_to
        )
    except (ValueError, TypeError):

        selected_date_to = today

    # ----------------------------------------------------------
    # If dates are reversed, reset to current week
    # ----------------------------------------------------------

    if selected_date_from > selected_date_to:

        selected_date_from = week_start
        selected_date_to = today

    # ==========================================================
    # BASE QUERYSET
    # ==========================================================

    qs = (
        Prospect.objects
        .select_related(
            "owner",
            "territory",
            "area",
        )
    )

    # ==========================================================
    # REP-ONLY VISIBILITY
    #
    # This is applied directly to the queryset.
    #
    # A Representative therefore cannot bypass the restriction
    # by changing URL parameters.
    # ==========================================================

    if rep_only:

        qs = qs.filter(
            owner=request.user
        )

    # ==========================================================
    # DATE RANGE
    #
    # Use datetime boundaries so the complete selected days
    # are included.
    # ==========================================================

    start_datetime = datetime.combine(
        selected_date_from,
        datetime.min.time(),
    )

    end_datetime = datetime.combine(
        selected_date_to + timedelta(days=1),
        datetime.min.time(),
    )

    # Make timezone-aware when USE_TZ=True
    if timezone.is_naive(start_datetime):

        start_datetime = timezone.make_aware(
            start_datetime,
            timezone.get_current_timezone(),
        )

    if timezone.is_naive(end_datetime):

        end_datetime = timezone.make_aware(
            end_datetime,
            timezone.get_current_timezone(),
        )

    qs = qs.filter(
        created_at__gte=start_datetime,
        created_at__lt=end_datetime,
    )

    # ==========================================================
    # SEARCH
    # ==========================================================

    q = (
        request.GET.get("q") or ""
    ).strip()

    if q:

        qs = qs.filter(
            Q(name__icontains=q)
            | Q(organization__icontains=q)
            | Q(contact_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(whatsapp__icontains=q)
            | Q(email__icontains=q)
            | Q(notes__icontains=q)
            | Q(territory__name__icontains=q)
            | Q(area__name__icontains=q)
        )

    # ==========================================================
    # STAGE FILTER
    # ==========================================================

    stage_filter = (
        request.GET.get("stage") or ""
    ).strip().upper()

    valid_stages = {
        code
        for code, _ in Prospect.STAGE_CHOICES
    }

    if (
        stage_filter
        and stage_filter in valid_stages
    ):

        qs = qs.filter(
            stage=stage_filter
        )

    # ==========================================================
    # STATUS FILTER
    # ==========================================================

    status_filter = (
        request.GET.get("status") or ""
    ).strip().upper()

    valid_statuses = {
        code
        for code, _ in Prospect.STATUS_CHOICES
    }

    if (
        status_filter
        and status_filter in valid_statuses
    ):

        qs = qs.filter(
            status=status_filter
        )

    # ==========================================================
    # TOTAL AFTER FILTERS
    # ==========================================================

    prospects_total = qs.count()

    # ==========================================================
    # PIPELINE SUMMARY
    # ==========================================================

    stage_label_map = dict(
        Prospect.STAGE_CHOICES
    )

    pipeline_raw = (
        qs
        .values("stage")
        .annotate(
            count=Count("id")
        )
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

    # ==========================================================
    # FINAL QUERYSET
    # ==========================================================

    prospects_qs = (
        qs
        .order_by("-created_at")
        .distinct()
    )

    # ==========================================================
    # CONTEXT
    # ==========================================================

    context = {
        # ------------------------------------------------------
        # Prospects
        # ------------------------------------------------------

        "prospects": prospects_qs,

        "prospects_total": prospects_total,

        # ------------------------------------------------------
        # Pipeline
        # ------------------------------------------------------

        "pipeline_summary": pipeline_summary,

        # ------------------------------------------------------
        # Current date
        # ------------------------------------------------------

        "today": today,

        # ------------------------------------------------------
        # Date filters
        # ------------------------------------------------------

        "selected_date_from": selected_date_from,

        "selected_date_to": selected_date_to,

        # ------------------------------------------------------
        # Visibility
        # ------------------------------------------------------

        "rep_only": rep_only,
    }

    # ==========================================================
    # RENDER
    # ==========================================================

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
    - product interests save correctly
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
            "product_interests",
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
    qs = (
        Client.objects
        .select_related(
            "account_manager",
            "region",
            "territory",
            "area",
        )
        .prefetch_related("product_interests")
        .order_by("name")
    )

    # -------------------------------------------------
    # ROLE / ACCESS
    # -------------------------------------------------

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # ONLY Representative = rep-only user
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # -------------------------------------------------
    # DROPDOWN DATA
    # -------------------------------------------------

    client_types = Client.CLIENT_TYPES
    provinces = Client.PROVINCES
    account_types = Client.ACCOUNT_TYPES
    credit_statuses = Client.CREDIT_STATUS
    statuses = Client.STATUS

    regions = Region.objects.filter(
        status="ACTIVE"
    ).order_by("name")

    territories = Territory.objects.filter(
        status="ACTIVE"
    ).select_related("region").order_by("name")

    areas = Area.objects.filter(
        status="ACTIVE"
    ).select_related("territory").order_by("name")

    # -------------------------------------------------
    # GET PARAMS
    # -------------------------------------------------

    search = (request.GET.get("search") or "").strip()
    client_type = request.GET.get("client_type") or ""
    province = request.GET.get("province") or ""
    account_type = request.GET.get("account_type") or ""
    credit_status = request.GET.get("credit_status") or ""
    status = request.GET.get("status") or ""
    region_id = request.GET.get("region") or ""
    territory_id = request.GET.get("territory") or ""
    area_id = request.GET.get("area") or ""

    # -------------------------------------------------
    # SEARCH
    # -------------------------------------------------

    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(organization__icontains=search)
            | Q(contact_person__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
            | Q(whatsapp__icontains=search)
            | Q(suburb__icontains=search)
            | Q(city__icontains=search)
        )

    # -------------------------------------------------
    # FILTERS
    # -------------------------------------------------

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

    if region_id.isdigit():
        qs = qs.filter(region_id=int(region_id))

    if territory_id.isdigit():
        qs = qs.filter(territory_id=int(territory_id))

    if area_id.isdigit():
        qs = qs.filter(area_id=int(area_id))

    clients = qs.distinct()

    return render(
        request,
        "clients/clients.html",
        {
            "clients": clients,
            "regions": regions,
            "territories": territories,
            "areas": areas,
            "client_types": client_types,
            "provinces": provinces,
            "account_types": account_types,
            "credit_statuses": credit_statuses,
            "statuses": statuses,

            # Access control
            "rep_only": rep_only,
        },
    )




@login_required
def view_client(request, pk):

    # ---------------------------
    # Core client
    # ---------------------------
    client = get_object_or_404(
        Client.objects
        .select_related(
            "account_manager",
            "funder",
            "region",
            "territory",
            "area",
        )
        .prefetch_related("product_interests"),
        pk=pk
    )

    # ---------------------------
    # Role / Access Control
    # ---------------------------
    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # Only users whose ONLY role is Representative
    # are restricted to their own clients.
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # Rep can only view clients where they are
    # the assigned Account Manager.
    if rep_only and client.account_manager_id != request.user.id:

        messages.error(
            request,
            "You do not have access to this profile."
        )

        return redirect("sales:clients")

    # ---------------------------
    # Orders (tab)
    # ---------------------------
    orders = (
        Order.objects
        .filter(client=client)
        .only(
            "id",
            "order_date",
            "status",
            "grand_total_inc",
        )
        .order_by("-order_date")[:10]
    )

    # ---------------------------
    # Credit (tab)
    # ---------------------------
    credit_account = None
    credit_utilization_pct = None
    credit_utilization_status = None

    if client.account_type == "CREDIT":

        credit_account = (
            CreditAccount.objects
            .filter(client=client)
            .first()
        )

        if credit_account and credit_account.credit_limit > 0:

            credit_utilization_pct = (
                credit_account.credit_used
                / credit_account.credit_limit
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
    compliance = getattr(
        client,
        "compliance",
        None
    )

    compliance_documents = []
    compliance_completion_pct = Decimal("0.00")

    if compliance:

        compliance_documents = (
            compliance.documents
            .all()
            .order_by("document_type")
        )

        total_docs = compliance_documents.count()

        approved_docs = (
            compliance_documents
            .filter(status="APPROVED")
            .count()
        )

        if total_docs > 0:

            compliance_completion_pct = (
                Decimal(approved_docs)
                / Decimal(total_docs)
            ) * Decimal("100.00")

    # ---------------------------
    # Communication (tab)
    # ---------------------------
    communication_logs = (
        CommunicationLog.objects
        .filter(
            related_model="Client",
            related_object_id=client.id,
        )
        .select_related("sent_by")
        .order_by("-created_at")
    )

    # ---------------------------
    # Communication Documents (Docs tab)
    # ---------------------------
    communication_docs = (
        CommunicationDocs.objects
        .filter(
            communication__related_model="Client",
            communication__related_object_id=client.id,
        )
        .select_related("communication")
        .order_by("-created_at")
    )

    # ---------------------------
    # Overview KPIs
    # ---------------------------
    total_spend = (
        Order.objects
        .filter(client=client)
        .aggregate(
            s=Coalesce(
                Sum("grand_total_inc"),
                Decimal("0.00")
            )
        )["s"]
    )

    days_active = (
        timezone.now().date()
        - client.created_at.date()
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
        .order_by(
            "-total_spend",
            "id"
        )
        .values_list(
            "id",
            flat=True
        )
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

        # Communication
        "communication_logs": communication_logs,

        # Docs
        "communication_docs": communication_docs,

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
        Client.objects
        .select_related(
            "account_manager",
            "region",
            "territory",
            "area",
        )
        .prefetch_related("product_interests"),
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

    # -------------------------------------------------
    # ROLE / ACCESS CONTROL
    # -------------------------------------------------

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # A user is rep-only ONLY when their complete
    # role set is exactly {"Representative"}.
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # -------------------------------------------------
    # BASE QUERYSET
    # -------------------------------------------------

    qs = (
        Quotation.objects
        .select_related(
            "client",
            "client__account_manager",
            "prospect",
            "created_by",
            "accepted_by",
            "converted_order",
        )
        .prefetch_related("items")
        .order_by("-created_at")
    )

    # -------------------------------------------------
    # REP ACCESS
    # -------------------------------------------------

    # Representative-only users can only see quotations
    # belonging to their own clients.
    if rep_only:
        qs = qs.filter(
            client__account_manager=request.user
        )

    # -------------------------------------------------
    # FILTER DROPDOWNS
    # -------------------------------------------------

    statuses = Quotation.STATUS_CHOICES

    # -------------------------------------------------
    # GET PARAMS
    # -------------------------------------------------

    search = (
        request.GET.get("search") or ""
    ).strip()

    status = (
        request.GET.get("status") or ""
    ).strip()

    has_order = (
        request.GET.get("has_order") or ""
    ).strip()

    target_type = (
        request.GET.get("target_type") or ""
    ).strip()

    created_by = (
        request.GET.get("created_by") or ""
    ).strip()

    date_from = (
        request.GET.get("date_from") or ""
    ).strip()

    date_to = (
        request.GET.get("date_to") or ""
    ).strip()

    # -------------------------------------------------
    # SEARCH
    # -------------------------------------------------

    if search:

        qs = qs.filter(

            Q(id__icontains=search)

            | Q(client__name__icontains=search)
            | Q(client__organization__icontains=search)
            | Q(client__contact_person__icontains=search)
            | Q(client__email__icontains=search)
            | Q(client__phone__icontains=search)

            | Q(prospect__name__icontains=search)
            | Q(prospect__organization__icontains=search)
            | Q(prospect__email__icontains=search)
            | Q(prospect__phone__icontains=search)

        )

    # -------------------------------------------------
    # STATUS
    # -------------------------------------------------

    if status:
        qs = qs.filter(
            status=status
        )

    # -------------------------------------------------
    # HAS CONVERTED ORDER
    # -------------------------------------------------

    if has_order == "yes":

        qs = qs.filter(
            converted_order__isnull=False
        )

    elif has_order == "no":

        qs = qs.filter(
            converted_order__isnull=True
        )

    # -------------------------------------------------
    # TARGET TYPE
    # -------------------------------------------------

    if target_type == "client":

        qs = qs.filter(
            client__isnull=False
        )

    elif target_type == "prospect":

        qs = qs.filter(
            prospect__isnull=False
        )

    # -------------------------------------------------
    # CREATED BY
    # -------------------------------------------------

    if created_by.isdigit():

        qs = qs.filter(
            created_by_id=int(created_by)
        )

    # -------------------------------------------------
    # DATE FILTER
    # -------------------------------------------------

    today = timezone.localdate()

    # Default:
    # Monday -> today
    week_start = today - timedelta(
        days=today.weekday()
    )

    try:
        selected_date_from = date.fromisoformat(
            date_from
        )
    except (ValueError, TypeError):
        selected_date_from = week_start

    try:
        selected_date_to = date.fromisoformat(
            date_to
        )
    except (ValueError, TypeError):
        selected_date_to = today

    # If From > To, reset to Monday -> today.
    if selected_date_from > selected_date_to:

        selected_date_from = week_start
        selected_date_to = today

    # -------------------------------------------------
    # DATETIME BOUNDARIES
    # -------------------------------------------------

    # Start of selected From date.
    start_datetime = datetime.combine(
        selected_date_from,
        datetime.min.time(),
    )

    # Start of the day AFTER selected To date.
    #
    # Using __lt__ means the entire selected To date
    # is included.
    end_datetime = datetime.combine(
        selected_date_to + timedelta(days=1),
        datetime.min.time(),
    )

    # Make timezone-aware where required.
    if timezone.is_naive(start_datetime):

        start_datetime = timezone.make_aware(
            start_datetime,
            timezone.get_current_timezone(),
        )

    if timezone.is_naive(end_datetime):

        end_datetime = timezone.make_aware(
            end_datetime,
            timezone.get_current_timezone(),
        )

    # -------------------------------------------------
    # APPLY DATE FILTER
    # -------------------------------------------------

    qs = qs.filter(
        created_at__gte=start_datetime,
        created_at__lt=end_datetime,
    )

    # -------------------------------------------------
    # FINAL DISTINCT
    # -------------------------------------------------

    quotations = qs.distinct()

    # -------------------------------------------------
    # RENDER
    # -------------------------------------------------

    return render(
        request,
        "quotations/quotations.html",
        {
            "quotations": quotations,

            "statuses": statuses,

            "selected_status": status,
            "selected_has_order": has_order,
            "selected_target_type": target_type,
            "selected_created_by": created_by,

            "search": search,

            # Date filter
            "date_from": selected_date_from,
            "date_to": selected_date_to,

            # Role
            "rep_only": rep_only,
        },
    )


@login_required
def view_quotation(request, pk):

    # -------------------------------------------------
    # ROLE / ACCESS CONTROL
    # -------------------------------------------------

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # A user is rep-only ONLY when their complete
    # role set is exactly {"Representative"}.
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # -------------------------------------------------
    # GET QUOTATION
    # -------------------------------------------------

    quotation = get_object_or_404(
        Quotation.objects
        .select_related(
            "client",
            "client__account_manager",
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

    # -------------------------------------------------
    # REP ACCESS CHECK
    # -------------------------------------------------

    # Representative-only users may only access
    # quotations belonging to their own clients.
    #
    # Direct URL access is also protected.
    if (
        rep_only
        and quotation.client_id is not None
        and quotation.client.account_manager_id != request.user.id
    ):
        messages.error(
            request,
            "You do not have access to this quotation."
        )

        return redirect(
            "sales:sales-quotations"
        )

    # -------------------------------------------------
    # TOTALS
    # -------------------------------------------------

    quotation.recalc_totals(
        save=False
    )

    # -------------------------------------------------
    # ITEM ROWS
    # -------------------------------------------------

    item_rows = []

    for item in quotation.items.all().order_by("id"):

        qty = (
            item.quantity
            or Decimal("0.00")
        )

        unit_excl = (
            item.unit_price_excl
            or Decimal("0.00")
        )

        discount_per_unit = (
            item.discount_excl
            or Decimal("0.00")
        )

        vat_pct = (
            item.vat_percent
            or Decimal("0.00")
        )

        gross_excl = (
            unit_excl * qty
        )

        discount_total = (
            discount_per_unit * qty
        )

        line_excl = (
            gross_excl
            - discount_total
        )

        vat_amount = (
            line_excl
            * (
                vat_pct
                / Decimal("100.00")
            )
        )

        line_inc = (
            line_excl
            + vat_amount
        )

        discount_pct = Decimal("0.00")

        if (
            unit_excl > 0
            and discount_per_unit > 0
        ):
            discount_pct = (
                discount_per_unit
                / unit_excl
            ) * Decimal("100.00")

        item_rows.append(
            {
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
            }
        )

    # -------------------------------------------------
    # RENDER
    # -------------------------------------------------

    return render(
        request,
        "quotations/view_quotation.html",
        {
            "quotation": quotation,
            "item_rows": item_rows,
            "rep_only": rep_only,
        },
    )



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
            # Territory
            "region", "territory", "area",

            # Account
            "status", "account_type", "credit_status",
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
            "region": forms.Select(attrs={"class": "form-select"}),
            "territory": forms.Select(attrs={"class": "form-select"}),
            "area": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        

        # Placeholders
        self.fields["email"].widget.attrs.setdefault("placeholder", "name@example.com")
        self.fields["phone"].widget.attrs.setdefault("placeholder", "e.g. 072 123 4567")
        self.fields["whatsapp"].widget.attrs.setdefault("placeholder", "e.g. 072 123 4567")

        # Optional: default to Retail if none chosen yet
        if not self.instance.pk and not self.initial.get("price_type"):
            self.fields["price_type"].initial = "Retail"


@login_required
def orders(request):

    # -------------------------------------------------
    # ROLE / ACCESS CONTROL
    # -------------------------------------------------

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # A user is rep-only ONLY when their complete
    # role set is exactly {"Representative"}.
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # -------------------------------------------------
    # BASE QUERYSET
    # -------------------------------------------------

    qs = (
        Order.objects
        .select_related(
            "client",
            "client__account_manager",
        )
        .prefetch_related("items")
    )

    # -------------------------------------------------
    # REP ACCESS
    # -------------------------------------------------

    # Representative-only users only see orders
    # belonging to their own clients.
    if rep_only:
        qs = qs.filter(
            client__account_manager=request.user
        )

    # -------------------------------------------------
    # OPTIONAL FILTERS
    # -------------------------------------------------

    status = (request.GET.get("status") or "").strip()
    channel = (request.GET.get("channel") or "").strip()
    q = (request.GET.get("q") or "").strip()

    if status:
        qs = qs.filter(status=status)

    if channel:
        qs = qs.filter(channel=channel)

    if q:
        qs = qs.filter(
            Q(client__name__icontains=q)
            | Q(client__organization__icontains=q)
            | Q(customer_notes__icontains=q)
            | Q(notes__icontains=q)
        )

    # -------------------------------------------------
    # DATE FILTER
    # -------------------------------------------------

    today = timezone.localdate()

    # Default date range:
    # Monday of the current week -> today
    week_start = today - timedelta(days=today.weekday())

    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()

    try:
        selected_date_from = date.fromisoformat(date_from)
    except (ValueError, TypeError):
        selected_date_from = week_start

    try:
        selected_date_to = date.fromisoformat(date_to)
    except (ValueError, TypeError):
        selected_date_to = today

    # If the user selects an invalid range,
    # reset to Monday -> today.
    if selected_date_from > selected_date_to:
        selected_date_from = week_start
        selected_date_to = today

    # -------------------------------------------------
    # DATETIME BOUNDARIES
    # -------------------------------------------------

    # Start of selected "From" date.
    start_datetime = datetime.combine(
        selected_date_from,
        datetime.min.time(),
    )

    # Start of the day AFTER selected "To" date.
    # Using __lt__ means the entire selected To date
    # is included, right up to 23:59:59...
    end_datetime = datetime.combine(
        selected_date_to + timedelta(days=1),
        datetime.min.time(),
    )

    # Make datetimes timezone-aware when required.
    if timezone.is_naive(start_datetime):
        start_datetime = timezone.make_aware(
            start_datetime,
            timezone.get_current_timezone(),
        )

    if timezone.is_naive(end_datetime):
        end_datetime = timezone.make_aware(
            end_datetime,
            timezone.get_current_timezone(),
        )

    # -------------------------------------------------
    # APPLY DATE FILTER
    # -------------------------------------------------

    qs = qs.filter(
        submitted_at__gte=start_datetime,
        submitted_at__lt=end_datetime,
    )

    # -------------------------------------------------
    # SAFE DECIMAL FALLBACKS
    # -------------------------------------------------

    ZERO_DEC = Value(
        Decimal("0.00"),
        output_field=DecimalField(
            max_digits=12,
            decimal_places=2,
        ),
    )

    ZERO_INT = Value(
        0,
        output_field=IntegerField(),
    )

    # -------------------------------------------------
    # COMPUTED TOTAL FALLBACK
    # -------------------------------------------------

    computed_total_fallback = ExpressionWrapper(
        Coalesce(F("subtotal_excl"), ZERO_DEC)
        + Coalesce(F("vat_total"), ZERO_DEC)
        + Coalesce(F("delivery_fee_excl"), ZERO_DEC),
        output_field=DecimalField(
            max_digits=12,
            decimal_places=2,
        ),
    )

    # -------------------------------------------------
    # ANNOTATIONS
    # -------------------------------------------------

    qs = qs.annotate(
        total_quantity=Coalesce(
            Sum("items__quantity"),
            ZERO_DEC,
            output_field=DecimalField(
                max_digits=12,
                decimal_places=2,
            ),
        ),

        item_count=Coalesce(
            Count(
                "items",
                distinct=True,
            ),
            ZERO_INT,
            output_field=IntegerField(),
        ),

        total_amount=Coalesce(
            F("grand_total_inc"),
            computed_total_fallback,
            output_field=DecimalField(
                max_digits=12,
                decimal_places=2,
            ),
        ),

    ).order_by(
        "-submitted_at"
    ).distinct()

    # -------------------------------------------------
    # RENDER
    # -------------------------------------------------

    return render(
        request,
        "orders/orders.html",
        {
            "orders": qs,

            "filter_status": status,
            "filter_channel": channel,
            "search": q,

            # Date filter values for the template
            "date_from": selected_date_from,
            "date_to": selected_date_to,

            # Role information
            "rep_only": rep_only,
        },
    )

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

    Representative-only users may only access orders belonging to
    clients assigned to them.

    Reps with any additional role (for example Representative + Supervisor)
    retain broader access.

    Totals are recalculated in-memory only (no DB write).
    """

    # -------------------------------------------------
    # ROLE / ACCESS CONTROL
    # -------------------------------------------------

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # A user is rep-only ONLY when their complete role
    # set is exactly {"Representative"}.
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # -------------------------------------------------
    # GET ORDER
    # -------------------------------------------------

    order = get_object_or_404(
        Order.objects
        .select_related(
            "client",
            "client__account_manager",
            "created_by",
            "reviewed_by",
            "approved_by",
        )
        .prefetch_related(
            "items__product",
            "items__category",
        ),
        pk=pk,
    )

    # -------------------------------------------------
    # REP ACCESS CHECK
    # -------------------------------------------------

    # Representative-only users can only access orders
    # belonging to their own clients.
    #
    # IMPORTANT:
    # This protects the actual URL as well as the list UI.
    if rep_only and order.client.account_manager_id != request.user.id:
        messages.error(
            request,
            "You do not have access to this order."
        )
        return redirect("sales:orders")

    # -------------------------------------------------
    # KEEP TOTALS FRESH
    # -------------------------------------------------

    # Recalculate in memory only.
    # No database write.
    try:
        order.recalc_totals(save=False)
    except Exception:
        # If recalc_totals doesn't exist or fails,
        # continue so the order can still be displayed.
        pass

    # -------------------------------------------------
    # INVOICE
    # -------------------------------------------------

    invoice = None

    try:
        invoice = order.invoice

    except AttributeError:
        invoice = None

    except Exception:
        # If the OneToOne relation raises another error,
        # don't allow it to break the order detail page.
        invoice = None

    # -------------------------------------------------
    # ORDER ITEMS
    # -------------------------------------------------

    items = (
        order.items
        .all()
        .order_by("id")
    )

    # -------------------------------------------------
    # RENDER
    # -------------------------------------------------

    return render(
        request,
        "orders/view_order.html",
        {
            "order": order,
            "items": items,
            "invoice": invoice,
            "rep_only": rep_only,
        },
    )



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

        # ============================================================
        # NORMAL WHOLESALE PRICING
        # ============================================================
        best_price_excl = None
        best_vat_percent = None

        active_pricing_rows = product.pricing_rows.filter(
            is_active=True
        )

        for pricing in active_pricing_rows:

            price_excl = pricing.wholesale_price_excl
            vat_percent = pricing.wholesale_vat_percent

            if price_excl is None or price_excl <= Decimal("0.00"):
                continue

            if best_price_excl is None or price_excl < best_price_excl:
                best_price_excl = price_excl
                best_vat_percent = vat_percent

        # ============================================================
        # SPECIAL PRICE
        # ============================================================
        #
        # If the product is on special and has a valid special
        # wholesale price INCLUDING VAT, use that price.
        #
        # The quotation stores unit_price_excl, so we convert the
        # special inclusive price back to EX VAT using the same VAT
        # percentage that applies to the product.
        #
        # ============================================================

        if (
            product.is_special
            and product.special_wholesale_price_inc is not None
            and product.special_wholesale_price_inc > Decimal("0.00")
            and best_vat_percent is not None
        ):

            vat_multiplier = (
                Decimal("1.00")
                + (best_vat_percent / Decimal("100.00"))
            )

            special_price_inc = product.special_wholesale_price_inc

            special_price_excl = (
                special_price_inc / vat_multiplier
            ).quantize(Decimal("0.01"))

            best_price_excl = special_price_excl

        # ============================================================
        # DISPLAY PRICE INCLUDING VAT
        # ============================================================

        if best_price_excl is not None:

            vat_multiplier = (
                Decimal("1.00")
                + (
                    (best_vat_percent or Decimal("0.00"))
                    / Decimal("100.00")
                )
            )

            best_price_incl = (
                best_price_excl * vat_multiplier
            ).quantize(Decimal("0.01"))

            # ========================================================
            # PRODUCT DISPLAY
            # ========================================================

            if (
                product.is_special
                and product.special_wholesale_price_inc is not None
                and product.special_wholesale_price_inc > Decimal("0.00")
            ):
                text = (
                    f"{product.sku} · {product.name} "
                    f"({product.uom}) — "
                    f"SPECIAL R{best_price_excl:.2f} excl · "
                    f"R{best_price_incl:.2f} incl"
                )
            else:
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

        # ============================================================
        # RETURN TO QUOTATION FORM
        # ============================================================

        results.append({
            "id": product.id,
            "text": text,
            "price_excl": str(
                best_price_excl or Decimal("0.00")
            ),
            "vat_percent": str(
                best_vat_percent or Decimal("0.00")
            ),
        })

    return JsonResponse({
        "results": results
    })



@login_required
def invoices(request):
    """
    List invoices with optional filters:

      - q: search across client name, client organization, order CL number
      - status: invoice status
      - date_from: invoice date range start (YYYY-MM-DD)
      - date_to: invoice date range end (YYYY-MM-DD)
      - page: paginator page

    Representative-only users can only see invoices belonging
    to their own clients.
    """

    # -------------------------------------------------
    # ROLE / ACCESS CONTROL
    # -------------------------------------------------

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # A user is rep-only ONLY when their complete
    # role set is exactly {"Representative"}.
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # -------------------------------------------------
    # BASE QUERYSET
    # -------------------------------------------------

    qs = (
        Invoice.objects
        .select_related(
            "client",
            "client__account_manager",
            "order",
        )
        .all()
        .order_by(
            "-invoice_date",
            "-created_at",
        )
    )

    # -------------------------------------------------
    # REP ACCESS
    # -------------------------------------------------

    # Representative-only users can only see invoices
    # belonging to clients assigned to them.
    if rep_only:
        qs = qs.filter(
            client__account_manager=request.user
        )

    # -------------------------------------------------
    # FILTERS FROM GET
    # -------------------------------------------------

    search = (request.GET.get("q") or "").strip()
    filter_status = (request.GET.get("status") or "").strip()

    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()

    # -------------------------------------------------
    # SEARCH
    # -------------------------------------------------

    if search:
        qs = qs.filter(
            Q(client__name__icontains=search)
            | Q(client__organization__icontains=search)
            | Q(order__cl_number__icontains=search)
        )

    # -------------------------------------------------
    # STATUS
    # -------------------------------------------------

    if filter_status:
        qs = qs.filter(
            status=filter_status
        )

    # -------------------------------------------------
    # DATE FILTER
    # -------------------------------------------------

    today = timezone.localdate()

    # Default:
    # Monday of current week -> today
    week_start = today - timedelta(
        days=today.weekday()
    )

    try:
        selected_date_from = date.fromisoformat(
            date_from
        )
    except (ValueError, TypeError):
        selected_date_from = week_start

    try:
        selected_date_to = date.fromisoformat(
            date_to
        )
    except (ValueError, TypeError):
        selected_date_to = today

    # If From > To, reset to Monday -> today.
    if selected_date_from > selected_date_to:
        selected_date_from = week_start
        selected_date_to = today

    # -------------------------------------------------
    # DATETIME BOUNDARIES
    # -------------------------------------------------

    # Start of selected From date.
    start_datetime = datetime.combine(
        selected_date_from,
        datetime.min.time(),
    )

    # Start of the day AFTER selected To date.
    end_datetime = datetime.combine(
        selected_date_to + timedelta(days=1),
        datetime.min.time(),
    )

    # Make timezone-aware where required.
    if timezone.is_naive(start_datetime):
        start_datetime = timezone.make_aware(
            start_datetime,
            timezone.get_current_timezone(),
        )

    if timezone.is_naive(end_datetime):
        end_datetime = timezone.make_aware(
            end_datetime,
            timezone.get_current_timezone(),
        )

    # -------------------------------------------------
    # APPLY DATE FILTER
    # -------------------------------------------------

    qs = qs.filter(
        invoice_date__gte=start_datetime,
        invoice_date__lt=end_datetime,
    )

    # -------------------------------------------------
    # PAGINATION
    # -------------------------------------------------

    per_page = 25

    page = request.GET.get(
        "page",
        1,
    )

    paginator = Paginator(
        qs,
        per_page,
    )

    try:
        invoices_page = paginator.page(
            page
        )

    except PageNotAnInteger:
        invoices_page = paginator.page(
            1
        )

    except EmptyPage:
        invoices_page = paginator.page(
            paginator.num_pages
        )

    # -------------------------------------------------
    # STATUS CHOICES
    # -------------------------------------------------

    status_choices = Invoice.STATUS_CHOICES

    # -------------------------------------------------
    # CONTEXT
    # -------------------------------------------------

    context = {
        "invoices": invoices_page,

        "search": search,

        "status_choices": status_choices,
        "filter_status": filter_status,

        "date_from": selected_date_from,
        "date_to": selected_date_to,

        "paginator": paginator,
        "page_obj": invoices_page,

        "rep_only": rep_only,
    }

    return render(
        request,
        "invoices/invoices.html",
        context,
    )


@login_required
def view_invoice(request, pk):
    """
    Invoice detail view.

    Representative-only users may only access invoices
    belonging to clients assigned to them.

    Direct URL access is also protected.
    """

    # -------------------------------------------------
    # ROLE / ACCESS CONTROL
    # -------------------------------------------------

    try:
        current_profile = (
            SalesRepProfile.objects
            .prefetch_related("roles")
            .get(user=request.user)
        )

        current_role_names = {
            role.name
            for role in current_profile.roles.all()
        }

    except SalesRepProfile.DoesNotExist:
        current_profile = None
        current_role_names = set()

    # A user is rep-only ONLY when their complete
    # role set is exactly {"Representative"}.
    rep_only = (
        current_profile is not None
        and current_role_names == {"Representative"}
    )

    # -------------------------------------------------
    # GET INVOICE
    # -------------------------------------------------

    invoice = get_object_or_404(
        Invoice.objects
        .select_related(
            "client",
            "client__account_manager",
            "order",
            "order__client",
            "order__created_by",
        )
        .prefetch_related(
            "order__items",
            "order__items__product",
            "order__items__category",
        ),
        pk=pk,
    )

    # -------------------------------------------------
    # REP ACCESS CHECK
    # -------------------------------------------------

    # Representative-only users may only access invoices
    # belonging to their own clients.
    if (
        rep_only
        and invoice.client.account_manager_id != request.user.id
    ):
        messages.error(
            request,
            "You do not have access to this invoice."
        )

        return redirect(
            "sales:sales-invoices"
        )

    # -------------------------------------------------
    # ORDER / CLIENT / ITEMS
    # -------------------------------------------------

    order = invoice.order
    client = invoice.client

    items = (
        order.items
        .all()
        .order_by("id")
    )

    # -------------------------------------------------
    # OVERDUE
    # -------------------------------------------------

    today = localdate()

    is_overdue = (
        invoice.status != "paid"
        and invoice.due_date is not None
        and invoice.due_date < today
    )

    # -------------------------------------------------
    # DEPOSIT OUTSTANDING
    # -------------------------------------------------

    deposit_outstanding = max(
        invoice.amount_due
        - (invoice.deposit_paid or 0),
        0,
    )

    # -------------------------------------------------
    # RENDER
    # -------------------------------------------------

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
            "rep_only": rep_only,
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

    # ============================================================
    # CURRENT DATE
    # ============================================================

    today = localdate()

    # ============================================================
    # LOGGED-IN USER SALES ROLE
    # ============================================================
    #
    # Representative-only users must only see their own sales data.
    # They must not be given access to management-level sections.
    #
    # A user is representative-only when they have the
    # Representative role and do NOT have the Supervisor role.
    # A user with both roles retains management visibility.
    # ============================================================

    sales_profile = getattr(
        request.user,
        "sales_rep_profile",
        None,
    )

    is_representative_only = False

    if sales_profile:
        role_names = list(
            sales_profile.roles.values_list(
                "name",
                flat=True,
            )
        )

        normalized_roles = {
            str(role).strip().lower()
            for role in role_names
            if role
        }

        has_representative_role = (
            "representative" in normalized_roles
        )

        has_supervisor_role = (
            "supervisor" in normalized_roles
        )

        is_representative_only = (
            has_representative_role
            and not has_supervisor_role
        )

    # ============================================================
    # YEAR
    # ============================================================

    try:
        selected_year = int(
            request.GET.get(
                "year",
                today.year,
            )
        )
    except (TypeError, ValueError):
        selected_year = today.year

    # ============================================================
    # REGION
    # ============================================================

    selected_region = request.GET.get(
        "region",
        "",
    )

    # ============================================================
    # SALES REPRESENTATIVE
    # ============================================================

    selected_rep = request.GET.get(
        "rep",
        "",
    )

    # ------------------------------------------------------------
    # REPRESENTATIVE-ONLY ACCESS CONTROL
    # ------------------------------------------------------------
    #
    # A representative cannot choose another representative through
    # the URL or dropdown. Their own User is always the selected rep.
    # This is enforced server-side, not only in the HTML.
    # ------------------------------------------------------------

    if is_representative_only:
        selected_rep = str(request.user.pk)

    # Sales representatives available in CommissionEntry.
    # The template expects each rep to have:
    #     r.value
    #     r.label
    #
    # Resolve the related model from the FK so this view does not
    # depend on a hard-coded User model import.
    rep_model = CommissionEntry._meta.get_field("rep").remote_field.model

    if is_representative_only:
        # Only expose the logged-in representative in the dropdown.
        rep_qs = (
            rep_model.objects
            .filter(
                pk=request.user.pk,
            )
        )
    else:
        rep_qs = (
            rep_model.objects
            .filter(
                id__in=CommissionEntry.objects
                .exclude(rep=None)
                .values_list("rep_id", flat=True)
                .distinct()
            )
        )

    reps = []

    for rep in rep_qs:
        try:
            label = rep.get_full_name()
        except Exception:
            label = ""

        if not label:
            label = getattr(rep, "username", "") or str(rep)

        reps.append({
            "value": rep.pk,
            "label": label,
        })

    reps.sort(
        key=lambda item: item["label"].lower()
    )

    # ============================================================
    # TERRITORY
    # ============================================================

    selected_territory = request.GET.get(
        "territory",
        "",
    )

    # ============================================================
    # PERIOD
    # ============================================================

    selected_period = request.GET.get(
        "period",
        "",
    )

    # ============================================================
    # PERIOD OPTIONS
    #
    # Commission periods:
    #
    # 15 Jan - 15 Feb
    # 15 Feb - 15 Mar
    # etc.
    # ============================================================

    period_options = []

    for month in range(1, 13):

        if month == 1:

            start_date = date(
                selected_year - 1,
                12,
                15,
            )

        else:

            start_date = date(
                selected_year,
                month - 1,
                15,
            )

        end_month = start_date.month + 1
        end_year = start_date.year

        if end_month == 13:

            end_month = 1
            end_year += 1

        end_date = date(
            end_year,
            end_month,
            15,
        )

        period_label = (
            f"{start_date.strftime('%d %b')} - "
            f"{end_date.strftime('%d %b')}"
        )

        period_options.append({
            "value": period_label,
            "label": period_label,
        })

    # ============================================================
    # DEFAULT PERIOD
    # ============================================================

    if not selected_period:

        if today.day >= 15:

            current_start = date(
                today.year,
                today.month,
                15,
            )

            if today.month == 12:

                current_end = date(
                    today.year + 1,
                    1,
                    15,
                )

            else:

                current_end = date(
                    today.year,
                    today.month + 1,
                    15,
                )

        else:

            if today.month == 1:

                current_start = date(
                    today.year - 1,
                    12,
                    15,
                )

            else:

                current_start = date(
                    today.year,
                    today.month - 1,
                    15,
                )

            current_end = date(
                today.year,
                today.month,
                15,
            )

        selected_period = (
            f"{current_start.strftime('%d %b')} - "
            f"{current_end.strftime('%d %b')}"
        )

    # ============================================================
    # CONVERT PERIOD TO DATE RANGE
    # ============================================================

    period_start = None
    period_end = None

    try:

        start_text, end_text = selected_period.split(
            " - "
        )

        start_day, start_month_name = (
            start_text.split()
        )

        end_day, end_month_name = (
            end_text.split()
        )

        start_month_number = list(
            calendar.month_abbr
        ).index(
            start_month_name
        )

        end_month_number = list(
            calendar.month_abbr
        ).index(
            end_month_name
        )

        start_day = int(start_day)
        end_day = int(end_day)

        # --------------------------------------------------------
        # December -> January
        # --------------------------------------------------------

        if (
            start_month_number == 12
            and end_month_number == 1
        ):

            period_start = date(
                selected_year - 1,
                start_month_number,
                start_day,
            )

            period_end = date(
                selected_year,
                end_month_number,
                end_day,
            )

        else:

            period_start = date(
                selected_year,
                start_month_number,
                start_day,
            )

            period_end = date(
                selected_year,
                end_month_number,
                end_day,
            )

    except (ValueError, TypeError):

        period_start = date(
            selected_year,
            today.month,
            15,
        )

        if today.month == 12:

            period_end = date(
                selected_year + 1,
                1,
                15,
            )

        else:

            period_end = date(
                selected_year,
                today.month + 1,
                15,
            )

    # ============================================================
    # TARGET MONTH
    #
    # The target is represented by the END month.
    #
    # Example:
    #
    # 15 Aug - 15 Sep
    #
    # -> SEP
    # ============================================================

    target_month_code = (
        calendar.month_abbr[
            period_end.month
        ].upper()
    )

    # ============================================================
    # REGION OPTIONS
    # ============================================================

    try:

        regions = (
            Region.objects
            .filter(
                status="ACTIVE"
            )
            .order_by(
                "name"
            )
        )

    except Exception:

        regions = (
            Region.objects
            .all()
            .order_by(
                "name"
            )
        )

    # ============================================================
    # TERRITORY OPTIONS
    # ============================================================

    territory_qs = (
        Territory.objects
        .filter(
            status="ACTIVE"
        )
        .select_related(
            "region"
        )
        .order_by(
            "name"
        )
    )

    if selected_region:

        territory_qs = (
            territory_qs.filter(
                region_id=selected_region
            )
        )

    territories = []

    for territory in territory_qs:

        territories.append({
            "value": territory.id,
            "label": territory.name,
            "region": (
                territory.region.name
                if territory.region
                else ""
            ),
        })

    # ============================================================
    # COMMISSION ENTRIES
    #
    # THIS IS THE SOURCE OF TRUTH FOR PERFORMANCE.
    #
    # The selected period is applied directly to
    # CommissionEntry.
    # ============================================================

    commission_entries = (
        CommissionEntry.objects
        .select_related(
            "invoice",
            "invoice__client",
            "invoice__client__area",
            "invoice__client__territory",
            "client",
            "area",
            "territory",
            "rep",
            "supervisor",
        )
        .filter(
            period=selected_period,
            invoice__paid_date__gte=period_start,
            invoice__paid_date__lt=period_end,
        )
        .order_by(
            "-invoice__paid_date",
            "-created_at",
        )
    )

    # ============================================================
    # REGION FILTER
    # ============================================================

    if selected_region:

        commission_entries = (
            commission_entries.filter(
                territory__region_id=selected_region
            )
        )

    # ============================================================
    # TERRITORY FILTER
    # ============================================================

    if selected_territory:

        commission_entries = (
            commission_entries.filter(
                territory_id=selected_territory
            )
        )

    # ============================================================
    # SALES REPRESENTATIVE FILTER
    # ============================================================

    if selected_rep:

        commission_entries = (
            commission_entries.filter(
                rep_id=selected_rep
            )
        )

    # ============================================================
    # PREVIOUS PERIOD
    # ============================================================

    previous_period_end = period_start

    if previous_period_end.month == 1:

        previous_period_start = date(
            previous_period_end.year - 1,
            12,
            15,
        )

    else:

        previous_period_start = date(
            previous_period_end.year,
            previous_period_end.month - 1,
            15,
        )

    previous_period_label = (
        f"{previous_period_start.strftime('%d %b')} - "
        f"{previous_period_end.strftime('%d %b')}"
    )

    previous_commission_entries = (
        CommissionEntry.objects
        .select_related(
            "invoice",
            "invoice__client",
            "client",
            "area",
            "territory",
            "rep",
            "supervisor",
        )
        .filter(
            period=previous_period_label,
            invoice__paid_date__gte=previous_period_start,
            invoice__paid_date__lt=previous_period_end,
        )
    )

    if selected_region:

        previous_commission_entries = (
            previous_commission_entries.filter(
                territory__region_id=selected_region
            )
        )

    if selected_territory:

        previous_commission_entries = (
            previous_commission_entries.filter(
                territory_id=selected_territory
            )
        )

    if selected_rep:

        previous_commission_entries = (
            previous_commission_entries.filter(
                rep_id=selected_rep
            )
        )

    # ============================================================
    # MONTHLY TARGETS
    # ============================================================

    monthly_targets = (
        MonthlyTarget.objects
        .select_related(
            "territory",
            "territory__region",
        )
        .filter(
            year=period_end.year,
            month=target_month_code,
        )
    )

    if selected_region:

        monthly_targets = (
            monthly_targets.filter(
                territory__region_id=selected_region
            )
        )

    if selected_territory:

        monthly_targets = (
            monthly_targets.filter(
                territory_id=selected_territory
            )
        )

    # ============================================================
    # TARGET TOTALS
    #
    # IMPORTANT:
    #
    # NO REP SELECTED
    #     Use the master MonthlyTarget totals for the selected
    #     region/territory.
    #
    # SPECIFIC REP SELECTED
    #     DO NOT use the master territory target.
    #
    #     Use MonthlyTargetAllocation for that specific rep:
    #
    #         monthly_target_value -> revenue target
    #         client_target        -> client target
    #
    # This keeps the actual performance and the target being
    # measured on the same level.
    # ============================================================

    rep_allocations = MonthlyTargetAllocation.objects.none()

    if selected_rep:

        # --------------------------------------------------------
        # REP-SPECIFIC MONTHLY TARGET ALLOCATIONS
        # --------------------------------------------------------

        rep_allocations = (
            MonthlyTargetAllocation.objects
            .select_related(
                "monthly_target",
                "monthly_target__territory",
                "monthly_target__territory__region",
                "sales_rep",
            )
            .filter(
                sales_rep_id=selected_rep,
                monthly_target__year=period_end.year,
                monthly_target__month=target_month_code,
            )
        )

        # Respect the selected region.
        if selected_region:
            rep_allocations = rep_allocations.filter(
                monthly_target__territory__region_id=selected_region
            )

        # Respect the selected territory.
        if selected_territory:
            rep_allocations = rep_allocations.filter(
                monthly_target__territory_id=selected_territory
            )

        # --------------------------------------------------------
        # REP REVENUE TARGET
        # --------------------------------------------------------

        monthly_target = (
            rep_allocations.aggregate(
                t=Sum("monthly_target_value")
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # REP CLIENT TARGET
        # --------------------------------------------------------

        client_target = (
            rep_allocations.aggregate(
                t=Sum("client_target")
            )["t"]
            or 0
        )

    else:

        # --------------------------------------------------------
        # ALL REPS
        #
        # Use the master MonthlyTarget totals.
        # --------------------------------------------------------

        monthly_target = (
            monthly_targets.aggregate(
                t=Sum("monthly_target")
            )["t"]
            or Decimal("0.00")
        )

        client_target = (
            monthly_targets.aggregate(
                t=Sum("total_client_target")
            )["t"]
            or 0
        )

    # ============================================================
    # TOTAL COMMISSION PAYABLE
    # ============================================================

    commission_totals = (
        commission_entries.aggregate(
            rep_total=Coalesce(
                Sum("rep_amount"),
                Decimal("0.00"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            ),
            supervisor_total=Coalesce(
                Sum("supervisor_amount"),
                Decimal("0.00"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            ),
        )
    )

    total_commission_payable = (
        commission_totals["rep_total"]
        + commission_totals["supervisor_total"]
    ).quantize(
        Decimal("0.01")
    )

    # ============================================================
    # NEW BUSINESS BONUS
    # ============================================================

    new_business_bonus_total = (
        commission_entries
        .filter(
            is_new_business=True
        )
        .aggregate(
            t=Sum("rep_amount")
        )["t"]
        or Decimal("0.00")
    )

    # ============================================================
    # REVENUE
    # ============================================================

    total_revenue = (
        commission_entries.aggregate(
            t=Sum(
                "invoice__order_total_inc"
            )
        )["t"]
        or Decimal("0.00")
    )

    # ============================================================
    # UNIQUE CLIENTS
    # ============================================================

    total_clients = (
        commission_entries
        .values("client_id")
        .exclude(
            client_id=None
        )
        .distinct()
        .count()
    )

    # ============================================================
    # PREVIOUS KPI VALUES
    # ============================================================

    previous_commission_totals = (
        previous_commission_entries.aggregate(
            rep_total=Coalesce(
                Sum("rep_amount"),
                Decimal("0.00"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            ),
            supervisor_total=Coalesce(
                Sum("supervisor_amount"),
                Decimal("0.00"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            ),
        )
    )

    previous_commission_payable = (
        previous_commission_totals["rep_total"]
        + previous_commission_totals["supervisor_total"]
    ).quantize(
        Decimal("0.01")
    )

    previous_revenue = (
        previous_commission_entries.aggregate(
            t=Sum(
                "invoice__order_total_inc"
            )
        )["t"]
        or Decimal("0.00")
    )

    previous_clients = (
        previous_commission_entries
        .values("client_id")
        .exclude(
            client_id=None
        )
        .distinct()
        .count()
    )

    previous_new_business_bonus = (
        previous_commission_entries
        .filter(
            is_new_business=True
        )
        .aggregate(
            t=Sum("rep_amount")
        )["t"]
        or Decimal("0.00")
    )

    # ============================================================
    # CHANGE HELPER
    # ============================================================

    def build_change(
        current,
        previous,
    ):

        current = (
            current
            or Decimal("0.00")
        )

        previous = (
            previous
            or Decimal("0.00")
        )

        if not isinstance(
            current,
            Decimal,
        ):

            current = Decimal(
                str(current)
            )

        if not isinstance(
            previous,
            Decimal,
        ):

            previous = Decimal(
                str(previous)
            )

        diff = current - previous

        if previous > 0:

            pct = (
                diff / previous
            ) * Decimal("100")

            pct = pct.quantize(
                Decimal("0.01")
            )

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
            "amount": diff.quantize(
                Decimal("0.01")
            ),
            "percent": pct,
        }

    # ============================================================
    # KPI CHANGES
    # ============================================================

    commission_payable_change = (
        build_change(
            total_commission_payable,
            previous_commission_payable,
        )
    )

    revenue_change = (
        build_change(
            total_revenue,
            previous_revenue,
        )
    )

    clients_change = (
        build_change(
            Decimal(total_clients),
            Decimal(previous_clients),
        )
    )

    new_business_bonus_change = (
        build_change(
            new_business_bonus_total,
            previous_new_business_bonus,
        )
    )

    # ============================================================
    # TARGET PROGRESS
    # ============================================================

    actual_revenue = total_revenue
    actual_clients = total_clients

    revenue_target_pct = (
        (
            actual_revenue
            / monthly_target
        )
        * Decimal("100")
        if monthly_target > 0
        else Decimal("0.00")
    )

    client_target_pct = (
        (
            Decimal(actual_clients)
            / Decimal(client_target)
        )
        * Decimal("100")
        if client_target > 0
        else Decimal("0.00")
    )

    revenue_gap = max(
        monthly_target - actual_revenue,
        Decimal("0.00"),
    )

    clients_needed_for_bonus = max(
        client_target - actual_clients,
        0,
    )

    # Accelerator/bonus activates only when BOTH targets are met.
    bonus_active = (
        actual_revenue >= monthly_target
        and actual_clients >= client_target
        if monthly_target > 0 and client_target > 0
        else False
    )

    # ============================================================
    # WORKING DAYS
    # ============================================================

    working_days = 0

    for target in monthly_targets:

        try:

            working_days = max(
                working_days,
                target.get_total_working_days(),
            )

        except Exception:

            pass

    if working_days <= 0:

        working_days = 1

    # ============================================================
    # DAYS PASSED
    # ============================================================

    if (
        period_start <= today < period_end
    ):

        current_day = today

    else:

        current_day = period_end

    days_passed = 0

    current_date = period_start

    while current_date < current_day:

        if current_date.weekday() < 5:

            days_passed += 1

        current_date += timedelta(
            days=1
        )

    days_remaining = max(
        working_days - days_passed,
        0,
    )

    # ============================================================
    # WEEKLY PACING
    # ============================================================

    weeks_in_period = Decimal("4.00")

    weekly_average = (
        actual_revenue
        / weeks_in_period
        if actual_revenue > 0
        else Decimal("0.00")
    ).quantize(
        Decimal("0.01")
    )

    required_per_week = (
        revenue_gap
        / weeks_in_period
        if revenue_gap > 0
        else Decimal("0.00")
    ).quantize(
        Decimal("0.01")
    )

    # ============================================================
    # REP PERFORMANCE
    #
    # IMPORTANT:
    #
    # CommissionEntry is the source of truth.
    #
    # Every rep appears ONLY ONCE.
    #
    # Entries = number of CommissionEntry records
    # for that rep during the selected period.
    # ============================================================

    rep_commission_summary = []

    rep_ids = (
        commission_entries
        .exclude(
            rep=None
        )
        .values_list(
            "rep_id",
            flat=True,
        )
        .distinct()
    )

    for rep_id in rep_ids:

        rep_entries = (
            commission_entries.filter(
                rep_id=rep_id
            )
        )

        rep_entry = (
            rep_entries
            .select_related(
                "rep"
            )
            .first()
        )

        if (
            not rep_entry
            or not rep_entry.rep
        ):

            continue

        rep = rep_entry.rep

        # --------------------------------------------------------
        # ENTRY COUNT
        # --------------------------------------------------------

        rep_entry_count = (
            rep_entries.count()
        )

        # --------------------------------------------------------
        # REVENUE
        # --------------------------------------------------------

        rep_revenue = (
            rep_entries.aggregate(
                t=Sum(
                    "invoice__order_total_inc"
                )
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # UNIQUE CLIENTS
        # --------------------------------------------------------

        rep_clients = (
            rep_entries
            .exclude(
                client_id=None
            )
            .values(
                "client_id"
            )
            .distinct()
            .count()
        )

        # --------------------------------------------------------
        # BASE COMMISSION
        # --------------------------------------------------------

        base_commission = (
            rep_entries
            .filter(
                is_new_business=False
            )
            .aggregate(
                t=Sum("rep_amount")
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # BONUS COMMISSION
        # --------------------------------------------------------

        bonus_commission = (
            rep_entries
            .filter(
                is_new_business=True
            )
            .aggregate(
                t=Sum("rep_amount")
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # TOTAL REP COMMISSION
        # --------------------------------------------------------

        total_rep_commission = (
            base_commission
            + bonus_commission
        ).quantize(
            Decimal("0.01")
        )

        # --------------------------------------------------------
        # TERRITORY
        # --------------------------------------------------------

        territory_names = list(
            rep_entries
            .exclude(
                territory=None
            )
            .values_list(
                "territory__name",
                flat=True,
            )
            .distinct()
        )

        if len(territory_names) == 1:

            territory_name = (
                territory_names[0]
            )

        elif len(territory_names) > 1:

            territory_name = "Multiple"

        else:

            territory_name = "—"

        territory_ids = list(
            rep_entries
            .exclude(
                territory=None
            )
            .values_list(
                "territory_id",
                flat=True,
            )
            .distinct()
        )

        if len(territory_ids) == 1:

            territory_id = (
                territory_ids[0]
            )

        else:

            territory_id = None

        # --------------------------------------------------------
        # SUPERVISOR
        # --------------------------------------------------------

        supervisor_names = []
        supervisor_ids = []

        supervisor_rows = (
            rep_entries
            .exclude(
                supervisor=None
            )
            .values(
                "supervisor_id",
                "supervisor__first_name",
                "supervisor__last_name",
                "supervisor__username",
            )
            .distinct()
        )

        for supervisor_row in supervisor_rows:

            supervisor_name = (
                f"{supervisor_row['supervisor__first_name'] or ''} "
                f"{supervisor_row['supervisor__last_name'] or ''}"
            ).strip()

            if not supervisor_name:

                supervisor_name = (
                    supervisor_row[
                        "supervisor__username"
                    ]
                    or "—"
                )

            if (
                supervisor_name
                not in supervisor_names
            ):

                supervisor_names.append(
                    supervisor_name
                )

            if (
                supervisor_row[
                    "supervisor_id"
                ]
                not in supervisor_ids
            ):

                supervisor_ids.append(
                    supervisor_row[
                        "supervisor_id"
                    ]
                )

        if len(supervisor_names) == 1:

            supervisor_name = (
                supervisor_names[0]
            )

        elif len(supervisor_names) > 1:

            supervisor_name = "Multiple"

        else:

            supervisor_name = "—"

        if len(supervisor_ids) == 1:

            supervisor_id = (
                supervisor_ids[0]
            )

        else:

            supervisor_id = None

        # --------------------------------------------------------
        # REP NAME
        # --------------------------------------------------------

        full_name = (
            rep.get_full_name()
            or rep.username
        )

        # --------------------------------------------------------
        # ADD REP
        # --------------------------------------------------------

        # --------------------------------------------------------
        # REP TARGET ALLOCATION
        #
        # When a rep is selected, the allocation query above is
        # already restricted to that rep.
        #
        # For the rep-performance table, also expose the
        # allocation when possible. This means the row and the
        # target cards are using the same allocation source.
        #
        # When no specific rep is selected, calculate the
        # allocation for this individual rep so every rep row
        # can display its own target.
        # --------------------------------------------------------

        if selected_rep and str(rep.id) == str(selected_rep):

            individual_rep_allocations = rep_allocations

        else:

            individual_rep_allocations = (
                MonthlyTargetAllocation.objects
                .filter(
                    sales_rep_id=rep.id,
                    monthly_target__year=period_end.year,
                    monthly_target__month=target_month_code,
                )
            )

            if selected_region:
                individual_rep_allocations = (
                    individual_rep_allocations.filter(
                        monthly_target__territory__region_id=selected_region
                    )
                )

            if selected_territory:
                individual_rep_allocations = (
                    individual_rep_allocations.filter(
                        monthly_target__territory_id=selected_territory
                    )
                )

        rep_revenue_target = (
            individual_rep_allocations.aggregate(
                t=Sum("monthly_target_value")
            )["t"]
            or Decimal("0.00")
        )

        rep_client_target = (
            individual_rep_allocations.aggregate(
                t=Sum("client_target")
            )["t"]
            or 0
        )

        rep_revenue_pct = (
            (
                rep_revenue
                / rep_revenue_target
            )
            * Decimal("100")
            if rep_revenue_target > 0
            else Decimal("0.00")
        )

        rep_revenue_pct = rep_revenue_pct.quantize(
            Decimal("0.01")
        )

        rep_commission_summary.append({

            "rep_id":
                rep.id,

            "rep_name":
                full_name,

            "role":
                "Sales Rep",

            "entries":
                rep_entry_count,

            "territory":
                territory_name,

            "territory_id":
                territory_id,

            "supervisor":
                supervisor_name,

            "supervisor_id":
                supervisor_id,

            "revenue":
                rep_revenue,

            "revenue_target":
                rep_revenue_target,

            "revenue_pct":
                rep_revenue_pct,

            "clients":
                rep_clients,

            "client_target":
                rep_client_target,

            "base_commission":
                base_commission,

            "bonus_commission":
                bonus_commission,

            "total_commission":
                total_rep_commission,
        })

    # ============================================================
    # HARD DEDUPLICATION OF REP PERFORMANCE
    # ============================================================
    # One row per representative.
    # CommissionEntry may contain multiple records for the same rep,
    # but the performance table must always show that rep once.
    # ============================================================

    unique_rep_summary = {}

    for row in rep_commission_summary:
        rep_id = row.get("rep_id")

        if rep_id is None:
            continue

        if rep_id not in unique_rep_summary:
            unique_rep_summary[rep_id] = row

    rep_commission_summary = list(
        unique_rep_summary.values()
    )

    # ============================================================
    # SORT REP PERFORMANCE
    # ============================================================

    rep_commission_summary = sorted(
        rep_commission_summary,
        key=lambda x: (
            x["total_commission"],
            x["bonus_commission"],
            x["revenue"],
            x["clients"],
            x["entries"],
        ),
        reverse=True,
    )

    # ============================================================
    # REP RANKING
    # ============================================================

    for index, row in enumerate(
        rep_commission_summary,
        start=1,
    ):

        row["ranking"] = index

    # ============================================================
    # TERRITORY PERFORMANCE
    # ============================================================

    territory_performance_summary = []

    seen_territories = set()

    for target in monthly_targets:

        territory = target.territory

        if not territory:
            continue

        if territory.id in seen_territories:
            continue

        seen_territories.add(
            territory.id
        )

        territory_entries = (
            commission_entries.filter(
                territory_id=territory.id
            )
        )

        # --------------------------------------------------------
        # REPS
        # --------------------------------------------------------

        rep_count = (
            territory_entries
            .exclude(
                rep=None
            )
            .values(
                "rep_id"
            )
            .distinct()
            .count()
        )

        # --------------------------------------------------------
        # CLIENTS
        # --------------------------------------------------------

        total_clients_territory = (
            territory_entries
            .exclude(
                client=None
            )
            .values(
                "client_id"
            )
            .distinct()
            .count()
        )

        # --------------------------------------------------------
        # REVENUE
        # --------------------------------------------------------

        territory_revenue = (
            territory_entries.aggregate(
                t=Sum(
                    "invoice__order_total_inc"
                )
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # REP COMMISSION
        # --------------------------------------------------------

        rep_commission_total = (
            territory_entries.aggregate(
                t=Sum("rep_amount")
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # SUPERVISOR COMMISSION
        # --------------------------------------------------------

        supervisor_commission_total = (
            territory_entries.aggregate(
                t=Sum(
                    "supervisor_amount"
                )
            )["t"]
            or Decimal("0.00")
        )

        total_commission_territory = (
            rep_commission_total
            + supervisor_commission_total
        ).quantize(
            Decimal("0.01")
        )

        # --------------------------------------------------------
        # ALLOCATED REPS
        # --------------------------------------------------------

        allocated_rep_count = (
            MonthlyTargetAllocation.objects
            .filter(
                monthly_target=target
            )
            .exclude(
                sales_rep=None
            )
            .values(
                "sales_rep_id"
            )
            .distinct()
            .count()
        )

        territory_performance_summary.append({

            "territory_id":
                territory.id,

            "territory":
                territory.name,

            "rep_count":
                rep_count,

            "allocated_rep_count":
                allocated_rep_count,

            "clients":
                total_clients_territory,

            "revenue":
                territory_revenue,

            "target":
                target.monthly_target
                or Decimal("0.00"),

            "client_target":
                target.total_client_target
                or 0,

            "rep_commission_total":
                rep_commission_total,

            "supervisor_commission_total":
                supervisor_commission_total,

            "total_commission":
                total_commission_territory,
        })

    # ============================================================
    # SUPERVISOR PERFORMANCE
    #
    # IMPORTANT:
    #
    # This is NOT payroll.
    #
    # It is performance based directly on CommissionEntry.
    #
    # Every supervisor appears ONLY ONCE.
    #
    # Entries:
    #     Number of CommissionEntry records.
    #
    # Reps:
    #     Number of unique reps.
    #
    # Clients:
    #     Number of unique clients.
    #
    # Revenue:
    #     Total invoice revenue.
    #
    # Commission:
    #     Total supervisor_amount.
    #
    # Total:
    #     Same as supervisor commission.
    # ============================================================

    supervisor_performance_summary = []

    supervisor_ids = (
        commission_entries
        .exclude(
            supervisor=None
        )
        .values_list(
            "supervisor_id",
            flat=True,
        )
        .distinct()
    )

    for supervisor_id in supervisor_ids:

        supervisor_entries = (
            commission_entries.filter(
                supervisor_id=supervisor_id
            )
        )

        supervisor_entry = (
            supervisor_entries
            .select_related(
                "supervisor"
            )
            .first()
        )

        if (
            not supervisor_entry
            or not supervisor_entry.supervisor
        ):

            continue

        supervisor = (
            supervisor_entry.supervisor
        )

        # --------------------------------------------------------
        # ENTRY COUNT
        # --------------------------------------------------------

        supervisor_entry_count = (
            supervisor_entries.count()
        )

        # --------------------------------------------------------
        # UNIQUE REPS
        # --------------------------------------------------------

        supervisor_rep_count = (
            supervisor_entries
            .exclude(
                rep=None
            )
            .values(
                "rep_id"
            )
            .distinct()
            .count()
        )

        # --------------------------------------------------------
        # UNIQUE CLIENTS
        # --------------------------------------------------------

        supervisor_client_count = (
            supervisor_entries
            .exclude(
                client=None
            )
            .values(
                "client_id"
            )
            .distinct()
            .count()
        )

        # --------------------------------------------------------
        # REVENUE
        # --------------------------------------------------------

        supervisor_revenue = (
            supervisor_entries.aggregate(
                t=Sum(
                    "invoice__order_total_inc"
                )
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # SUPERVISOR COMMISSION
        # --------------------------------------------------------

        supervisor_commission = (
            supervisor_entries.aggregate(
                t=Sum(
                    "supervisor_amount"
                )
            )["t"]
            or Decimal("0.00")
        )

        supervisor_commission = (
            supervisor_commission.quantize(
                Decimal("0.01")
            )
        )

        # --------------------------------------------------------
        # NAME
        # --------------------------------------------------------

        supervisor_name = (
            supervisor.get_full_name()
            or supervisor.username
        )

        # --------------------------------------------------------
        # ADD ONE SUPERVISOR ROW
        # --------------------------------------------------------

        supervisor_performance_summary.append({

            "supervisor_id":
                supervisor.id,

            "supervisor_name":
                supervisor_name,

            "entries":
                supervisor_entry_count,

            "reps":
                supervisor_rep_count,

            "clients":
                supervisor_client_count,

            "revenue":
                supervisor_revenue,

            "commission":
                supervisor_commission,

            "total":
                supervisor_commission,
        })

    # ============================================================
    # HARD DEDUPLICATION OF SUPERVISOR PERFORMANCE
    # ============================================================
    # One row per supervisor.
    # All CommissionEntry records belonging to the same supervisor
    # are already aggregated above; this final guard ensures the
    # template can never receive duplicate supervisor rows.
    # ============================================================

    unique_supervisor_summary = {}

    for row in supervisor_performance_summary:
        supervisor_id = row.get("supervisor_id")

        if supervisor_id is None:
            continue

        if supervisor_id not in unique_supervisor_summary:
            unique_supervisor_summary[supervisor_id] = row

    supervisor_performance_summary = list(
        unique_supervisor_summary.values()
    )

    # ============================================================
    # SORT SUPERVISOR PERFORMANCE
    #
    # Highest commission first.
    # ============================================================

    supervisor_performance_summary = sorted(
        supervisor_performance_summary,
        key=lambda x: (
            x["total"],
            x["revenue"],
            x["clients"],
            x["reps"],
            x["entries"],
        ),
        reverse=True,
    )

    # ============================================================
    # SUPERVISOR RANKING
    # ============================================================

    for index, row in enumerate(
        supervisor_performance_summary,
        start=1,
    ):

        row["ranking"] = index

    # ============================================================
    # PERFORMANCE TREND
    # ============================================================

    performance_trend_labels = []
    performance_trend_revenue = []
    performance_trend_commission = []
    performance_trend_clients = []
    performance_trend_orders = []

    for month in range(1, 13):

        start = date(
            selected_year,
            month,
            1,
        )

        # Use the first day of the following month as an
        # exclusive upper bound. This works correctly whether
        # invoice__paid_date is a DateField or DateTimeField.
        if month == 12:

            end = date(
                selected_year + 1,
                1,
                1,
            )

        else:

            end = date(
                selected_year,
                month + 1,
                1,
            )

        month_entries = (
            CommissionEntry.objects
            .select_related(
                "invoice",
                "client",
                "territory",
                "rep",
                "supervisor",
            )
            .filter(
                invoice__paid_date__gte=start,
                invoice__paid_date__lt=end,
            )
        )

        if selected_region:

            month_entries = (
                month_entries.filter(
                    territory__region_id=selected_region
                )
            )

        if selected_territory:

            month_entries = (
                month_entries.filter(
                    territory_id=selected_territory
                )
            )

        if selected_rep:

            month_entries = (
                month_entries.filter(
                    rep_id=selected_rep
                )
            )

        # --------------------------------------------------------
        # REVENUE
        # --------------------------------------------------------

        month_revenue = (
            month_entries.aggregate(
                t=Sum(
                    "invoice__order_total_inc"
                )
            )["t"]
            or Decimal("0.00")
        )

        # --------------------------------------------------------
        # COMMISSION
        # --------------------------------------------------------

        month_commission_totals = (
            month_entries.aggregate(
                rep_total=Coalesce(
                    Sum("rep_amount"),
                    Decimal("0.00"),
                    output_field=DecimalField(
                        max_digits=14,
                        decimal_places=2,
                    ),
                ),
                supervisor_total=Coalesce(
                    Sum("supervisor_amount"),
                    Decimal("0.00"),
                    output_field=DecimalField(
                        max_digits=14,
                        decimal_places=2,
                    ),
                ),
            )
        )

        month_commission = (
            month_commission_totals[
                "rep_total"
            ]
            + month_commission_totals[
                "supervisor_total"
            ]
        ).quantize(
            Decimal("0.01")
        )

        # --------------------------------------------------------
        # CLIENTS
        # --------------------------------------------------------

        month_clients = (
            month_entries
            .exclude(
                client=None
            )
            .values(
                "client_id"
            )
            .distinct()
            .count()
        )

        # --------------------------------------------------------
        # ORDERS
        # --------------------------------------------------------

        month_orders = (
            month_entries
            .exclude(
                invoice=None
            )
            .values(
                "invoice_id"
            )
            .distinct()
            .count()
        )

        performance_trend_labels.append(
            calendar.month_abbr[month]
        )

        performance_trend_revenue.append(
            float(month_revenue)
        )

        performance_trend_commission.append(
            float(month_commission)
        )

        performance_trend_clients.append(
            month_clients
        )

        performance_trend_orders.append(
            month_orders
        )

    # ============================================================
    # EMAIL MODAL COMPATIBILITY
    # ============================================================

    target_rep = None

    filter_date_from = period_start
    filter_date_to = period_end

    # ============================================================
    # CONTEXT
    # ============================================================

    context = {

        # --------------------------------------------------------
        # FILTERS
        # --------------------------------------------------------

        "selected_period":
            selected_period,

        "selected_year":
            selected_year,

        "selected_region":
            selected_region,

        "selected_rep":
            selected_rep,

        "reps":
            reps,

        "selected_territory":
            selected_territory,

        "periods":
            period_options,

        "years":
            list(
                range(
                    today.year - 2,
                    today.year + 3,
                )
            ),

        "regions":
            regions,

        "territories":
            territories,

        # --------------------------------------------------------
        # USER ACCESS / ROLE
        # --------------------------------------------------------

        "is_representative_only":
            is_representative_only,

        # --------------------------------------------------------
        # PERIOD DATES
        # --------------------------------------------------------

        "period_start":
            period_start,

        "period_end":
            period_end,

        # --------------------------------------------------------
        # KPI
        # --------------------------------------------------------

        "total_commission_payable":
            total_commission_payable,

        "total_revenue":
            total_revenue,

        "total_clients":
            total_clients,

        "new_business_bonus_total":
            new_business_bonus_total,

        "commission_payable_change":
            commission_payable_change,

        "revenue_change":
            revenue_change,

        "clients_change":
            clients_change,

        "new_business_bonus_change":
            new_business_bonus_change,

        "comparison_start":
            previous_period_start,

        "comparison_end":
            previous_period_end,

        # --------------------------------------------------------
        # TARGETS
        # --------------------------------------------------------

        "actual_revenue":
            actual_revenue,

        "monthly_target":
            monthly_target,

        "revenue_target_pct":
            revenue_target_pct,

        "revenue_gap":
            revenue_gap,

        "required_per_week":
            required_per_week,

        "weekly_average":
            weekly_average,

        "actual_clients":
            actual_clients,

        "client_target":
            client_target,

        "client_target_pct":
            client_target_pct,

        "bonus_active":
            bonus_active,

        "clients_needed_for_bonus":
            clients_needed_for_bonus,

        "days_remaining":
            days_remaining,

        # --------------------------------------------------------
        # REP PERFORMANCE
        # --------------------------------------------------------

        "rep_commission_summary":
            rep_commission_summary,

        # --------------------------------------------------------
        # COMMISSION ENTRIES
        # --------------------------------------------------------

        "commission_entries":
            commission_entries[:20],

        # --------------------------------------------------------
        # TERRITORY PERFORMANCE
        # --------------------------------------------------------

        "territory_performance_summary":
            territory_performance_summary,

        # --------------------------------------------------------
        # SUPERVISOR PERFORMANCE
        # --------------------------------------------------------

        "supervisor_performance_summary":
            supervisor_performance_summary,

        # --------------------------------------------------------
        # EMAIL
        # --------------------------------------------------------

        "target_rep":
            target_rep,

        "filter_date_from":
            filter_date_from,

        "filter_date_to":
            filter_date_to,

        # --------------------------------------------------------
        # TREND
        # --------------------------------------------------------

        "performance_trend_labels":
            performance_trend_labels,

        "performance_trend_revenue":
            performance_trend_revenue,

        "performance_trend_commission":
            performance_trend_commission,

        "performance_trend_clients":
            performance_trend_clients,

        "performance_trend_orders":
            performance_trend_orders,
    }

    # ============================================================
    # RENDER
    # ============================================================

    return render(
        request,
        "commission/commission.html",
        context,
    )




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
        .select_related(
            "client",
            "created_by",
            "closed_by",
        )
        .order_by("-created_at")
    )

    # =====================================================
    # FILTERS
    # =====================================================

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    department = (request.GET.get("department") or "").strip()
    ticket_type = (request.GET.get("ticket_type") or "").strip()


    # =====================================================
    # SEARCH
    # =====================================================

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


    # =====================================================
    # FILTER BY STATUS
    # =====================================================

    if status:
        qs = qs.filter(status=status)


    # =====================================================
    # FILTER BY PRIORITY
    # =====================================================

    if priority:
        qs = qs.filter(priority=priority)


    # =====================================================
    # FILTER BY DEPARTMENT
    # =====================================================

    if department:
        qs = qs.filter(department=department)


    # =====================================================
    # FILTER BY TICKET TYPE
    # =====================================================

    if ticket_type:
        qs = qs.filter(ticket_type=ticket_type)


    # =====================================================
    # STATISTICS
    # =====================================================

    stats_qs = Ticket.objects.all()

    stats = {
        "total": stats_qs.count(),

        "new": stats_qs.filter(
            status=Ticket.Status.NEW
        ).count(),

        "open": stats_qs.filter(
            status=Ticket.Status.OPEN
        ).count(),

        "pending": stats_qs.filter(
            status=Ticket.Status.PENDING
        ).count(),

        "resolved": stats_qs.filter(
            status=Ticket.Status.RESOLVED
        ).count(),

        "closed": stats_qs.filter(
            status=Ticket.Status.CLOSED
        ).count(),
    }


    # =====================================================
    # PAGINATION
    # =====================================================

    paginator = Paginator(qs, 25)

    page_number = request.GET.get("page")

    page_obj = paginator.get_page(page_number)


    # =====================================================
    # CONTEXT
    # =====================================================

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

            "department": Ticket._meta.get_field(
                "department"
            ).choices,

            "ticket_type": Ticket.TicketType.choices,
        },
    }


    return render(
        request,
        "tickets/tickets.html",
        context,
    )

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
    """
    Detailed commission performance for a single sales representative.

    The detail page uses the SAME 15th-to-15th reporting period
    used by the main Commission Centre.

    Shows:
    - All commission entries for the selected rep
    - All entries within the selected reporting period
    - Rep commission
    - New business bonus
    - Revenue generated
    - Unique clients
    - Rep revenue target from MonthlyTargetAllocation
    - Rep client target from MonthlyTargetAllocation
    - Client target progress
    - Monthly commission trend

    The selected period is passed from the Commission Centre as:

        ?period=<selected_period>

    For backwards compatibility, month/year parameters are also
    supported when period is not supplied.
    """

    today = localdate()

    # ============================================================
    # SALES REPRESENTATIVE
    # ============================================================

    rep_user = get_object_or_404(
        User,
        id=user_id,
    )

    # ============================================================
    # FILTERS
    # ============================================================

    selected_period = (
        request.GET.get("period", "")
        or ""
    ).strip()

    selected_area = (
        request.GET.get("area", "")
        or ""
    ).strip()

    selected_territory = (
        request.GET.get("territory", "")
        or ""
    ).strip()

    # ============================================================
    # PERIOD HELPERS
    # ============================================================

    def build_reporting_period(
        year,
        month,
    ):
        """
        Build the 15th-to-15th reporting period.

        Example:

            August 2026
            = 15 July 2026 through 15 August 2026

        The end date is EXCLUSIVE when querying paid invoices.
        """

        if month == 1:
            period_start = date(
                year - 1,
                12,
                15,
            )
        else:
            period_start = date(
                year,
                month - 1,
                15,
            )

        period_end = date(
            year,
            month,
            15,
        )

        return period_start, period_end

    # ============================================================
    # DETERMINE SELECTED REPORTING PERIOD
    # ============================================================

    period_start = None
    period_end = None

    # ------------------------------------------------------------
    # OPTION 1:
    # Main Commission Centre sends an ISO period.
    #
    # Supported examples:
    #
    # 2026-07-15_2026-08-15
    # 2026-07-15/2026-08-15
    # 2026-07-15 to 2026-08-15
    # ------------------------------------------------------------

    if selected_period:

        period_text = (
            selected_period
            .replace(
                "–",
                "-",
            )
            .replace(
                "—",
                "-",
            )
            .strip()
        )

        # Try ISO-style dates first.
        iso_matches = re.findall(
            r"(\d{4}-\d{2}-\d{2})",
            period_text,
        )

        if len(iso_matches) >= 2:
            try:
                period_start = date.fromisoformat(
                    iso_matches[0]
                )

                period_end = date.fromisoformat(
                    iso_matches[1]
                )
            except ValueError:
                period_start = None
                period_end = None

    # ------------------------------------------------------------
    # OPTION 2:
    # Period label such as:
    #
    # 15 Jul - 15 Aug
    # Aug 15 - Sep 15
    #
    # In this case use selected_year / today.year.
    # ------------------------------------------------------------

    if selected_period and (
        period_start is None
        or period_end is None
    ):

        year_param = request.GET.get(
            "year"
        )

        try:
            selected_year = (
                int(year_param)
                if year_param
                else today.year
            )
        except (
            TypeError,
            ValueError,
        ):
            selected_year = today.year

        # Try to identify the ending month.
        month_number = None

        month_abbreviations = {
            calendar.month_abbr[i].lower(): i
            for i in range(1, 13)
        }

        month_names = {
            calendar.month_name[i].lower(): i
            for i in range(1, 13)
        }

        lower_period = period_text.lower()

        # Look for full month names first.
        for month_name, number in month_names.items():

            if month_name in lower_period:
                month_number = number

        # Then abbreviations.
        if month_number is None:

            for month_name, number in month_abbreviations.items():

                if month_name in lower_period:
                    month_number = number

        if month_number:

            period_start, period_end = (
                build_reporting_period(
                    selected_year,
                    month_number,
                )
            )

    # ============================================================
    # OPTION 3:
    # BACKWARDS COMPATIBILITY
    #
    # If no usable period was supplied, use month/year.
    # ============================================================

    if period_start is None or period_end is None:

        month_param = request.GET.get(
            "month"
        )

        year_param = request.GET.get(
            "year"
        )

        try:
            selected_month = (
                int(month_param)
                if month_param
                else today.month
            )
        except (
            TypeError,
            ValueError,
        ):
            selected_month = today.month

        try:
            selected_year = (
                int(year_param)
                if year_param
                else today.year
            )
        except (
            TypeError,
            ValueError,
        ):
            selected_year = today.year

        if (
            selected_month < 1
            or selected_month > 12
        ):
            selected_month = today.month

        if (
            selected_year < 2000
            or selected_year > 2100
        ):
            selected_year = today.year

        period_start, period_end = (
            build_reporting_period(
                selected_year,
                selected_month,
            )
        )

    # ============================================================
    # FINAL PERIOD VALIDATION
    # ============================================================

    if period_start >= period_end:

        # Safe fallback to the current reporting period.

        if today.day >= 15:

            if today.month == 12:
                fallback_year = today.year + 1
                fallback_month = 1
            else:
                fallback_year = today.year
                fallback_month = today.month + 1

        else:

            fallback_year = today.year
            fallback_month = today.month

        period_start, period_end = (
            build_reporting_period(
                fallback_year,
                fallback_month,
            )
        )

    # The target month/year is determined by the
    # MONTH IN WHICH THE REPORTING PERIOD ENDS.
    target_year = period_end.year
    target_month = period_end.month

    month_code = (
        calendar.month_abbr[
            target_month
        ].upper()
    )

    # ============================================================
    # HUMAN-READABLE PERIOD LABEL
    # ============================================================

    selected_period = (
        f"{period_start.strftime('%d %b %Y')}"
        f" - "
        f"{period_end.strftime('%d %b %Y')}"
    )

    # ============================================================
    # COMMISSION ENTRIES
    # ============================================================
    #
    # IMPORTANT:
    #
    # Use invoice__paid_date, NOT CommissionEntry.created_at.
    #
    # CommissionEntry is generated when the invoice becomes
    # paid, and the Commission Centre also uses paid_date.
    #
    # The period end is EXCLUSIVE:
    #
    #     >= period_start
    #     <  period_end
    #
    # This prevents the 15th from being counted in two periods.
    # ============================================================

    commission_entries = (
        CommissionEntry.objects
        .select_related(
            "invoice",
            "invoice__client",
            "invoice__client__territory",
            "invoice__client__area",
            "client",
            "territory",
            "area",
            "rep",
            "supervisor",
        )
        .filter(
            rep=rep_user,
            invoice__paid_date__gte=period_start,
            invoice__paid_date__lt=period_end,
        )
        .order_by(
            "-invoice__paid_date",
            "-created_at",
        )
    )

    # ============================================================
    # AREA FILTER
    # ============================================================

    if selected_area:

        commission_entries = (
            commission_entries.filter(
                client__area=selected_area
            )
        )

    # ============================================================
    # TERRITORY FILTER
    # ============================================================

    if selected_territory:

        commission_entries = (
            commission_entries.filter(
                territory_id=selected_territory
            )
        )

    # ============================================================
    # REP COMMISSION
    # ============================================================

    rep_total = (
        commission_entries.aggregate(
            t=Sum("rep_amount")
        )["t"]
        or Decimal("0.00")
    )

    rep_total = rep_total.quantize(
        Decimal("0.01")
    )

    # ============================================================
    # SUPERVISOR COMMISSION
    # ============================================================

    supervisor_total = (
        commission_entries.aggregate(
            t=Sum("supervisor_amount")
        )["t"]
        or Decimal("0.00")
    )

    supervisor_total = supervisor_total.quantize(
        Decimal("0.01")
    )

    # ============================================================
    # TOTAL COMMISSION
    # ============================================================

    total_commission = (
        rep_total
        + supervisor_total
    ).quantize(
        Decimal("0.01")
    )

    # ============================================================
    # NEW BUSINESS BONUS
    # ============================================================
    #
    # New business bonus is based on the rep commission
    # attached to new-business CommissionEntry records.
    # ============================================================

    bonus_total = (
        commission_entries
        .filter(
            is_new_business=True
        )
        .aggregate(
            t=Sum("rep_amount")
        )["t"]
        or Decimal("0.00")
    )

    bonus_total = bonus_total.quantize(
        Decimal("0.01")
    )

    # ============================================================
    # REVENUE
    # ============================================================

    revenue_total = (
        commission_entries.aggregate(
            t=Sum(
                "invoice__order_total_inc"
            )
        )["t"]
        or Decimal("0.00")
    )

    revenue_total = revenue_total.quantize(
        Decimal("0.01")
    )

    # ============================================================
    # UNIQUE CLIENTS
    # ============================================================

    client_count = (
        commission_entries
        .values("client_id")
        .exclude(
            client_id=None
        )
        .distinct()
        .count()
    )

    # ============================================================
    # ORDERS / ENTRIES
    # ============================================================

    entry_count = commission_entries.count()

    # Because CommissionEntry has a OneToOne relationship
    # with Invoice, the number of commission entries also
    # represents the number of commission-generating invoices.
    order_count = entry_count

    # ============================================================
    # MONTHLY TARGET ALLOCATION
    # ============================================================
    #
    # IMPORTANT:
    #
    # We use MonthlyTargetAllocation for THIS REP and THIS
    # REPORTING PERIOD.
    #
    # The allocation stores:
    #
    #     monthly_target_value = revenue target
    #     client_target        = client target
    #
    # A rep may have allocations across multiple territories,
    # so we aggregate them rather than simply taking .first().
    # ============================================================

    allocation_qs = (
        MonthlyTargetAllocation.objects
        .select_related(
            "monthly_target",
            "monthly_target__territory",
            "sales_rep",
        )
        .filter(
            sales_rep=rep_user,
            monthly_target__year=target_year,
            monthly_target__month=month_code,
        )
    )

    # ------------------------------------------------------------
    # Territory filter
    # ------------------------------------------------------------

    if selected_territory:

        allocation_qs = (
            allocation_qs.filter(
                monthly_target__territory_id=(
                    selected_territory
                )
            )
        )

    # ------------------------------------------------------------
    # Area compatibility
    #
    # MonthlyTarget in the current model is territory based.
    # There is no area field in the model shown, so the area
    # filter is intentionally NOT applied here.
    #
    # Actual commission entries are still filtered by area.
    # ------------------------------------------------------------

    allocation_totals = (
        allocation_qs.aggregate(
            revenue_target=Coalesce(
                Sum(
                    "monthly_target_value"
                ),
                Decimal("0.00"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            ),
            client_target=Coalesce(
                Sum(
                    "client_target"
                ),
                0,
            ),
        )
    )

    revenue_target = (
        allocation_totals[
            "revenue_target"
        ]
        or Decimal("0.00")
    )

    revenue_target = revenue_target.quantize(
        Decimal("0.01")
    )

    client_target = (
        allocation_totals[
            "client_target"
        ]
        or 0
    )

    # ============================================================
    # REVENUE TARGET %
    # ============================================================

    if revenue_target > 0:

        revenue_target_pct = (
            revenue_total
            / revenue_target
            * Decimal("100")
        )

    else:

        revenue_target_pct = Decimal(
            "0.00"
        )

    revenue_target_pct = (
        revenue_target_pct.quantize(
            Decimal("0.01")
        )
    )

    # ============================================================
    # CLIENT TARGET %
    # ============================================================

    if client_target > 0:

        client_target_pct = (
            Decimal(client_count)
            / Decimal(client_target)
            * Decimal("100")
        )

    else:

        client_target_pct = Decimal(
            "0.00"
        )

    client_target_pct = (
        client_target_pct.quantize(
            Decimal("0.01")
        )
    )

    # ============================================================
    # REVENUE GAP
    # ============================================================

    revenue_gap = max(
        revenue_target - revenue_total,
        Decimal("0.00"),
    )

    revenue_gap = revenue_gap.quantize(
        Decimal("0.01")
    )

    # ============================================================
    # CLIENT GAP
    # ============================================================

    clients_needed_for_bonus = max(
        client_target - client_count,
        0,
    )

    # ============================================================
    # BONUS ACTIVE
    # ============================================================
    #
    # The accelerator/bonus only activates when BOTH:
    #
    #     1. Revenue target reached
    #     2. Client target reached
    #
    # This matches the Commission Centre logic.
    # ============================================================

    bonus_active = (
        revenue_total >= revenue_target
        and client_count >= client_target
        if (
            revenue_target > 0
            and client_target > 0
        )
        else False
    )

    # ============================================================
    # PERIOD WORKING DAYS
    # ============================================================

    working_days = 0

    current_day = period_start

    while current_day < period_end:

        if current_day.weekday() < 5:
            working_days += 1

        current_day += timedelta(
            days=1
        )

    if working_days <= 0:
        working_days = 1

    # ============================================================
    # DAYS PASSED
    # ============================================================

    effective_today = today

    if effective_today < period_start:

        days_passed = 0

    elif effective_today >= period_end:

        days_passed = working_days

    else:

        days_passed = 0

        current_day = period_start

        while current_day < effective_today:

            if current_day.weekday() < 5:
                days_passed += 1

            current_day += timedelta(
                days=1
            )

    days_remaining = max(
        working_days - days_passed,
        0,
    )

    # ============================================================
    # REQUIRED PER WEEK
    # ============================================================

    weeks_remaining = (
        Decimal(days_remaining)
        / Decimal("5")
    )

    if (
        weeks_remaining > 0
        and revenue_gap > 0
    ):

        required_per_week = (
            revenue_gap
            / weeks_remaining
        ).quantize(
            Decimal("0.01")
        )

    else:

        required_per_week = Decimal(
            "0.00"
        )

    # ============================================================
    # DAILY / WEEKLY AVERAGE
    # ============================================================

    if days_passed > 0:

        weekly_average = (
            revenue_total
            / Decimal(days_passed)
            * Decimal("5")
        ).quantize(
            Decimal("0.01")
        )

    else:

        weekly_average = Decimal(
            "0.00"
        )

    # ============================================================
    # COMMISSION TREND
    #
    # Keep the full selected calendar year for the chart,
    # but use paid_date for consistency with Commission Centre.
    # ============================================================

    commission_trend_labels = []
    commission_trend_data = []

    # Use the year in which the selected period ends.
    trend_year = target_year

    selected_trend_index = (
        target_month - 1
    )

    for month in range(1, 13):

        start = date(
            trend_year,
            month,
            1,
        )

        if month == 12:

            end = date(
                trend_year + 1,
                1,
                1,
            )

        else:

            end = date(
                trend_year,
                month + 1,
                1,
            )

        qs = (
            CommissionEntry.objects
            .filter(
                rep=rep_user,
                invoice__paid_date__gte=start,
                invoice__paid_date__lt=end,
            )
        )

        # Apply area filter to trend.

        if selected_area:

            qs = qs.filter(
                client__area=selected_area
            )

        # Apply territory filter to trend.

        if selected_territory:

            qs = qs.filter(
                territory_id=selected_territory
            )

        totals = qs.aggregate(
            rep_total=Coalesce(
                Sum("rep_amount"),
                Decimal("0.00"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            ),
            supervisor_total=Coalesce(
                Sum("supervisor_amount"),
                Decimal("0.00"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            ),
        )

        month_total = (
            totals["rep_total"]
            + totals["supervisor_total"]
        ).quantize(
            Decimal("0.01")
        )

        commission_trend_labels.append(
            f"{calendar.month_abbr[month]} "
            f"{trend_year}"
        )

        commission_trend_data.append(
            float(month_total)
        )

    # ============================================================
    # FILTER OPTIONS
    # ============================================================

    months = [
        {
            "value": i,
            "label": calendar.month_name[i],
        }
        for i in range(1, 13)
    ]

    years = list(
        range(
            today.year - 2,
            today.year + 3,
        )
    )

    # ============================================================
    # CONTEXT
    # ============================================================

    context = {

        # --------------------------------------------------------
        # REPRESENTATIVE
        # --------------------------------------------------------

        "rep_user":
            rep_user,

        # --------------------------------------------------------
        # COMMISSION ENTRIES
        # --------------------------------------------------------

        "commission_entries":
            commission_entries,

        "entry_count":
            entry_count,

        "order_count":
            order_count,

        # --------------------------------------------------------
        # REPORTING PERIOD
        # --------------------------------------------------------

        "period_start":
            period_start,

        "period_end":
            period_end,

        "selected_period":
            selected_period,

        "selected_month":
            target_month,

        "selected_year":
            target_year,

        "selected_month_name":
            calendar.month_name[
                target_month
            ],

        # --------------------------------------------------------
        # FILTERS
        # --------------------------------------------------------

        "selected_area":
            selected_area,

        "selected_territory":
            selected_territory,

        "months":
            months,

        "years":
            years,

        # --------------------------------------------------------
        # COMMISSION TOTALS
        # --------------------------------------------------------

        "rep_total":
            rep_total,

        "supervisor_total":
            supervisor_total,

        "total_commission":
            total_commission,

        "bonus_total":
            bonus_total,

        "revenue_total":
            revenue_total,

        "client_count":
            client_count,

        # --------------------------------------------------------
        # TARGETS
        # --------------------------------------------------------

        "revenue_target":
            revenue_target,

        "revenue_target_pct":
            revenue_target_pct,

        "revenue_gap":
            revenue_gap,

        "client_target":
            client_target,

        "client_target_pct":
            client_target_pct,

        "clients_needed_for_bonus":
            clients_needed_for_bonus,

        "bonus_active":
            bonus_active,

        # --------------------------------------------------------
        # PACING
        # --------------------------------------------------------

        "working_days":
            working_days,

        "days_passed":
            days_passed,

        "days_remaining":
            days_remaining,

        "required_per_week":
            required_per_week,

        "weekly_average":
            weekly_average,

        # --------------------------------------------------------
        # TREND
        # --------------------------------------------------------

        "commission_trend_labels":
            commission_trend_labels,

        "commission_trend_data":
            commission_trend_data,

        "selected_trend_index":
            selected_trend_index,
    }

    # ============================================================
    # RENDER
    # ============================================================

    return render(
        request,
        "commission/commission_rep_detail.html",
        context,
    )

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



@login_required
def sales_knowledge_list(request):
    """
    Sales Product Knowledge landing page.

    Lists products available to the sales team and provides
    search and filtering by:

    - Product name
    - SKU
    - Product number
    - Category
    - Sub-category
    - Minimum wholesale price
    - Maximum wholesale price
    """

    # -------------------------------------------------------------------------
    # BASE PRODUCT QUERYSET
    # -------------------------------------------------------------------------
    products = (
        Product.objects
        .select_related(
            "category",
            "category__parent",
            "knowledge",
        )
        .filter(
            visible="YES"
        )
        .order_by("name")
    )

    # -------------------------------------------------------------------------
    # SEARCH
    #
    # Searches:
    # - Product name
    # - SKU
    # - Product number
    # - Category name
    # - Parent category name
    # -------------------------------------------------------------------------
    q = (request.GET.get("q") or "").strip()

    if q:
        products = products.filter(
            Q(name__icontains=q)
            | Q(sku__icontains=q)
            | Q(product_no__icontains=q)
            | Q(category__name__icontains=q)
            | Q(category__parent__name__icontains=q)
        )

    # -------------------------------------------------------------------------
    # CATEGORY FILTER
    #
    # Selecting a parent category also includes products assigned directly
    # to that category as well as products belonging to its sub-categories.
    # -------------------------------------------------------------------------
    category_id = (request.GET.get("category") or "").strip()

    if category_id:
        products = products.filter(
            Q(category_id=category_id)
            | Q(category__parent_id=category_id)
        )

    # -------------------------------------------------------------------------
    # SUB-CATEGORY FILTER
    # -------------------------------------------------------------------------
    subcategory_id = (
        request.GET.get("subcategory") or ""
    ).strip()

    if subcategory_id:
        products = products.filter(
            category_id=subcategory_id
        )

    # -------------------------------------------------------------------------
    # MINIMUM PRICE FILTER
    # -------------------------------------------------------------------------
    min_price = (
        request.GET.get("min_price") or ""
    ).strip()

    if min_price:
        try:
            products = products.filter(
                wholesale_price__gte=float(min_price)
            )
        except (TypeError, ValueError):
            min_price = ""

    # -------------------------------------------------------------------------
    # MAXIMUM PRICE FILTER
    # -------------------------------------------------------------------------
    max_price = (
        request.GET.get("max_price") or ""
    ).strip()

    if max_price:
        try:
            products = products.filter(
                wholesale_price__lte=float(max_price)
            )
        except (TypeError, ValueError):
            max_price = ""

    # -------------------------------------------------------------------------
    # CATEGORY LIST
    #
    # Include both parent categories and sub-categories so the template
    # can populate the category and sub-category filters.
    # -------------------------------------------------------------------------
    categories = (
        Category.objects
        .filter(
            is_active=True
        )
        .select_related(
            "parent"
        )
        .order_by(
            "parent__name",
            "sort_order",
            "name",
        )
    )

    # -------------------------------------------------------------------------
    # RENDER
    # -------------------------------------------------------------------------
    return render(
        request,
        "product/product_knowledge_list.html",
        {
            "products": products,
            "categories": categories,

            # Search
            "search_query": q,

            # Category filters
            "selected_category": category_id,
            "selected_subcategory": subcategory_id,

            # Price filters
            "min_price": min_price,
            "max_price": max_price,
        },
    )

@login_required
def sales_product_knowledge_detail(request, pk):
    """
    Sales Product Knowledge detail page.

    Displays the current product information and Product Knowledge
    profile for the sales team.
    """

    product = get_object_or_404(
        Product.objects
        .select_related(
            "category",
            "category__parent",
            "knowledge",
        )
        .prefetch_related(
            "knowledge__customer_business_types",
            "knowledge__product_benefits",
            "knowledge__knowledge_variants",
            "knowledge__customer_alternatives",
            "knowledge__product_competitors",
            "knowledge__customer_questions",
            "knowledge__product_objections",
        ),
        pk=pk,
        visible="YES",
    )

    knowledge = product.knowledge

    return render(
        request,
        "product/product_knowledge_detail.html",
        {
            "product": product,
            "knowledge": knowledge,
        },
    )


@login_required
def sales_knowledge_compare(request):
    """
    Sales Product Comparison page.

    The selected product IDs are supplied by the browser through
    localStorage and then passed to this page through the query string.

    Example:
        /sales/sales-knowledge/compare/?products=1,4,7
    """

    product_ids = request.GET.get("products", "").strip()

    if not product_ids:
        return render(
            request,
            "product/product_knowledge_compare.html",
            {
                "products": [],
                "comparison_count": 0,
            },
        )

    # ---------------------------------------------------------
    # CLEAN PRODUCT IDS
    # ---------------------------------------------------------
    ids = []

    for value in product_ids.split(","):
        value = value.strip()

        if value.isdigit():
            ids.append(int(value))

    # Remove duplicates while preserving order
    ids = list(dict.fromkeys(ids))

    # Comparison is limited to 4 products
    ids = ids[:4]

    if not ids:
        return render(
            request,
            "product/product_knowledge_compare.html",
            {
                "products": [],
                "comparison_count": 0,
            },
        )

    # ---------------------------------------------------------
    # GET PRODUCTS
    # ---------------------------------------------------------
    products_qs = (
        Product.objects
        .select_related(
            "category",
            "category__parent",
            "knowledge",
        )
        .prefetch_related(
            "knowledge__customer_business_types",
            "knowledge__product_benefits",
            "knowledge__knowledge_variants",
            "knowledge__customer_alternatives",
            "knowledge__product_competitors",
            "knowledge__customer_questions",
            "knowledge__product_objections",
        )
        .filter(
            id__in=ids,
            visible="YES",
        )
    )

    # ---------------------------------------------------------
    # PRESERVE THE USER'S SELECTION ORDER
    # ---------------------------------------------------------
    products_by_id = {
        product.id: product
        for product in products_qs
    }

    products = [
        products_by_id[product_id]
        for product_id in ids
        if product_id in products_by_id
    ]

    return render(
        request,
        "product/product_knowledge_compare.html",
        {
            "products": products,
            "comparison_count": len(products),
        },
    )


    