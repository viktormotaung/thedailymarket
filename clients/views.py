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
from tasks.models import Task
from credit.models import CreditAccount
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from django.db.models import Sum
from django.db.models.functions import Coalesce
from .forms import ClientEditForm, ClientComplianceForm, ClientComplianceDocumentForm, ClientComplianceDocumentStatusForm

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

class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            # Identity & Ownership
            "entity_type",                 # ✅ ADDED
            "name",
            "organization",
            "client_type",
            "account_manager",
            "price_type",

            # Contact
            "contact_person",
            "email",
            "phone",
            "whatsapp",

            # Address
            "address_line1",
            "address_line2",
            "suburb",
            "city",
            "province",
            "postal_code",
            "country",

            # ✅ Delivery Address (ADD THESE)
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_suburb",
            "delivery_city",
            "delivery_province",
            "delivery_postal_code",
            "delivery_country",

            # Compliance
            "registration_identifier",
            "vat_number",

            # Categorisation & Account
            "categories",
            "status",
            "account_type",
            "credit_status",

            # Spend & Notes
            "estimated_weekly_spend",
            "notes",
        ]

        widgets = {
            # Text inputs
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

            "delivery_address_line1": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_address_line2": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_suburb": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_city": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_province": forms.Select(attrs={"class": "form-select"}),
            "delivery_postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_country": forms.TextInput(attrs={"class": "form-control"}),

            # Compliance
            "registration_identifier": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Company registration number or SA ID number",
            }),
            "vat_number": forms.TextInput(attrs={"class": "form-control"}),

            # Numbers
            "estimated_weekly_spend": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),

            # Notes
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 5}),

            # Selects
            "entity_type": forms.Select(attrs={"class": "form-select"}),   # ✅ ADDED
            "client_type": forms.Select(attrs={"class": "form-select"}),
            "account_manager": forms.Select(attrs={"class": "form-select"}),
            "province": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "account_type": forms.Select(attrs={"class": "form-select"}),
            "credit_status": forms.Select(attrs={"class": "form-select"}),
            "price_type": forms.Select(attrs={"class": "form-select"}),

            # Many-to-many
            "categories": forms.SelectMultiple(
                attrs={"class": "form-select", "size": "6"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Only active categories
        self.fields["categories"].queryset = (
            Category.objects.filter(is_active=True).order_by("name")
        )

        # Human-friendly labels
        self.fields["entity_type"].label = "Business Type"
        self.fields["registration_identifier"].label = "Registration / ID Number"

        # Placeholders
        self.fields["email"].widget.attrs.setdefault(
            "placeholder", "name@example.com"
        )
        self.fields["phone"].widget.attrs.setdefault(
            "placeholder", "e.g. 072 123 4567"
        )
        self.fields["whatsapp"].widget.attrs.setdefault(
            "placeholder", "e.g. 072 123 4567"
        )

        # Default price type
        if not self.instance.pk and not self.initial.get("price_type"):
            self.fields["price_type"].initial = "Retail"


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

    return render(
        request,
        "clients/client_edit.html",
        {"form": form, "client": client},
    )


@login_required
@staff_required
def client_compliance_edit(request, pk):
    # -----------------------------
    # Load client + compliance
    # -----------------------------
    client = get_object_or_404(Client, pk=pk)

    compliance, _ = ClientCompliance.objects.get_or_create(
        client=client
    )

    documents = (
        compliance.documents
        .all()
        .order_by("document_type")
    )

    # Default form (overall compliance)
    compliance_form = ClientComplianceForm(instance=compliance)

    # -----------------------------
    # POST handling
    # -----------------------------
    if request.method == "POST":

        # =====================================================
        # 1️⃣ SAVE OVERALL COMPLIANCE STATUS
        # =====================================================
        if "save_compliance" in request.POST:
            compliance_form = ClientComplianceForm(
                request.POST,
                instance=compliance
            )

            if compliance_form.is_valid():
                compliance = compliance_form.save(commit=False)

                # Audit only when decision is made
                if compliance.vetting_status in ("APPROVED", "REJECTED"):
                    compliance.vetted_by = request.user
                    compliance.vetted_at = timezone.now()

                compliance.save()

                messages.success(
                    request,
                    "Compliance vetting status updated successfully."
                )
                return redirect(
                    "client-compliance-edit",
                    pk=client.pk
                )

            messages.error(
                request,
                "Please correct the compliance form errors."
            )

        # =====================================================
        # 2️⃣ SAVE INDIVIDUAL DOCUMENT STATUS
        # =====================================================
        elif "save_document_status" in request.POST:
            document_id = request.POST.get("document_id")

            document = get_object_or_404(
                ClientComplianceDocument,
                pk=document_id,
                compliance=compliance,
            )

            document_status_form = ClientComplianceDocumentStatusForm(
                request.POST,
                instance=document
            )

            if document_status_form.is_valid():
                doc = document_status_form.save(commit=False)

                # Audit trail
                doc.reviewed_by = request.user
                doc.reviewed_at = timezone.now()
                doc.save()

                messages.success(
                    request,
                    f"{doc.get_document_type_display()} reviewed successfully."
                )
                return redirect(
                    "client-compliance-edit",
                    pk=client.pk
                )

            messages.error(
                request,
                "Please correct the document status errors."
            )

    # -----------------------------
    # Render page
    # -----------------------------
    return render(
        request,
        "clients/client_compliance_edit.html",
        {
            "client": client,
            "compliance": compliance,
            "form": compliance_form,
            "documents": documents,
            # used to instantiate per-row forms in template
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
        "clients/client_view.html",
        context
    )