# credit/views.py
import hashlib
import logging
import urllib.parse
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import transaction
from communications.models import CommunicationLog
from django.db.models import (
    DecimalField, F, OuterRef, Q, Subquery, Sum, Value
)
from django.db.models.functions import Coalesce
from django.forms import inlineformset_factory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from clients.models import Client
from profiles.models import CustomerProfile
from transactions.models import Transaction

from .forms import (
    CreditEditForm,
    FunderAllocationFormSet,
    FunderForm,
    FunderMemberFormSet,
    FunderMovementForm,
)
from .communication_services import send_credit_status_notifications

from .models import (
    CreditAccount,
    CreditEntry,
    CreditLog,
    Funder,
    FunderAllocation,
    FunderMember,
    FunderMovement,
    FunderWeekSummary,
)

logger = logging.getLogger(__name__)


def r2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def staff_check(user):
    return user.is_authenticated and user.is_staff

staff_required = user_passes_test(staff_check, login_url="/portal/client/login/")


@login_required
@staff_required
def credit_list(request):
    """
    Trade Assist customer-facility portfolio.
    Reserved funder capital is shown separately from facility limit and usage.
    """
    zero = Decimal("0.00")
    funder_fields = {field.name for field in Funder._meta.get_fields()}

    if "is_active_for_new_business" in funder_fields:
        active_funder = Funder.objects.filter(
            is_active_for_new_business=True
        ).order_by("id").first()
    else:
        active_funder = (
            Funder.objects.order_by("id").first()
            if Funder.objects.count() == 1 else None
        )

    allocation_qs = FunderAllocation.objects.filter(
        client_id=OuterRef("client_id")
    )
    if active_funder:
        allocation_qs = allocation_qs.filter(funder_id=active_funder.pk)

    qs = (
        CreditAccount.objects.select_related("client", "funder")
        .annotate(
            available_amount=Coalesce(
                F("credit_limit") - F("credit_used"),
                Value(zero),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            reserved_amount=Coalesce(
                Subquery(allocation_qs.values("amount")[:1]),
                Value(zero),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        .order_by("-updated_at", "client__name")
    )

    client_id = (request.GET.get("client") or "").strip()
    min_limit = (request.GET.get("min_limit") or "").strip()
    max_limit = (request.GET.get("max_limit") or "").strip()
    status_filter = (request.GET.get("status") or "").strip().upper()

    if client_id.isdigit():
        qs = qs.filter(client_id=int(client_id))

    def to_decimal(value):
        try:
            return Decimal(value)
        except (TypeError, ValueError, ArithmeticError):
            return None

    if min_limit:
        value = to_decimal(min_limit)
        if value is not None:
            qs = qs.filter(credit_limit__gte=value)
    if max_limit:
        value = to_decimal(max_limit)
        if value is not None:
            qs = qs.filter(credit_limit__lte=value)

    account_fields = {field.name for field in CreditAccount._meta.get_fields()}
    if status_filter and "status" in account_fields:
        qs = qs.filter(status=status_filter)

    totals = qs.aggregate(
        total_limit=Coalesce(Sum("credit_limit"), Value(zero)),
        total_used=Coalesce(Sum("credit_used"), Value(zero)),
        total_available=Coalesce(Sum("available_amount"), Value(zero)),
        total_reserved=Coalesce(Sum("reserved_amount"), Value(zero)),
    )

    funder_balance = active_funder.balance if active_funder else zero
    funder_reserved = active_funder.total_allocated() if active_funder else zero
    funder_unallocated = max(zero, funder_balance - funder_reserved)

    percent_used_total = zero
    if totals["total_limit"]:
        percent_used_total = (
            totals["total_used"] / totals["total_limit"] * Decimal("100")
        ).quantize(Decimal("0.01"))

    page_obj = Paginator(qs, 25).get_page(request.GET.get("page", 1))
    return render(request, "credit/credit_list.html", {
        "credit_accounts": page_obj.object_list,
        "page_obj": page_obj,
        "clients": Client.objects.order_by("name").only("id", "name"),
        "request": request,
        "active_funder": active_funder,
        "funder_balance": funder_balance,
        "total_funder_reserved": funder_reserved,
        "unallocated_funder_capital": funder_unallocated,
        "total_limit": totals["total_limit"],
        "total_used": totals["total_used"],
        "total_available": totals["total_available"],
        "total_reserved": totals["total_reserved"],
        "percent_used_total": percent_used_total,
        "status_filter": status_filter,
    })


@login_required
@staff_required
def credit_edit(request, client_id):
    """Edit a customer's Trade Assist facility and keep its capital reservation in sync."""
    client = get_object_or_404(Client, pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)

    # CreditAccount.status is the authoritative buying-power status.
    # Client.credit_status is retained as a legacy/client-facing mirror.
    original_account_status = (
        account.status or CreditAccount.STATUS_PENDING
    ).upper()
    zero = Decimal("0.00")

    if request.method == "POST":
        form = CreditEditForm(request.POST)

        if form.is_valid():
            new_account_type = form.cleaned_data["account_type"]
            # The form uses Client.CREDIT_STATUS values (normally lowercase),
            # while CreditAccount stores its status in uppercase.
            new_credit_status = (form.cleaned_data["credit_status"] or "").strip().lower()
            new_account_status = new_credit_status.upper()
            valid_account_statuses = {
                value for value, _label in CreditAccount.STATUS_CHOICES
            }
            if new_account_status not in valid_account_statuses:
                form.add_error(
                    "credit_status",
                    "Select a valid buying-power status.",
                )
                raise ValueError("The selected buying-power status is invalid.")
            new_limit = r2(form.cleaned_data["credit_limit"] or zero)
            new_payment_term = form.cleaned_data["payment_term"]
            new_deposit_pct = form.cleaned_data["credit_deposit_pct"]
            note = form.cleaned_data.get("note") or ""
            new_funder = form.cleaned_data.get("funder")

            try:
                with transaction.atomic():
                    # Lock the account before changing its facility or funding link.
                    account = CreditAccount.objects.select_for_update().get(pk=account.pk)
                    current_limit = r2(account.credit_limit or zero)
                    current_used = r2(account.credit_used or zero)

                    if new_limit < current_used:
                        raise ValueError(
                            f"The facility cannot be reduced below the current outstanding amount "
                            f"of R{current_used:,.2f}."
                        )

                    # A funding relationship is not silently transferred here. This avoids
                    # leaving a historical reservation behind under the previous funder.
                    if account.funder_id and not new_funder:
                        raise ValueError(
                            "This customer already has a funder linked. Keep that funder selected; "
                            "do not clear the funding source while editing the facility."
                        )

                    if account.funder_id and new_funder and account.funder_id != new_funder.pk:
                        raise ValueError(
                            "This customer is already linked to another funder. "
                            "Manage the funder relationship from the funder allocation screen."
                        )

                    other_client_allocations = FunderAllocation.objects.filter(
                        client=client
                    )
                    if new_funder:
                        other_client_allocations = other_client_allocations.exclude(
                            funder_id=new_funder.pk
                        )
                    if other_client_allocations.exists():
                        raise ValueError(
                            "A reservation already exists for this customer under another funder. "
                            "Resolve that historical allocation before creating a new one."
                        )

                    if new_limit > zero and not new_funder:
                        raise ValueError("Select the funder backing this buying-power limit.")

                    if new_funder:
                        funder_fields = {f.name for f in Funder._meta.get_fields()}
                        if "is_active_for_new_business" in funder_fields:
                            if not new_funder.is_active_for_new_business and account.funder_id != new_funder.pk:
                                raise ValueError(
                                    "This funder is not active for new business and cannot receive a new allocation."
                                )

                        # Lock the funder and its reservation row to avoid competing edits.
                        locked_funder = Funder.objects.select_for_update().get(pk=new_funder.pk)
                        allocation = (
                            FunderAllocation.objects.select_for_update()
                            .filter(funder=locked_funder, client=client)
                            .first()
                        )

                        already_reserved = (
                            locked_funder.total_allocated()
                            - (allocation.amount if allocation else zero)
                        )
                        available_for_this_customer = max(
                            zero, r2((locked_funder.balance or zero) - already_reserved)
                        )
                        if new_limit > available_for_this_customer:
                            raise ValueError(
                                f"The requested limit of R{new_limit:,.2f} exceeds the funder's "
                                f"available unallocated capital of R{available_for_this_customer:,.2f}."
                            )

                        if allocation is None:
                            allocation = FunderAllocation(
                                funder=locked_funder,
                                client=client,
                                amount=new_limit,
                            )
                            allocation.save()
                        elif r2(allocation.amount or zero) != new_limit:
                            allocation.amount = new_limit
                            allocation.save()

                        # FunderAllocation.save() links the account to the funder.
                        account.refresh_from_db()

                    # Synchronise the legacy Client status mirror and the
                    # authoritative CreditAccount status in the same transaction.
                    client_updates = []
                    if client.account_type != new_account_type:
                        client.account_type = new_account_type
                        client_updates.append("account_type")
                    if (client.credit_status or "").lower() != new_credit_status:
                        client.credit_status = new_credit_status
                        client_updates.append("credit_status")
                    if client_updates:
                        client.save(update_fields=client_updates)

                    account_rule_updates = []
                    if account.status != new_account_status:
                        account.status = new_account_status
                        account_rule_updates.append("status")

                    # Update account terms separately from limit audit.
                    rule_updates = account_rule_updates
                    if account.payment_term != new_payment_term:
                        account.payment_term = new_payment_term
                        rule_updates.append("payment_term")
                    if account.credit_deposit_pct != new_deposit_pct:
                        account.credit_deposit_pct = new_deposit_pct
                        rule_updates.append("credit_deposit_pct")
                    if rule_updates:
                        account.save(update_fields=rule_updates + ["updated_at"])

                    # The reservation is updated first; the facility limit is then
                    # changed through the audited model method.
                    if new_limit != current_limit:
                        account.set_limit(
                            new_limit,
                            authorised_by=request.user,
                            note=note or "Customer facility limit updated.",
                        )

                    # Notify only when the authoritative facility status changes.
                    # on_commit prevents an email being sent if the database update rolls back.
                    if original_account_status != new_account_status:
                        previous_status = original_account_status or "UNSET"
                        updated_status = new_account_status or "UNSET"
                        transaction.on_commit(
                            lambda client_id=client.pk,
                                   old_status=previous_status,
                                   new_status=updated_status,
                                   actor_id=request.user.pk:
                                _send_status_notifications_from_view(
                                    client_id=client_id,
                                    previous_status=old_status,
                                    new_status=new_status,
                                    sent_by_id=actor_id,
                                ),
                            robust=True,
                        )

                messages.success(
                    request,
                    "Trade Assist customer settings and funder allocation updated."
                )
                return redirect("credit-view", client_id=client.id)

            except (ValueError, ValidationError) as exc:
                form.add_error(None, str(exc))
                messages.error(request, "The changes were not saved. Please review the message below.")

    else:
        form = CreditEditForm(initial={
            "account_type": client.account_type,
            # Use the facility status, not the potentially stale legacy client field.
            "credit_status": (account.status or CreditAccount.STATUS_PENDING).lower(),
            "credit_limit": account.credit_limit,
            "payment_term": account.payment_term,
            "credit_deposit_pct": account.credit_deposit_pct,
            "funder": account.funder_id,
            "note": "",
        })

    funder = account.funder
    allocation = None
    funder_balance = zero
    funder_reserved = zero
    funder_unallocated = zero
    if funder:
        allocation = FunderAllocation.objects.filter(funder=funder, client=client).first()
        funder_balance = r2(funder.balance or zero)
        funder_reserved = r2(funder.total_allocated())
        funder_unallocated = max(zero, r2(funder_balance - funder_reserved))

    return render(request, "credit/credit_edit.html", {
        "client": client,
        "account": account,
        "form": form,
        "limit": r2(account.credit_limit or zero),
        "used": r2(account.credit_used or zero),
        "available": r2(account.credit_available or zero),
        "allocation": allocation,
        "funder_balance": funder_balance,
        "funder_reserved": funder_reserved,
        "funder_unallocated": funder_unallocated,
    })



def _create_email_communication_log(
    *,
    recipient,
    recipient_name="",
    subject="",
    message="",
    related_object=None,
    sent_by=None,
):
    """
    Create a CommunicationLog row before attempting delivery.

    A log is created even if the email subsequently fails. The log model is
    the single communication audit trail used by this view.
    """
    related_model = None
    related_object_id = None

    if related_object is not None:
        related_model = related_object.__class__.__name__
        related_object_id = related_object.pk

    return CommunicationLog.objects.create(
        channel=CommunicationLog.CHANNEL_EMAIL,
        status=CommunicationLog.STATUS_PENDING,
        recipient_name=recipient_name or None,
        recipient_contact=(recipient or "").strip() or "Unavailable recipient",
        subject=(subject or "")[:255] or None,
        message=message or "",
        related_model=related_model,
        related_object_id=related_object_id,
        provider="Django email backend",
        sent_by=sent_by if getattr(sent_by, "pk", None) else None,
    )


def _send_email_and_update_log(*, communication, email_message):
    """
    Send an EmailMultiAlternatives message and persist the delivery attempt.

    Django's email backend confirms that the message was accepted for sending;
    it does not, by itself, prove that the recipient's mailbox delivered it.
    """
    try:
        sent_count = email_message.send(fail_silently=False)

        if sent_count:
            communication.status = CommunicationLog.STATUS_SENT
            communication.sent_at = now()
            communication.error_message = ""
            communication.provider_response = {
                "backend": "Django email backend",
                "accepted_count": sent_count,
            }
            communication.save(update_fields=[
                "status",
                "sent_at",
                "error_message",
                "provider_response",
                "updated_at",
            ])
            return True

        communication.status = CommunicationLog.STATUS_FAILED
        communication.failed_at = now()
        communication.error_message = (
            "The configured email backend did not accept the message."
        )
        communication.provider_response = {
            "backend": "Django email backend",
            "accepted_count": 0,
        }
        communication.save(update_fields=[
            "status",
            "failed_at",
            "error_message",
            "provider_response",
            "updated_at",
        ])
        logger.error(
            "Email backend did not accept communication log %s.",
            communication.pk,
        )
        return False

    except Exception as exc:
        communication.status = CommunicationLog.STATUS_FAILED
        communication.failed_at = now()
        communication.error_message = str(exc)
        communication.provider_response = {
            "backend": "Django email backend",
            "exception_type": exc.__class__.__name__,
        }
        communication.save(update_fields=[
            "status",
            "failed_at",
            "error_message",
            "provider_response",
            "updated_at",
        ])
        logger.exception(
            "Email delivery failed for communication log %s.",
            communication.pk,
        )
        return False


def _send_status_notifications_from_view(
    *, client_id, previous_status, new_status, sent_by_id=None
):
    """Resolve the staff actor and send both tracked status communications."""
    sent_by = None
    if sent_by_id:
        from django.contrib.auth import get_user_model
        sent_by = get_user_model().objects.filter(pk=sent_by_id).first()
    return send_credit_status_notifications(
        client_id=client_id,
        previous_status=previous_status,
        new_status=new_status,
        sent_by=sent_by,
    )


def send_email_credit_status_changed(
    client_id,
    previous_status,
    new_status,
    sent_by=None,
    sent_by_id=None,
):
    """
    Send a branded customer status email and register the attempt in
    CommunicationLog, whether delivery succeeds or fails.
    """
    if sent_by is None and sent_by_id:
        from django.contrib.auth import get_user_model
        sent_by = get_user_model().objects.filter(pk=sent_by_id).first()

    client = Client.objects.select_related("credit_account").get(pk=client_id)

    customer_profile = (
        client.customer_profiles
        .select_related("user")
        .filter(user__email__gt="")
        .first()
    )
    user = getattr(customer_profile, "user", None)
    recipient_email = (
        getattr(user, "email", None)
        or getattr(client, "email", None)
        or ""
    ).strip()

    recipient_name = (
        user.get_short_name()
        if user and hasattr(user, "get_short_name")
        else ""
    ) or getattr(client, "contact_person", None) or client.name or "there"

    status_key = (new_status or "").strip().lower().replace(" ", "_")
    template_by_status = {
        "pending": "email/credit/status_pending.html",
        "active": "email/credit/status_active.html",
        "overdue": "email/credit/status_overdue.html",
        "suspended": "email/credit/status_suspended.html",
        "closed": "email/credit/status_closed.html",
    }
    subject_by_status = {
        "pending": "Trade Assist account under review – The Daily Market",
        "active": "Your Trade Assist buying power is active – The Daily Market",
        "overdue": "Action required: Trade Assist settlement overdue",
        "suspended": "Trade Assist account suspended – The Daily Market",
        "closed": "Trade Assist account closure confirmation – The Daily Market",
    }

    subject = subject_by_status.get(
        status_key,
        "Trade Assist account status update – The Daily Market",
    )

    # Log the attempt before rendering or sending, so template errors and
    # missing customer email addresses are also visible to staff.
    communication = _create_email_communication_log(
        recipient=recipient_email,
        recipient_name=recipient_name,
        subject=subject,
        related_object=client,
        sent_by=sent_by,
    )

    if not recipient_email:
        communication.status = CommunicationLog.STATUS_FAILED
        communication.failed_at = now()
        communication.error_message = (
            "No customer email address was found on the linked "
            "CustomerProfile user or Client record."
        )
        communication.save(update_fields=[
            "status", "failed_at", "error_message", "updated_at",
        ])
        logger.warning(
            "Credit-status email not sent for client %s: no recipient email.",
            client_id,
        )
        return False

    template_name = template_by_status.get(status_key)
    if not template_name:
        communication.status = CommunicationLog.STATUS_FAILED
        communication.failed_at = now()
        communication.error_message = (
            f"Unsupported client credit status: {new_status!r}."
        )
        communication.save(update_fields=[
            "status", "failed_at", "error_message", "updated_at",
        ])
        return False

    try:
        account = getattr(client, "credit_account", None)
        zero = Decimal("0.00")
        credit_limit = account.credit_limit if account else zero
        outstanding_balance = account.credit_used if account else zero
        available_buying_power = max(
            zero, credit_limit - outstanding_balance
        )

        buying_power_available = status_key == "active"
        contribution_pct = (
            getattr(account, "credit_deposit_pct", None)
            if account else None
        )
        if contribution_pct is None:
            contribution_pct = Decimal("100.00")

        term = getattr(account, "payment_term", None) if account else None
        payment_term_label = {
            "0D": "Prepaid",
            "1D": "1 day",
            "3D": "3 days",
            "7D": "7 days",
        }.get(term, term or "Not specified")

        account_manager = getattr(client, "account_manager", None)
        account_manager_name = ""
        if account_manager:
            account_manager_name = (
                getattr(account_manager, "get_full_name", lambda: "")()
                or getattr(account_manager, "first_name", "")
                or getattr(account_manager, "username", "")
            )

        support_email = getattr(
            settings,
            "SUPPORT_EMAIL",
            "support@thedailymarket.co.za",
        )

        context = {
            "client": client,
            "account": account,
            "customer_name": recipient_name,
            "previous_status": (
                previous_status or "UNSET"
            ).replace("_", " ").title(),
            "new_status": (
                new_status or "UNSET"
            ).replace("_", " ").title(),
            "credit_limit": credit_limit or zero,
            "outstanding_balance": outstanding_balance or zero,
            "available_buying_power": available_buying_power,
            "buying_power_available": buying_power_available,
            "contribution_pct": contribution_pct,
            "payment_term_label": payment_term_label,
            "account_manager_name": account_manager_name,
            "support_email": support_email,
        }

        html_body = render_to_string(template_name, context)
        text_body = (
            f"Hello {recipient_name},\n\n"
            f"Your Trade Assist account status has changed from "
            f"{context['previous_status']} to {context['new_status']}.\n\n"
            f"Approved buying power: R{credit_limit:,.2f}\n"
            f"Outstanding balance: R{outstanding_balance:,.2f}\n"
            f"Available buying power: "
            f"{f'R{available_buying_power:,.2f}' if buying_power_available else 'Unavailable'}\n"
            f"Your upfront contribution: {contribution_pct}%\n"
            f"Settlement term: {payment_term_label}\n\n"
            f"For assistance, contact {support_email} or call 087 265 5488.\n\n"
            "Regards,\nThe Daily Market Team"
        )

        communication.message = text_body
        communication.save(update_fields=["message", "updated_at"])

        email_message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
            headers={"Reply-To": support_email},
        )
        email_message.attach_alternative(html_body, "text/html")

        return _send_email_and_update_log(
            communication=communication,
            email_message=email_message,
        )

    except Exception as exc:
        communication.status = CommunicationLog.STATUS_FAILED
        communication.failed_at = now()
        communication.error_message = str(exc)
        communication.provider_response = {
            "stage": "message_preparation",
            "exception_type": exc.__class__.__name__,
        }
        communication.save(update_fields=[
            "status",
            "failed_at",
            "error_message",
            "provider_response",
            "updated_at",
        ])
        logger.exception(
            "Could not prepare credit-status email for client %s.",
            client_id,
        )
        return False


@login_required
@staff_required
def credit_client_view(request, client_id):
    from decimal import Decimal
    from django.db.models import Sum, Q, Value, DecimalField
    from django.db.models.functions import Coalesce

    # ------------------------------------------------------------------
    # Client & Credit Account
    # ------------------------------------------------------------------
    client = get_object_or_404(
        Client.objects.select_related("credit_account"),
        pk=client_id,
    )
    account, _ = CreditAccount.objects.get_or_create(client=client)

    # ------------------------------------------------------------------
    # Credit Logs (LIMIT AUDIT)
    # ------------------------------------------------------------------
    logs = (
        account.logs
        .select_related("authorised_by")
        .order_by("-created_at")
    )

    # ------------------------------------------------------------------
    # Credit-related Transactions (REFERENCE ONLY)
    # ------------------------------------------------------------------
    transactions = (
        Transaction.objects
        .select_related("invoice")
        .filter(
            client=client,
            transaction_type__in=[
                "credit_usage",
                "credit_repayment",
                "credit_issue",
                "adjustment",
            ],
        )
        .order_by("-created_at", "-id")
    )

    # ------------------------------------------------------------------
    # Account-level Snapshots (LIMIT / RISK)
    # ------------------------------------------------------------------
    credit_limit = account.credit_limit or Decimal("0.00")
    credit_used = account.credit_used or Decimal("0.00")

    raw_available = credit_limit - credit_used
    credit_available = max(Decimal("0.00"), raw_available)

    over_limit_amount = (
        abs(raw_available) if raw_available < 0 else Decimal("0.00")
    )

    percent_used = (
        Decimal("0.00")
        if credit_limit <= 0
        else (credit_used / credit_limit) * Decimal("100")
    )

    # ------------------------------------------------------------------
    # Open Credit Exposure Per Invoice (RISK)
    # ------------------------------------------------------------------
    exposure_raw = (
        CreditEntry.objects
        .filter(
            credit_account=account,
            invoice__isnull=False,
        )
        .values(
            "invoice_id",
            "invoice__invoice_date",
            "invoice__due_date",
            "invoice__status",
            "invoice__settlement_due_date",
            "invoice__settlement_status",
            "invoice__order_id",
        )
        .annotate(
            credit_used=Coalesce(
                Sum("amount", filter=Q(kind=CreditEntry.USAGE)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            credit_repaid=Coalesce(
                Sum("amount", filter=Q(kind=CreditEntry.REPAYMENT)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        )
    )

    open_invoices = []
    for row in exposure_raw:
        outstanding = row["credit_used"] - row["credit_repaid"]
        if outstanding > 0:
            open_invoices.append({
                "invoice_id": row["invoice_id"],
                "invoice_date": row["invoice__invoice_date"],
                "due_date": row["invoice__due_date"],
                "status": row["invoice__status"],
                "settlement_due_date": row["invoice__settlement_due_date"],
                "settlement_status": row["invoice__settlement_status"],
                "credit_used": row["credit_used"],
                "credit_repaid": row["credit_repaid"],
                "outstanding": outstanding,
                "order_id": row["invoice__order_id"],
            })

    open_credit_total = credit_used

    # ------------------------------------------------------------------
    # CREDIT WALLET LEDGER (MONEY ONLY)
    # ------------------------------------------------------------------
    credit_entries = list(
        account.entries
        .select_related("invoice", "transaction")
        .order_by("posted_at", "id")  # OLDEST → NEWEST
    )

    for entry in credit_entries:
        entry.running_balance = entry.balance

    credit_entries.reverse()

    # ------------------------------------------------------------------
    # FUNDER — Unallocated Capital
    # ------------------------------------------------------------------
    funder = account.funder
    allocatable_balance = Decimal("0.00")

    if funder:
        funder_balance = funder.balance or Decimal("0.00")
        reserved_capital = funder.total_allocated()
        allocatable_balance = max(
            Decimal("0.00"),
            funder_balance - reserved_capital,
        )


    


    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    return render(
        request,
        "credit/credit_view.html",
        {
            "client": client,
            "account": account,
            "logs": logs,
            "transactions": transactions,

            # Limit / Risk
            "credit_limit": credit_limit,
            "credit_used": credit_used,
            "credit_available": credit_available,
            "over_limit_amount": over_limit_amount,
            "percent_used": percent_used.quantize(Decimal("0.01")),

            # Exposure
            "open_invoices": open_invoices,
            "open_credit_total": open_credit_total,

            # Wallet
            "credit_entries": credit_entries,

            # Funder
            "funder": funder,
            "allocatable_balance": allocatable_balance,
        },
    )

@login_required
@staff_required
@require_POST
def credit_confirm_payment(request, client_id):
    """
    Capture a verified repayment against one selected invoice only.
    The invoice model creates the invoice-linked CreditEntry and updates
    settlement balances; account-wide repayments are intentionally disabled.
    """
    from invoices.models import Invoice

    client = get_object_or_404(Client, pk=client_id)
    invoice_id = (request.POST.get("invoice_id") or "").strip()
    reference = (request.POST.get("reference") or "").strip()
    amount_raw = (request.POST.get("amount") or "").strip()

    if not invoice_id.isdigit():
        messages.error(request, "Select the invoice being repaid.")
        return redirect("credit-view", client_id=client.id)

    invoice = get_object_or_404(Invoice, pk=int(invoice_id), client=client)

    try:
        amount = Decimal(amount_raw)
    except Exception:
        amount = Decimal("0.00")

    if amount <= 0:
        messages.error(request, "Enter a repayment amount greater than zero.")
        return redirect("credit-view", client_id=client.id)

    try:
        entry = invoice.record_credit_repayment(
            amount,
            reference=reference,
            note=f"Invoice-specific repayment captured by {request.user}.",
        )
    except Exception as exc:
        messages.error(request, f"Repayment was not recorded: {exc}")
        return redirect("credit-view", client_id=client.id)

    messages.success(
        request,
        f"R{entry.amount:.2f} repayment allocated to invoice #{invoice.id}."
    )
    return redirect("credit-view", client_id=client.id)



def generate_payfast_request(request, invoice_id):
    invoice = get_object_or_404(
        Invoice.objects.select_related("order", "order__client"),
        pk=invoice_id
    )

    data = [
        ("merchant_id", settings.PAYFAST_MERCHANT_ID),
        ("merchant_key", settings.PAYFAST_MERCHANT_KEY),
        ("return_url", "https://yourdomain.co.za/payfast/return/"),
        ("cancel_url", "https://yourdomain.co.za/payfast/cancel/"),
        ("notify_url", "https://yourdomain.co.za/payfast/itn/"),

        ("name_first", invoice.order.client.contact_person.split()[0]),
        ("name_last", invoice.order.client.contact_person.split()[-1]),
        ("email_address", invoice.order.client.email),

        ("m_payment_id", f"INV-{invoice.id}"),
        ("amount", f"{invoice.amount_due:.2f}"),
        ("item_name", f"Invoice #{invoice.id}"),
    ]

    signature = generate_payfast_signature(
        data=data,
        passphrase=settings.PAYFAST_PASSPHRASE
    )

    payfast_data = dict(data)
    payfast_data["signature"] = signature

    # Build the full PayFast URL
    from urllib.parse import urlencode
    payfast_link = f"{settings.PAYFAST_PROCESS_URL}?{urlencode(payfast_data)}"

    return JsonResponse({"payment_url": payfast_link})

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
@staff_required
def credit_send_request(request, client_id):
    """Email a PayFast request for one invoice's outstanding TA settlement."""
    from invoices.models import Invoice

    client = get_object_or_404(Client, pk=client_id)
    invoice_id = (request.GET.get("invoice_id") or request.POST.get("invoice_id") or "").strip()
    if not invoice_id.isdigit():
        return JsonResponse({
            "success": False,
            "message": "An invoice_id is required. Repayment requests are invoice-specific."
        }, status=400)

    invoice = get_object_or_404(Invoice, pk=int(invoice_id), client=client)
    outstanding = invoice.settlement_outstanding or Decimal("0.00")

    if outstanding <= 0 or invoice.allocation_status != "active":
        return JsonResponse({
            "success": False,
            "message": "This invoice has no active outstanding Trade Assist settlement."
        }, status=400)

    if not client.email:
        return JsonResponse({"success": False, "message": "Client has no email."}, status=400)

    data = [
        ("merchant_id", settings.PAYFAST_MERCHANT_ID),
        ("merchant_key", settings.PAYFAST_MERCHANT_KEY),
        ("return_url", "https://yourdomain.co.za/payfast/return/"),
        ("cancel_url", "https://yourdomain.co.za/payfast/cancel/"),
        ("notify_url", "https://yourdomain.co.za/payfast/itn/"),
        ("name_first", (client.contact_person or client.name).split()[0]),
        ("name_last", (client.contact_person or client.name).split()[-1]),
        ("email_address", client.email),
        ("m_payment_id", f"INV-{invoice.id}-TA"),
        ("amount", f"{outstanding:.2f}"),
        ("item_name", f"Trade Assist settlement - Invoice #{invoice.id}"),
    ]

    signature = generate_payfast_signature(
        data, passphrase=settings.PAYFAST_PASSPHRASE
    )
    payfast_data = dict(data)
    payfast_data["signature"] = signature
    payfast_link = (
        f"{settings.PAYFAST_PROCESS_URL}?"
        f"{urllib.parse.urlencode(payfast_data)}"
    )

    ctx = {
        "client": client,
        "invoice": invoice,
        "outstanding": outstanding,
        "payfast_link": payfast_link,
        "support_email": getattr(
            settings, "SUPPORT_EMAIL", "support@thedailymarket.co.za"
        ),
    }
    subject = f"The Daily Market – Trade Assist settlement for Invoice #{invoice.id}"

    communication = _create_email_communication_log(
        recipient=client.email,
        recipient_name=client.contact_person or client.name,
        subject=subject,
        related_object=invoice,
        sent_by=request.user,
    )

    try:
        text_body = render_to_string("email/payfast_credit_request.txt", ctx)
        html_body = render_to_string("email/payfast_credit_request.html", ctx)

        communication.message = text_body
        communication.save(update_fields=["message", "updated_at"])

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[client.email],
            headers={"Reply-To": ctx["support_email"]},
        )
        msg.attach_alternative(html_body, "text/html")

        sent = _send_email_and_update_log(
            communication=communication,
            email_message=msg,
        )
    except Exception as exc:
        communication.status = CommunicationLog.STATUS_FAILED
        communication.failed_at = now()
        communication.error_message = str(exc)
        communication.provider_response = {
            "stage": "message_preparation",
            "exception_type": exc.__class__.__name__,
        }
        communication.save(update_fields=[
            "status",
            "failed_at",
            "error_message",
            "provider_response",
            "updated_at",
        ])
        logger.exception(
            "Could not prepare PayFast settlement email for invoice %s.",
            invoice.pk,
        )
        sent = False

    if not sent:
        return JsonResponse({
            "success": False,
            "message": (
                "The settlement email could not be sent. "
                "The failed attempt has been recorded in the Communication Log."
            ),
            "communication_log_id": communication.pk,
        }, status=502)

    return JsonResponse({
        "success": True,
        "message": f"Invoice-specific repayment request sent for invoice #{invoice.id}.",
        "communication_log_id": communication.pk,
    })




@login_required
@staff_required
@require_POST
def credit_record_repayment(request, client_id):
    """
    Invoice-specific repayment capture.

    The former account-wide repayment action is intentionally removed:
    every payment must identify the invoice whose TA-funded balance it settles.
    """
    from invoices.models import Invoice

    client = get_object_or_404(Client, pk=client_id)
    invoice_id = (request.POST.get("invoice_id") or "").strip()
    amount_raw = (request.POST.get("amount") or "").strip()
    reference = (request.POST.get("reference") or "").strip()

    if not invoice_id.isdigit():
        messages.error(request, "Select a specific invoice before recording repayment.")
        return redirect("credit-view", client_id=client.id)

    invoice = get_object_or_404(Invoice, pk=int(invoice_id), client=client)

    try:
        amount = Decimal(amount_raw)
    except Exception:
        amount = Decimal("0.00")

    if amount <= 0:
        messages.error(request, "Enter a repayment amount greater than zero.")
        return redirect("credit-view", client_id=client.id)

    try:
        entry = invoice.record_credit_repayment(
            amount,
            reference=reference,
            note=f"Invoice-specific repayment captured by {request.user}.",
        )
    except Exception as exc:
        messages.error(request, f"Repayment was not recorded: {exc}")
        return redirect("credit-view", client_id=client.id)

    messages.success(
        request,
        f"R{entry.amount:.2f} allocated to invoice #{invoice.id}. "
        f"Remaining invoice settlement: R{invoice.settlement_outstanding:.2f}."
    )
    return redirect("credit-view", client_id=client.id)




@login_required
@staff_required
def funders_list(request):
    """Single-funder funding overview; historical funders remain visible."""
    funder_fields = {field.name for field in Funder._meta.get_fields()}
    funders = list(Funder.objects.annotate(
        total_allocated=Coalesce(
            Sum("allocations__amount"),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    ).order_by("name"))

    active_funder = None
    if "is_active_for_new_business" in funder_fields:
        active_funder = next(
            (f for f in funders if f.is_active_for_new_business), None
        )
    elif len(funders) == 1:
        active_funder = funders[0]

    for funder in funders:
        funder.reserved_capital = funder.total_allocated or Decimal("0.00")
        funder.unallocated_capital = max(
            Decimal("0.00"),
            (funder.balance or Decimal("0.00")) - funder.reserved_capital,
        )
        funder.is_legacy_record = funder.pk != getattr(active_funder, "pk", None)

    return render(request, "credit/funders_list.html", {
        "funders": funders,
        "active_funder": active_funder,
        "legacy_funders": [f for f in funders if f.is_legacy_record],
        "total_funder_capital": sum(
            (f.balance or Decimal("0.00") for f in funders), Decimal("0.00")
        ),
        "total_reserved_capital": sum(
            (f.reserved_capital for f in funders), Decimal("0.00")
        ),
    })


@login_required
@staff_required
def funder_view(request, funder_id):
    """
    Trade Assist funding control centre.

    FunderAllocation is the capital reservation.
    CreditAccount.credit_used is current customer exposure.
    These values are deliberately reported separately.
    """
    funder = get_object_or_404(Funder, pk=funder_id)

    funder_fields = {field.name for field in Funder._meta.get_fields()}
    if "is_active_for_new_business" in funder_fields:
        is_active_funder = bool(funder.is_active_for_new_business)
    else:
        is_active_funder = Funder.objects.count() == 1

    allocations = list(
        FunderAllocation.objects
        .filter(funder=funder)
        .select_related("client", "client__credit_account")
        .order_by("client__name")
    )

    total_reserved = Decimal("0.00")
    total_exposure = Decimal("0.00")

    for allocation in allocations:
        total_reserved += allocation.amount or Decimal("0.00")

        try:
            account = allocation.client.credit_account
        except CreditAccount.DoesNotExist:
            account = None

        allocation.facility_limit = (
            account.credit_limit if account else None
        )
        allocation.current_exposure = (
            account.credit_used if account else Decimal("0.00")
        )
        allocation.account_status = account.status if account else ""
        allocation.unused_reservation = max(
            Decimal("0.00"),
            (allocation.amount or Decimal("0.00")) - allocation.current_exposure,
        )
        total_exposure += allocation.current_exposure

    funder_balance = funder.balance or Decimal("0.00")
    unallocated_capital = max(
        Decimal("0.00"), funder_balance - total_reserved
    )
    unused_reserved_capacity = max(
        Decimal("0.00"), total_reserved - total_exposure
    )
    exposure_above_reservations = max(
        Decimal("0.00"), total_exposure - total_reserved
    )

    movements = (
        FunderMovement.objects
        .filter(funder=funder)
        .order_by("-created_at", "-id")[:100]
    )

    members = (
        FunderMember.objects
        .filter(funder=funder)
        .select_related("user")
        .order_by("role", "user__username")
    )

    # Weekly return summaries belong to the legacy model. They remain visible
    # for historical funders only and are not presented as current TA charges.
    show_legacy_performance = not is_active_funder
    week_summaries = (
        FunderWeekSummary.objects.filter(funder=funder).order_by("-week_start")
        if show_legacy_performance else FunderWeekSummary.objects.none()
    )

    delta_days = max(0, (now().date() - funder.created_at.date()).days)
    weeks, days = divmod(delta_days, 7)
    duration_display = f"{weeks} week{'s' if weeks != 1 else ''}"
    if days:
        duration_display += f", {days} day{'s' if days != 1 else ''}"

    context = {
        "funder": funder,
        "is_active_funder": is_active_funder,
        "show_legacy_performance": show_legacy_performance,
        "allocations": allocations,
        "movements": movements,
        "members": members,
        "week_summaries": week_summaries,
        "total_reserved": total_reserved,
        "total_exposure": total_exposure,
        "unallocated_capital": unallocated_capital,
        "unused_reserved_capacity": unused_reserved_capacity,
        "exposure_above_reservations": exposure_above_reservations,
        "duration_display": duration_display,
    }
    return render(request, "credit/funder_view.html", context)


@login_required
@staff_required
def add_funder(request):
    """One-time controlled setup for the single active Trade Assist funder."""
    funder_fields = {field.name for field in Funder._meta.get_fields()}

    if "is_active_for_new_business" in funder_fields:
        active_exists = Funder.objects.filter(
            is_active_for_new_business=True
        ).exists()
    else:
        active_exists = Funder.objects.exists()

    if active_exists:
        messages.info(
            request,
            "The active Trade Assist funder already exists. "
            "A second funder cannot be created for new programme activity."
        )
        return redirect("funder-list")

    if request.method == "POST":
        form = FunderForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Recheck inside the transaction to reduce the chance of
                # concurrent requests creating multiple active funders.
                if Funder.objects.select_for_update().exists():
                    messages.error(
                        request,
                        "A funder record already exists. No additional funder was created."
                    )
                    return redirect("funder-list")

                funder = form.save(commit=False)
                if "is_active_for_new_business" in funder_fields:
                    funder.is_active_for_new_business = True
                funder.save()

            messages.success(request, "Trade Assist funder created.")
            return redirect("funder-list")
    else:
        form = FunderForm()

    return render(request, "credit/add_funder.html", {"form": form})


@login_required
@staff_required
def funder_edit(request, funder_id):
    """
    Edit the active Trade Assist funder's name, access members and
    customer capital reservations.

    The active Trade Assist programme does not charge interest or fees.
    Legacy weekly-rate/profit settings are retained for historical records
    and are not editable through this screen.
    """
    funder = get_object_or_404(Funder, pk=funder_id)

    funder_fields = {field.name for field in Funder._meta.get_fields()}
    if "is_active_for_new_business" in funder_fields:
        is_active_funder = bool(funder.is_active_for_new_business)
    else:
        is_active_funder = Funder.objects.count() == 1

    if not is_active_funder:
        messages.warning(
            request,
            "Historical funder records are read-only. Their original "
            "financial settings and allocations have been preserved."
        )
        return redirect("funder-view", funder_id=funder.pk)

    if request.method == "POST":
        form = FunderForm(request.POST, instance=funder)
        member_formset = FunderMemberFormSet(request.POST, instance=funder)
        allocation_formset = FunderAllocationFormSet(
            request.POST, instance=funder
        )

        form_valid = form.is_valid()
        member_valid = member_formset.is_valid()
        allocation_valid = allocation_formset.is_valid()

        if form_valid and member_valid and allocation_valid:
            try:
                with transaction.atomic():
                    locked_funder = Funder.objects.select_for_update().get(
                        pk=funder.pk
                    )

                    # Do not allow the active Trade Assist programme to
                    # introduce weekly interest/profit settings. Preserve
                    # any legacy values already stored on the record.
                    for legacy_field in (
                        "weekly_rate_pct",
                        "profit_mode",
                        "profit_frequency",
                    ):
                        if legacy_field in form.cleaned_data:
                            form.cleaned_data[legacy_field] = getattr(
                                locked_funder, legacy_field
                            )

                    # Build the complete proposed reservation book, including
                    # additions, edits and deletions, before saving anything.
                    existing = {
                        row.pk: {
                            "client_id": row.client_id,
                            "amount": row.amount or Decimal("0.00"),
                        }
                        for row in FunderAllocation.objects.select_for_update().filter(
                            funder=locked_funder
                        )
                    }
                    proposed = dict(existing)

                    for index, allocation_form in enumerate(
                        allocation_formset.forms
                    ):
                        cleaned = getattr(
                            allocation_form, "cleaned_data", None
                        )
                        if not cleaned:
                            continue

                        instance = allocation_form.instance
                        if cleaned.get("DELETE"):
                            if instance.pk:
                                proposed.pop(instance.pk, None)
                            continue

                        client = cleaned.get("client")
                        amount = cleaned.get("amount")
                        if client is None or amount is None:
                            continue

                        key = instance.pk if instance.pk else f"new-{index}"
                        proposed[key] = {
                            "client_id": client.pk,
                            "amount": amount,
                        }

                    proposed_total = sum(
                        (item["amount"] for item in proposed.values()),
                        Decimal("0.00"),
                    )
                    capital_balance = (
                        locked_funder.balance or Decimal("0.00")
                    )

                    if proposed_total > capital_balance:
                        raise ValueError(
                            "Total customer reservations cannot exceed "
                            "the funder's available capital balance."
                        )

                    # A reservation must never be reduced below the customer's
                    # current outstanding Trade Assist exposure.
                    for item in proposed.values():
                        account = CreditAccount.objects.select_for_update().filter(
                            client_id=item["client_id"]
                        ).first()
                        current_exposure = (
                            account.credit_used
                            if account and account.credit_used
                            else Decimal("0.00")
                        )
                        if item["amount"] < current_exposure:
                            raise ValueError(
                                "A customer reservation cannot be reduced "
                                "below that customer's current outstanding "
                                "Trade Assist exposure."
                            )

                    # Save the funder form, member access and reservations
                    # together so a failure rolls back the entire update.
                    form.save()
                    member_formset.save()
                    allocation_formset.save()

                    # IMPORTANT:
                    # ModelFormSet.save() does not call model.save() for an
                    # unchanged existing row. Therefore, explicitly reconcile
                    # EVERY surviving reservation with its customer's
                    # CreditAccount limit on every funder save.
                    saved_allocations = (
                        FunderAllocation.objects.select_for_update()
                        .select_related("funder", "client")
                        .filter(funder=locked_funder)
                        .order_by("pk")
                    )

                    for allocation in saved_allocations:
                        account, _ = CreditAccount.objects.select_for_update().get_or_create(
                            client_id=allocation.client_id,
                            defaults={
                                "funder": locked_funder,
                                "status": CreditAccount.STATUS_PENDING,
                            },
                        )

                        # Keep the account linked to the funder that owns
                        # this reservation before recording a limit change.
                        if account.funder_id != locked_funder.pk:
                            account.funder = locked_funder
                            account.save(update_fields=["funder", "updated_at"])

                        allocation_limit = allocation.amount or Decimal("0.00")
                        current_limit = account.credit_limit or Decimal("0.00")

                        if current_limit != allocation_limit:
                            account.set_limit(
                                new_limit=allocation_limit,
                                authorised_by=request.user,
                                note=(
                                    f"Buying-power limit synchronised from "
                                    f"FunderAllocation #{allocation.pk} "
                                    f"during funder update."
                                ),
                            )

                messages.success(
                    request,
                    "Trade Assist funder details, access members and "
                    "customer reservations have been updated."
                )
                return redirect("funder-view", funder_id=funder.pk)

            except Exception as exc:
                logger.exception(
                    "Funder update failed for funder %s", funder.pk
                )
                messages.error(request, str(exc))
        else:
            messages.error(
                request,
                "Please correct the errors below. No changes were saved."
            )
    else:
        form = FunderForm(instance=funder)
        member_formset = FunderMemberFormSet(instance=funder)
        allocation_formset = FunderAllocationFormSet(instance=funder)

    allocated_total = funder.total_allocated()
    available_for_allocation = max(
        Decimal("0.00"),
        (funder.balance or Decimal("0.00")) - allocated_total,
    )

    return render(
        request,
        "credit/funder_edit.html",
        {
            "form": form,
            "member_formset": member_formset,
            "allocation_formset": allocation_formset,
            "funder": funder,
            "allocated_total": allocated_total,
            "available_for_allocation": available_for_allocation,
            "is_active_funder": is_active_funder,
        },
    )


@login_required
@staff_required
@require_POST
def funder_add_movement(request, funder_id):
    """Record a capital movement; payouts may only use unallocated capital."""
    funder = get_object_or_404(Funder, pk=funder_id)

    funder_fields = {field.name for field in Funder._meta.get_fields()}
    if "is_active_for_new_business" in funder_fields:
        is_active_funder = bool(funder.is_active_for_new_business)
    else:
        is_active_funder = Funder.objects.count() == 1

    if not is_active_funder:
        messages.error(
            request,
            "Capital movements cannot be added to a historical funder record."
        )
        return redirect("funder-view", funder_id=funder.pk)

    form = FunderMovementForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please check the capital movement details.")
        return redirect("funder-view", funder_id=funder.pk)

    try:
        with transaction.atomic():
            locked_funder = Funder.objects.select_for_update().get(pk=funder.pk)
            kind = form.cleaned_data["kind"]
            amount = form.cleaned_data["amount"]

            if amount <= 0:
                raise ValueError("Movement amount must be greater than zero.")

            reserved = locked_funder.total_allocated()
            unallocated = (locked_funder.balance or Decimal("0.00")) - reserved

            if kind == FunderMovement.PAYOUT and amount > unallocated:
                raise ValueError(
                    "A payout cannot reduce funder capital below the amount reserved for customer facilities."
                )

            movement = form.save(commit=False)
            movement.funder = locked_funder
            movement.save()

        messages.success(request, "Funder capital movement recorded.")
    except Exception as exc:
        logger.exception("Funder movement failed for funder %s", funder.pk)
        messages.error(request, str(exc))

    return redirect("funder-view", funder_id=funder.pk)
