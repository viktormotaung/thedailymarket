from django import forms
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q, Count
from .models import Client, ClientCompliance, ClientComplianceDocument
from products.models import Category
from django.contrib import messages
from orders.models import Order
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import transaction
from clients.models import Client, ClientCompliance, ClientComplianceDocument, Prospect, ProspectUpdate, Membership, Lead, LeadActivity
from clients.models import GAUTENG_CITY_CHOICES
from clients.forms import ProspectForm, ProspectUpdateForm
from tasks.models import Task
from credit.models import CreditAccount
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from django.db.models import Sum
from django.db.models.functions import Coalesce
from .forms import ClientEditForm, ClientComplianceForm, ClientComplianceDocumentForm, ClientComplianceDocumentStatusForm, ClientForm, ClientOperationsForm
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count
from django.utils import timezone
from collections import defaultdict
from .forms import LeadForm
from clients.models import Client, Prospect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def _bs(extra_class=None):
    """
    Bootstrap helper for form widgets.
    Usage:
      _bs() -> {"class": "form-control"}
      _bs("form-select") -> {"class": "form-select"}
    """
    return {
        "class": extra_class or "form-control"
    }
User = get_user_model()




def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url='/portal/client/login/')

@login_required
@staff_required
def client_list(request):
    qs = (
        Client.objects
        .select_related("account_manager")
        .order_by("name")
    )

    # Dropdown data (pulled from model choices so it stays in sync)
    client_types = Client.CLIENT_TYPES
    provinces = Client.PROVINCES
    account_types = Client.ACCOUNT_TYPES
    credit_statuses = Client.CREDIT_STATUS
    statuses = Client.STATUS
   

    # GET params
    search = (request.GET.get("search") or "").strip()
    client_type = request.GET.get("client_type") or ""
    province = request.GET.get("province") or ""
    account_type = request.GET.get("account_type") or ""
    credit_status = request.GET.get("credit_status") or ""
    status = request.GET.get("status") or ""
    

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
    

    clients = qs.distinct()

    return render(request, "clients/client_list.html", {
        "clients": clients,
        "client_types": client_types,
        "provinces": provinces,
        "account_types": account_types,
        "credit_statuses": credit_statuses,
        "statuses": statuses,
    })


@login_required
@staff_required
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            messages.success(request, f"Client '{client.name}' created successfully.")
            return redirect("client-view", pk=client.pk)
        messages.error(request, "Please fix the errors below.")
    else:
        form = ClientForm()

    return render(request, "clients/client_create.html", {"form": form})


@login_required
@staff_required
def client_edit(request, pk):
    client = get_object_or_404(
        Client.objects.select_related("account_manager"),
                      
        pk=pk
    )

    original_status = client.status

    if request.method == "POST":
        form = ClientEditForm(request.POST, instance=client)

        if form.is_valid():
            with transaction.atomic():
                updated_client = form.save()

                content_type = ContentType.objects.get_for_model(updated_client)
                latest_task = Task.objects.filter(
                    content_type=content_type,
                    object_id=updated_client.id
                ).order_by("-created_at").first()

                if latest_task:
                    latest_task.status = Task.Status.CLOSED
                    latest_task.completed_at = timezone.now()
                    latest_task.save(update_fields=["status", "completed_at", "updated_at"])

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

        # 🔥 DEBUG PRINT BLOCK
        print("\n========== FORM ERRORS ==========")
        print("Form errors dict:", form.errors)
        print("Non-field errors:", form.non_field_errors())
        for field in form:
            if field.errors:
                print(f"Field '{field.name}' errors:", field.errors)
        print("=================================\n")

        messages.error(request, "Please fix the errors below.")

    else:
        form = ClientEditForm(instance=client)

    return render(
        request,
        "clients/client_edit.html",
        {"form": form, "client": client},
    )


