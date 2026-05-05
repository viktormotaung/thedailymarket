from django import forms
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
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
from clients.models import Client, ClientCompliance, ClientComplianceDocument
from clients.models import GAUTENG_CITY_CHOICES

from tasks.models import Task
from credit.models import CreditAccount
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from django.db.models import Sum
from django.db.models.functions import Coalesce
from .forms import ClientEditForm, ClientComplianceForm, ClientComplianceDocumentForm, ClientComplianceDocumentStatusForm, ClientForm, ClientOperationsForm
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

    return render(request, "clients/client_list.html", {
        "clients": clients,
        "filter_categories": filter_categories,
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
        Client.objects.select_related("account_manager")
                      .prefetch_related("categories"),
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
        .prefetch_related("categories", "operating_hours"),
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