@login_required
@staff_required
def client_compliance_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)

    compliance, _ = ClientCompliance.objects.get_or_create(client=client)

    documents = (
        compliance.documents
        .select_related("reviewed_by", "uploaded_by")
        .all()
        .order_by("document_type")
    )

    compliance_form = ClientComplianceForm(instance=compliance)

    allowed_extensions = [".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"]
    max_file_size = 10 * 1024 * 1024  # 10MB

    # =====================================================
    # HELPER: VALIDATE UPLOADED FILE
    # =====================================================
    def validate_uploaded_file(uploaded_file):
        import os

        ext = os.path.splitext(uploaded_file.name)[1].lower()

        if ext not in allowed_extensions:
            return "Invalid file type. Allowed files: PDF, JPG, PNG, DOC, DOCX."

        if uploaded_file.size > max_file_size:
            return "File is too large. Maximum allowed size is 10MB."

        return None

    # =====================================================
    # HELPER: AUTO-RECALCULATE COMPLIANCE STATUS
    # =====================================================
    def recalculate_compliance_status():
        total_docs = compliance.documents.count()

        uploaded_docs = (
            compliance.documents
            .exclude(file="")
            .count()
        )

        approved_docs = compliance.documents.filter(
            status="APPROVED"
        ).count()

        rejected_exists = compliance.documents.filter(
            status="REJECTED"
        ).exists()

        # No documents or no uploads yet
        if total_docs == 0 or uploaded_docs == 0:
            compliance.vetting_status = "PENDING"
            compliance.vetted_by = None
            compliance.vetted_at = None

        # Any rejected document means compliance is rejected
        elif rejected_exists:
            compliance.vetting_status = "REJECTED"
            compliance.vetted_by = request.user
            compliance.vetted_at = timezone.now()

        # All required documents must be uploaded AND approved
        elif uploaded_docs == total_docs and approved_docs == total_docs:
            compliance.vetting_status = "APPROVED"
            compliance.vetted_by = request.user
            compliance.vetted_at = timezone.now()

        # Otherwise, still in review
        else:
            compliance.vetting_status = "IN_REVIEW"
            compliance.vetted_by = None
            compliance.vetted_at = None

        compliance.save(
            update_fields=[
                "vetting_status",
                "vetted_by",
                "vetted_at",
                "updated_at",
            ]
        )

    # =====================================================
    # POST HANDLING
    # =====================================================
    if request.method == "POST":

        # =====================================================
        # 1️⃣ SAVE OVERALL COMPLIANCE NOTES ONLY
        # =====================================================
        if "save_compliance" in request.POST:
            compliance_form = ClientComplianceForm(
                request.POST,
                instance=compliance
            )

            if compliance_form.is_valid():
                updated_compliance = compliance_form.save(commit=False)

                # System controls vetting_status automatically.
                # User may update notes, but status is recalculated.
                compliance.notes = updated_compliance.notes
                compliance.save(update_fields=["notes", "updated_at"])

                recalculate_compliance_status()

                messages.success(
                    request,
                    "Compliance notes saved and status recalculated successfully."
                )
                return redirect("client-compliance-edit", pk=client.pk)

            messages.error(
                request,
                "Please correct the compliance form errors."
            )

        # =====================================================
        # 2️⃣ UPLOAD / REPLACE DOCUMENT FILE
        # =====================================================
        elif "upload_document" in request.POST:
            document_id = request.POST.get("document_id")

            document = get_object_or_404(
                ClientComplianceDocument,
                pk=document_id,
                compliance=compliance,
            )

            uploaded_file = request.FILES.get("file")

            if not uploaded_file:
                messages.error(request, "Please select a file to upload.")
                return redirect("client-compliance-edit", pk=client.pk)

            file_error = validate_uploaded_file(uploaded_file)

            if file_error:
                messages.error(request, file_error)
                return redirect("client-compliance-edit", pk=client.pk)

            # Save/replace file
            document.file = uploaded_file
            document.uploaded_by = request.user

            # Reset review whenever file is uploaded/replaced
            document.status = "PENDING"
            document.reviewed_by = None
            document.reviewed_at = None
            document.notes = ""

            document.save()

            recalculate_compliance_status()

            messages.success(
                request,
                f"{document.get_document_type_display()} uploaded successfully. Document is now pending review."
            )
            return redirect("client-compliance-edit", pk=client.pk)

        # =====================================================
        # 3️⃣ SAVE INDIVIDUAL DOCUMENT REVIEW STATUS
        # =====================================================
        elif "save_document_status" in request.POST:
            document_id = request.POST.get("document_id")

            document = get_object_or_404(
                ClientComplianceDocument,
                pk=document_id,
                compliance=compliance,
            )

            if not document.file:
                messages.error(
                    request,
                    "You cannot review a document before a file has been uploaded."
                )
                return redirect("client-compliance-edit", pk=client.pk)

            document_status_form = ClientComplianceDocumentStatusForm(
                request.POST,
                instance=document
            )

            if document_status_form.is_valid():
                doc = document_status_form.save(commit=False)

                doc.reviewed_by = request.user
                doc.reviewed_at = timezone.now()
                doc.save()

                recalculate_compliance_status()

                messages.success(
                    request,
                    f"{doc.get_document_type_display()} reviewed successfully. Compliance status recalculated."
                )
                return redirect("client-compliance-edit", pk=client.pk)

            messages.error(
                request,
                "Please correct the document status errors."
            )

        else:
            messages.error(request, "Invalid compliance action.")
            return redirect("client-compliance-edit", pk=client.pk)

    # =====================================================
    # REFRESH DOCUMENTS AFTER POSSIBLE CHANGES
    # =====================================================
    documents = (
        compliance.documents
        .select_related("reviewed_by", "uploaded_by")
        .all()
        .order_by("document_type")
    )

    return render(
        request,
        "clients/client_compliance_edit.html",
        {
            "client": client,
            "compliance": compliance,
            "form": compliance_form,
            "documents": documents,
            "document_status_form_class": ClientComplianceDocumentStatusForm,
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


@login_required
@staff_required
def client_view(request, pk):
    client = get_object_or_404(
        Client.objects
        .select_related("account_manager", "funder")
        .prefetch_related("operating_hours"),
        pk=pk
    )

    client_orders_qs = Order.objects.filter(client=client)

    orders = (
        client_orders_qs
        .only("id", "order_date", "status", "grand_total_inc")
        .order_by("-order_date")[:10]
    )

    order_count = client_orders_qs.count()

    latest_order = (
        client_orders_qs
        .order_by("-order_date")
        .first()
    )

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

    compliance = getattr(client, "compliance", None)

    compliance_documents = []
    compliance_completion_pct = Decimal("0.00")
    compliance_total_docs = 0
    compliance_approved_docs = 0
    compliance_pending_docs = 0
    compliance_rejected_docs = 0

    if compliance:
        compliance_documents = (
            compliance.documents
            .select_related("reviewed_by", "uploaded_by")
            .all()
            .order_by("document_type")
        )

        compliance_total_docs = compliance_documents.count()
        compliance_approved_docs = compliance_documents.filter(status="APPROVED").count()
        compliance_pending_docs = compliance_documents.filter(status="PENDING").count()
        compliance_rejected_docs = compliance_documents.filter(status="REJECTED").count()

        if compliance_total_docs > 0:
            compliance_completion_pct = (
                Decimal(compliance_approved_docs) / Decimal(compliance_total_docs)
            ) * Decimal("100.00")

    total_spend = (
        client_orders_qs
        .aggregate(
            s=Coalesce(Sum("grand_total_inc"), Decimal("0.00"))
        )["s"]
    )

    days_active = (
        timezone.localdate() - client.created_at.date()
    ).days

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

    today_hours = client.get_today_hours()

    context = {
        "client": client,

        "days_active": days_active,
        "total_spend": total_spend,
        "spend_rank": spend_rank,
        "total_clients": total_clients,

        "today_hours": today_hours,

        "orders": orders,
        "order_count": order_count,
        "latest_order": latest_order,

        "credit_account": credit_account,
        "credit_utilization_pct": credit_utilization_pct,
        "credit_utilization_status": credit_utilization_status,

        "compliance": compliance,
        "compliance_documents": compliance_documents,
        "compliance_completion_pct": compliance_completion_pct,
        "compliance_total_docs": compliance_total_docs,
        "compliance_approved_docs": compliance_approved_docs,
        "compliance_pending_docs": compliance_pending_docs,
        "compliance_rejected_docs": compliance_rejected_docs,

        "success_message": request.GET.get("ok", ""),
        "error_message": request.GET.get("err", ""),
    }

    return render(
        request,
        "clients/client_view.html",
        context
    )



@login_required
@staff_required
def client_edit_operations(request, pk):
    client = get_object_or_404(Client, pk=pk)

    if request.method == "POST":
        form = ClientOperationsForm(
            request.POST,
            instance=client,
        )

        if form.is_valid():
            form.save()
            messages.success(request, "Operating hours updated successfully.")
            return redirect("client-edit-operations", pk=client.pk)

        messages.error(request, "Please correct the errors below.")

    else:
        form = ClientOperationsForm(
            instance=client,
        )

    return render(
        request,
        "clients/client_edit_operations.html",
        {
            "client": client,
            "form": form,
        },
    )



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
        "clients/prospects.html",
        context,
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
    return render(request, "clients/prospect_detail.html", context)





@login_required
@staff_required
def client_dashboard(request):

    today = timezone.now()
    start_of_month = today.replace(day=1)

    # --------------------------------------------------
    # PROSPECTS THIS MONTH
    # --------------------------------------------------
    prospects_this_month = Prospect.objects.filter(
        created_at__gte=start_of_month
    ).count()

    # --------------------------------------------------
    # CONVERSION RATE
    # --------------------------------------------------
    total_prospects = Prospect.objects.count()

    won_prospects = Prospect.objects.filter(
        stage="WON"
    ).count()

    conversion_rate = round(
        (won_prospects / total_prospects * 100),
        1
    ) if total_prospects else 0

    # --------------------------------------------------
    # CLIENT TOTALS
    # --------------------------------------------------
    total_clients = Client.objects.count()

    active_clients = Client.objects.filter(
        status="ACTIVE"
    ).count()

    inactive_clients = Client.objects.filter(
        status="INACTIVE"
    ).count()

    # --------------------------------------------------
    # CLIENT AREA BREAKDOWN
    # --------------------------------------------------
    area_summary = (
        Client.objects
        .values("area")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    area_percentages = []

    for row in area_summary:

        pct = round(
            (row["total"] / total_clients * 100),
            1
        ) if total_clients else 0

        area_percentages.append(
            {
                "area": row["area"],
                "count": row["total"],
                "percent": pct,
            }
        )

    # --------------------------------------------------
    # MAP DATA
    # --------------------------------------------------

    map_points = []

    # Active clients = GREEN
    for client in Client.objects.filter(
        status="ACTIVE"
    ).exclude(
        delivery_lat__isnull=True
    ).exclude(
        delivery_lng__isnull=True
    ):

        map_points.append({
            "type": "client",
            "status": "ACTIVE",
            "name": client.name,
            "lat": float(client.delivery_lat),
            "lng": float(client.delivery_lng),
            "color": "green",
        })

    # Inactive clients = RED
    for client in Client.objects.filter(
        status="INACTIVE"
    ).exclude(
        delivery_lat__isnull=True
    ).exclude(
        delivery_lng__isnull=True
    ):

        map_points.append({
            "type": "client",
            "status": "INACTIVE",
            "name": client.name,
            "lat": float(client.delivery_lat),
            "lng": float(client.delivery_lng),
            "color": "red",
        })

    # Active prospects = BLUE
    for prospect in Prospect.objects.exclude(
        stage="LOST"
    ).exclude(
        lat__isnull=True
    ).exclude(
        lng__isnull=True
    ):

        map_points.append({
            "type": "prospect",
            "status": prospect.stage,
            "name": prospect.name,
            "lat": float(prospect.lat),
            "lng": float(prospect.lng),
            "color": "blue",
        })

    # Lost prospects = RED
    for prospect in Prospect.objects.filter(
        stage="LOST"
    ).exclude(
        lat__isnull=True
    ).exclude(
        lng__isnull=True
    ):

        map_points.append({
            "type": "prospect",
            "status": "LOST",
            "name": prospect.name,
            "lat": float(prospect.lat),
            "lng": float(prospect.lng),
            "color": "red",
        })

    context = {

        # KPI cards
        "prospects_this_month": prospects_this_month,
        "total_prospects": total_prospects,
        "won_prospects": won_prospects,
        "conversion_rate": conversion_rate,

        "total_clients": total_clients,
        "active_clients": active_clients,
        "inactive_clients": inactive_clients,

        # Charts
        "area_percentages": area_percentages,

        # Map
        "map_points": map_points,
    }

    return render(
        request,
        "clients/client_dashboard.html",
        context,
    )


@login_required
@staff_required
def membership_list(request):

    memberships = (
        Membership.objects
        .select_related("client", "client__account_manager")
        .order_by("membership_number")
    )

    search = (request.GET.get("search") or "").strip()
    status = request.GET.get("status") or ""

    if search:
        memberships = memberships.filter(
            Q(membership_number__icontains=search)
            | Q(client__name__icontains=search)
            | Q(client__organization__icontains=search)
            | Q(client__contact_person__icontains=search)
            | Q(client__phone__icontains=search)
        )

    if status:
        memberships = memberships.filter(status=status)

    return render(
        request,
        "clients/membership_list.html",
        {
            "memberships": memberships,
            "statuses": Membership.STATUS_CHOICES,
        },
    )


@login_required
@staff_required
def membership_create(request):

    clients = (
        Client.objects
        .select_related("account_manager")
        .order_by("name")
    )

    search = (request.GET.get("search") or "").strip()
    membership_filter = request.GET.get("membership") or ""

    if search:
        clients = clients.filter(
            Q(name__icontains=search)
            | Q(organization__icontains=search)
            | Q(contact_person__icontains=search)
            | Q(phone__icontains=search)
        )

    # Attach membership (if any) to each client
    memberships = {
        m.client_id: m
        for m in Membership.objects.select_related("client")
    }

    client_list = []

    for client in clients:
        client.membership = memberships.get(client.id)
        client_list.append(client)

    if membership_filter == "linked":
        client_list = [
            client for client in client_list
            if client.membership
        ]

    elif membership_filter == "unlinked":
        client_list = [
            client for client in client_list
            if not client.membership
        ]

    context = {
        "title": "Create Membership",
        "clients": client_list,
    }

    return render(
        request,
        "clients/membership_create.html",
        context,
    )


@login_required
@staff_required
def membership_link(request, client_id):

    client = get_object_or_404(Client, pk=client_id)

    # Prevent duplicate memberships
    if Membership.objects.filter(client=client).exists():
        messages.warning(
            request,
            f"{client.name} already has a membership."
        )
        return redirect("membership-create")

    # Generate next membership number
    last = (
        Membership.objects
        .order_by("-id")
        .first()
    )

    if last and last.membership_number:
        try:
            next_number = int(last.membership_number.replace("MEM", "")) + 1
        except Exception:
            next_number = last.id + 1
    else:
        next_number = 1

    membership = Membership.objects.create(
        client=client,
        status="ACTIVE",
        source="ADMIN",
    )

    messages.success(
        request,
        f"{client.name} has been linked to membership {membership.membership_number}."
    )

    return redirect("membership-create")


@login_required
@staff_required
def membership_delink(request, membership_id):

    membership = get_object_or_404(
        Membership,
        pk=membership_id
    )

    client_name = membership.client.name

    membership.delete()

    messages.success(
        request,
        f"{client_name} has been delinked from Trade Assist."
    )

    return redirect("membership-create")


@login_required
@staff_required
def membership_view(request, pk):

    membership = get_object_or_404(
        Membership.objects.select_related("client"),
        pk=pk,
    )

    context = {
        "membership": membership,
        "title": "Membership Details",
    }

    return render(
        request,
        "clients/membership_view.html",
        context,
    )


@login_required
@staff_required
def membership_edit(request, pk):

    membership = get_object_or_404(
        Membership,
        pk=pk,
    )

    if request.method == "POST":

        membership.status = request.POST.get(
            "status",
            membership.status,
        )

        membership.source = request.POST.get(
            "source",
            membership.source,
        )

        membership.internal_notes = request.POST.get(
            "internal_notes",
            membership.internal_notes,
        )

        membership.save()

        messages.success(
            request,
            "Membership updated successfully.",
        )

        return redirect(
            "membership-view",
            pk=membership.pk,
        )

    context = {
        "membership": membership,
        "statuses": Membership.STATUS_CHOICES,
        "sources": Membership.SOURCE_CHOICES,
        "title": "Edit Membership",
    }

    return render(
        request,
        "clients/membership_edit.html",
        context,
    )




@login_required
@staff_required
def leads_list(request):

    qs = (
        Lead.objects
        .select_related(
            "assigned_to",
            "prospect",
        )
        .prefetch_related("product_interests")
        .order_by("-created_at")
    )

    # ---------------------------------------------
    # SEARCH
    # ---------------------------------------------
    q = (request.GET.get("q") or "").strip()

    if q:
        qs = qs.filter(
            Q(lead_number__icontains=q)
            | Q(business_name__icontains=q)
            | Q(contact_person__icontains=q)
            | Q(phone__icontains=q)
            | Q(whatsapp__icontains=q)
        )

    # ---------------------------------------------
    # STATUS
    # ---------------------------------------------
    status = (request.GET.get("status") or "").strip()

    if status:
        qs = qs.filter(status=status)

    # ---------------------------------------------
    # SOURCE
    # ---------------------------------------------
    source = (request.GET.get("source") or "").strip()

    if source:
        qs = qs.filter(source=source)

    context = {
        "leads": qs,
        "statuses": Lead.STATUS_CHOICES,
        "sources": Lead.SOURCE_CHOICES,
        "today": timezone.localdate(),
    }

    return render(
        request,
        "clients/leads_list.html",
        context,
    )




@login_required
def lead_view(request, pk):

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

    context = {

        "lead": lead,

        "activities": lead.activities.select_related(
            "user",
        ).order_by(
            "-occurred_at",
            "-created_at",
        ),

    }

    return render(
        request,
        "clients/lead_view.html",
        context,
    )


@login_required
@staff_required
def lead_edit(request, pk):

    lead = get_object_or_404(
        Lead,
        pk=pk,
    )

    if request.method == "POST":

        form = LeadForm(
            request.POST,
            instance=lead,
        )

        if form.is_valid():

            lead = form.save()

            LeadActivity.objects.create(
                lead=lead,
                activity_type="LEAD_UPDATED",
                notes="Lead details updated.",
                user=request.user,
            )

            messages.success(
                request,
                "Lead updated successfully.",
            )

            return redirect(
                "lead-view",
                pk=lead.pk,
            )

    else:

        form = LeadForm(
            instance=lead,
        )

    context = {

        "lead": lead,
        "form": form,

    }

    return render(
        request,
        "clients/lead_edit.html",
        context,
    )





@csrf_exempt
def respondio_create_lead(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "message": "POST requests only.",
            },
            status=405,
        )

    return JsonResponse(
        {
            "success": True,
            "message": "Respond.io endpoint is working.",
        }
    )