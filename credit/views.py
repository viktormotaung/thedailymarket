# credit/views.py
import hashlib
import logging
import urllib.parse
from datetime import date, datetime, time, timedelta
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
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.timezone import now, localdate, get_current_timezone, make_aware
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
    CreditSettlement,
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


# ============================================================
# TRADE ASSIST ACCOUNT STATEMENTS
# ============================================================

def _statement_period(period, start_raw="", end_raw=""):
    """Resolve statement dates using the twice-weekly Thu/Sun cycle."""
    today = localdate()
    period = (period or "current").strip().lower()

    if period == "current":
        # Monday–Thursday is the Thursday cycle; Friday–Sunday is the Sunday cycle.
        cycle_start = today - timedelta(days=today.weekday())
        if today.weekday() >= 4:  # Friday, Saturday or Sunday
            cycle_start = today - timedelta(days=today.weekday() - 4)
        return cycle_start, today, "Current period"

    if period == "7":
        return today - timedelta(days=6), today, "Last 7 days"

    if period == "30":
        return today - timedelta(days=29), today, "Last 30 days"

    if period == "custom":
        try:
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
        except (TypeError, ValueError):
            raise ValueError("Select a valid start date and end date.")
        if end < start:
            raise ValueError("The end date cannot be earlier than the start date.")
        if end > today:
            raise ValueError("The statement end date cannot be in the future.")
        return start, end, "Custom date range"

    raise ValueError("Select a valid statement period.")


def _statement_context(client, account, start_date, end_date, period_label):
    """
    Build the statement from the account's actual credit ledger.

    Datetime boundaries are explicitly constructed in the active Django
    timezone (Africa/Johannesburg in this project) so the complete selected
    dates are included, regardless of the database timezone.
    """
    zero = Decimal("0.00")
    current_tz = get_current_timezone()

    period_start = make_aware(
        datetime.combine(start_date, time.min),
        current_tz,
    )
    period_end_exclusive = make_aware(
        datetime.combine(end_date + timedelta(days=1), time.min),
        current_tz,
    )

    # The CreditEntry ledger is the source of truth for all account activity.
    entries = list(
        CreditEntry.objects.filter(
            credit_account=account,
            posted_at__gte=period_start,
            posted_at__lt=period_end_exclusive,
        )
        .select_related("invoice", "transaction", "created_by")
        .order_by("posted_at", "id")
    )

    # One settlement is created for every usage entry. Filter through its
    # usage entry so the statement includes the utilisations made in-period.
    settlements = list(
        CreditSettlement.objects.filter(
            credit_account=account,
            usage_entry__posted_at__gte=period_start,
            usage_entry__posted_at__lt=period_end_exclusive,
        )
        .select_related("invoice", "usage_entry")
        .order_by("due_date", "usage_entry__posted_at", "id")
    )

    usage_total = sum(
        (entry.amount for entry in entries if entry.kind == CreditEntry.USAGE),
        zero,
    )
    repayment_total = sum(
        (
            entry.amount
            for entry in entries
            if entry.kind == CreditEntry.REPAYMENT
        ),
        zero,
    )
    adjustment_total = sum(
        (
            entry.amount
            for entry in entries
            if entry.kind == CreditEntry.ADJUSTMENT
        ),
        zero,
    )

    # CreditEntry.balance is the available buying power AFTER that entry.
    # Opening = last balance before the period; closing = last balance
    # posted during the period (or opening balance if there was no activity).
    previous_entry = (
        CreditEntry.objects.filter(
            credit_account=account,
            posted_at__lt=period_start,
        )
        .order_by("-posted_at", "-id")
        .first()
    )
    last_period_entry = (
        CreditEntry.objects.filter(
            credit_account=account,
            posted_at__gte=period_start,
            posted_at__lt=period_end_exclusive,
        )
        .order_by("-posted_at", "-id")
        .first()
    )

    opening_available = (
        previous_entry.balance if previous_entry else zero
    )
    closing_available = (
        last_period_entry.balance if last_period_entry else opening_available
    )

    # Settlement balances are live balances, while the utilisation date is
    # the historical date on which buying power was used.
    today = localdate()
    overdue_count = 0
    upcoming_count = 0
    partially_settled_count = 0
    settled_count = 0
    cancelled_count = 0

    for settlement in settlements:
        outstanding = r2(
            getattr(settlement, "outstanding_amount", zero) or zero
        )
        repaid = r2(getattr(settlement, "repaid_amount", zero) or zero)
        stored_status = (getattr(settlement, "status", "") or "").upper()

        if stored_status == "CANCELLED":
            display_status = "Cancelled"
            cancelled_count += 1
        elif outstanding <= zero:
            display_status = "Settled"
            settled_count += 1
        elif settlement.grace_date and settlement.grace_date < today:
            display_status = "Overdue"
            overdue_count += 1
        elif repaid > zero:
            display_status = "Partially settled"
            partially_settled_count += 1
        else:
            display_status = "Outstanding"

        if (
            outstanding > zero
            and display_status not in ("Overdue", "Cancelled")
            and settlement.due_date
            and settlement.due_date >= today
        ):
            upcoming_count += 1

        settlement.display_status = display_status

    outstanding_total = sum(
        (
            r2(getattr(settlement, "outstanding_amount", zero) or zero)
            for settlement in settlements
            if (getattr(settlement, "status", "") or "").upper() != "CANCELLED"
        ),
        zero,
    )

    credit_limit = r2(account.credit_limit or zero)
    current_used = r2(account.credit_used or zero)
    current_available = r2(account.credit_available or zero)
    utilisation_pct = (
        (current_used / credit_limit) * Decimal("100")
        if credit_limit > zero else zero
    )
    utilisation_pct = min(Decimal("100.00"), max(zero, utilisation_pct)).quantize(
        Decimal("0.01")
    )

    # Account-wide outstanding schedule: unlike the statement activity table,
    # this includes every still-open utilisation, even if it was created
    # before the selected statement period.
    account_settlements = list(
        CreditSettlement.objects.filter(credit_account=account)
        .select_related("invoice", "usage_entry")
        .order_by("due_date", "usage_entry__posted_at", "id")
    )

    account_open_settlements = []
    due_schedule_map = {}
    account_total_outstanding = zero
    account_overdue_total = zero
    account_upcoming_total = zero
    account_no_due_date_total = zero

    for settlement in account_settlements:
        settlement_outstanding = r2(
            getattr(settlement, "outstanding_amount", zero) or zero
        )
        settlement_repaid = r2(
            getattr(settlement, "repaid_amount", zero) or zero
        )
        settlement_status = (
            getattr(settlement, "status", "") or ""
        ).upper()

        if settlement_status == "CANCELLED" or settlement_outstanding <= zero:
            continue

        if settlement.grace_date and settlement.grace_date < today:
            settlement_account_status = "Overdue"
            account_overdue_total += settlement_outstanding
        elif settlement.due_date and settlement.due_date >= today:
            settlement_account_status = (
                "Partially settled" if settlement_repaid > zero else "Upcoming"
            )
            account_upcoming_total += settlement_outstanding
        elif settlement.due_date is None:
            settlement_account_status = "Due date not set"
            account_no_due_date_total += settlement_outstanding
        else:
            # Due date has passed, but grace date has not.
            settlement_account_status = (
                "Partially settled" if settlement_repaid > zero else "Due"
            )
            account_upcoming_total += settlement_outstanding

        settlement.account_display_status = settlement_account_status
        account_open_settlements.append(settlement)
        account_total_outstanding += settlement_outstanding

        due_key = settlement.due_date
        if due_key not in due_schedule_map:
            due_schedule_map[due_key] = {
                "due_date": due_key,
                "grace_dates": set(),
                "invoice_refs": [],
                "outstanding": zero,
                "status_labels": set(),
            }

        schedule_row = due_schedule_map[due_key]
        schedule_row["outstanding"] += settlement_outstanding
        schedule_row["status_labels"].add(settlement_account_status)
        if settlement.grace_date:
            schedule_row["grace_dates"].add(settlement.grace_date)
        invoice_ref = (
            f"Invoice #{settlement.invoice_id}"
            if settlement.invoice_id else f"Utilisation #{settlement.pk}"
        )
        schedule_row["invoice_refs"].append(invoice_ref)

    due_schedule = []
    for due_key, row in due_schedule_map.items():
        row["outstanding"] = r2(row["outstanding"])
        row["grace_dates"] = sorted(row["grace_dates"])
        row["invoice_refs"] = ", ".join(row["invoice_refs"])
        row["status_labels"] = ", ".join(sorted(row["status_labels"]))
        due_schedule.append(row)

    due_schedule.sort(
        key=lambda row: (
            row["due_date"] is None,
            row["due_date"] or date.max,
        )
    )

    account_total_outstanding = r2(account_total_outstanding)
    account_overdue_total = r2(account_overdue_total)
    account_upcoming_total = r2(account_upcoming_total)
    account_no_due_date_total = r2(account_no_due_date_total)

    customer_email = (getattr(client, "email", "") or "").strip()
    if not customer_email:
        profile = (
            client.customer_profiles
            .select_related("user")
            .filter(user__email__gt="")
            .first()
        )
        if profile and profile.user:
            customer_email = (profile.user.email or "").strip()

    return {
        "client": client,
        "account": account,
        "start_date": start_date,
        "end_date": end_date,
        "period_label": period_label,
        "generated_at": now(),
        "entries": entries,
        "settlements": settlements,
        "usage_total": usage_total,
        "repayment_total": repayment_total,
        "adjustment_total": adjustment_total,
        "opening_available": opening_available,
        "closing_available": closing_available,
        "settlement_outstanding_total": outstanding_total,
        "credit_limit": credit_limit,
        "current_used": current_used,
        "current_available": current_available,
        "utilisation_pct": utilisation_pct,
        "overdue_count": overdue_count,
        "upcoming_count": upcoming_count,
        "partially_settled_count": partially_settled_count,
        "settled_count": settled_count,
        "cancelled_count": cancelled_count,
        "account_open_settlements": account_open_settlements,
        "due_schedule": due_schedule,
        "account_total_outstanding": account_total_outstanding,
        "account_overdue_total": account_overdue_total,
        "account_upcoming_total": account_upcoming_total,
        "account_no_due_date_total": account_no_due_date_total,
        "customer_email": customer_email,
    }


def _build_statement_pdf(context):
    """Create a printable PDF statement using ReportLab."""
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )
    from xml.sax.saxutils import escape

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=14*mm, leftMargin=14*mm,
        topMargin=14*mm, bottomMargin=14*mm,
        title=f"Trade Assist Statement - {context['client']}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="BrandTitle", parent=styles["Title"], textColor=colors.HexColor("#0b5c39"),
        alignment=TA_CENTER, fontSize=19, leading=22, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="SmallRight", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=8,
    ))
    story = [
        Paragraph("THE DAILY MARKET", styles["BrandTitle"]),
        Paragraph("TRADE ASSIST ACCOUNT STATEMENT", styles["Heading2"]),
        Paragraph(
            f"<b>Account holder:</b> {escape(str(context['client']))}<br/>"
            f"<b>Statement period:</b> {context['start_date']:%d %b %Y} – "
            f"{context['end_date']:%d %b %Y}<br/>"
            f"<b>Generated:</b> {context['generated_at']:%d %b %Y %H:%M}",
            styles["Normal"],
        ),
        Spacer(1, 8),
    ]

    money = lambda value: f"R{(value or Decimal('0.00')):,.2f}"
    summary = [
        ["Approved buying power", "Currently utilised", "Available buying power"],
        [money(context["credit_limit"]), money(context["current_used"]),
         money(context["current_available"])],
        ["Utilisation of approved limit", "Buying power used in period", "Repayments in period"],
        [f'{context["utilisation_pct"]}%', money(context["usage_total"]),
         money(context["repayment_total"])],
        ["Total account outstanding", "Overdue outstanding", "Upcoming / due outstanding"],
        [money(context["account_total_outstanding"]),
         money(context["account_overdue_total"]),
         money(context["account_upcoming_total"])],
    ]
    t = Table(summary, colWidths=[58*mm, 58*mm, 58*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0b5c39")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("BACKGROUND", (0,2), (-1,2), colors.HexColor("#eaf2ed")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTNAME", (0,2), (-1,2), "Helvetica-Bold"),
        ("FONTNAME", (0,1), (-1,1), "Helvetica-Bold"),
        ("FONTNAME", (0,3), (-1,3), "Helvetica-Bold"),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#d7dfda")),
        ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ]))
    story += [t, Spacer(1, 12), Paragraph("Buying-power utilisation and due dates", styles["Heading2"])]

    settlement_rows = [[
        "Invoice", "Utilisation date", "Due date", "Grace date",
        "Amount used", "Repaid", "Outstanding", "Status"
    ]]
    for item in context["settlements"]:
        settlement_rows.append([
            f"#{item.invoice_id}" if item.invoice_id else "—",
            item.usage_entry.posted_at.strftime("%d/%m/%y") if item.usage_entry and item.usage_entry.posted_at else "—",
            item.due_date.strftime("%d/%m/%y") if item.due_date else "—",
            item.grace_date.strftime("%d/%m/%y") if item.grace_date else "—",
            money(item.original_amount), money(item.repaid_amount),
            money(item.outstanding_amount), item.display_status,
        ])
    if len(settlement_rows) == 1:
        settlement_rows.append(["No buying-power utilisations in this period.", "", "", "", "", "", "", ""])
    st = Table(settlement_rows, repeatRows=1,
               colWidths=[15*mm, 20*mm, 18*mm, 18*mm, 22*mm, 20*mm, 22*mm, 25*mm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0b5c39")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("GRID", (0,0), (-1,-1), .3, colors.HexColor("#d7dfda")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (4,1), (6,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story += [
        st,
        Spacer(1, 5),
        Paragraph(
            f'<b>Settlement position in this period:</b> '
            f'{context["settled_count"]} settled · '
            f'{context["partially_settled_count"]} partially settled · '
            f'{context["overdue_count"]} overdue · '
            f'{context["upcoming_count"]} upcoming · '
            f'{context["cancelled_count"]} cancelled',
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph("Outstanding balance & settlement schedule", styles["Heading2"]),
        Paragraph(
            "This schedule covers all currently unsettled utilisations on the account, "
            "including utilisations from outside the selected statement period. "
            "Amounts are grouped by their contractual due date.",
            styles["Normal"],
        ),
        Spacer(1, 5),
    ]

    due_rows = [[
        "Due date", "Grace date(s)", "Invoice reference(s)",
        "Outstanding amount", "Position"
    ]]
    for row in context["due_schedule"]:
        due_rows.append([
            row["due_date"].strftime("%d/%m/%Y") if row["due_date"] else "Date not set",
            ", ".join(d.strftime("%d/%m/%Y") for d in row["grace_dates"]) or "—",
            row["invoice_refs"] or "—",
            money(row["outstanding"]),
            row["status_labels"] or "Outstanding",
        ])

    if len(due_rows) == 1:
        due_rows.append(["No outstanding settlements", "—", "—", money(Decimal("0.00")), "Up to date"])

    due_rows.append([
        "TOTAL OUTSTANDING", "", "",
        money(context["account_total_outstanding"]),
        "",
    ])

    due_table = Table(
        due_rows,
        repeatRows=1,
        colWidths=[25*mm, 25*mm, 55*mm, 35*mm, 25*mm],
    )
    due_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0b5c39")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("GRID", (0,0), (-1,-1), .3, colors.HexColor("#d7dfda")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (3,1), (3,-1), "RIGHT"),
        ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#eaf2ed")),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story += [
        due_table,
        Spacer(1, 5),
        Paragraph(
            f'<b>Outstanding without a due date:</b> '
            f'{money(context["account_no_due_date_total"])}'
            f'&nbsp;&nbsp;&nbsp; <b>Overdue:</b> '
            f'{money(context["account_overdue_total"])}'
            f'&nbsp;&nbsp;&nbsp; <b>Upcoming / due:</b> '
            f'{money(context["account_upcoming_total"])}',
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph("Account activity", styles["Heading2"]),
    ]

    activity_rows = [["Date", "Entry", "Reference / invoice", "Debit", "Credit", "Available balance"]]
    for entry in context["entries"]:
        debit = money(entry.amount) if entry.kind in (CreditEntry.USAGE, CreditEntry.LIMIT_DECREASE) else "—"
        credit = money(entry.amount) if entry.kind in (CreditEntry.REPAYMENT, CreditEntry.ISSUE, CreditEntry.WRITEOFF) else "—"
        if entry.kind == CreditEntry.ADJUSTMENT:
            debit = money(abs(entry.amount)) if entry.amount < 0 else "—"
            credit = money(entry.amount) if entry.amount > 0 else "—"
        reference = f"Invoice #{entry.invoice_id}" if entry.invoice_id else (entry.reference or "—")
        activity_rows.append([
            entry.posted_at.strftime("%d/%m/%y %H:%M"),
            entry.get_kind_display(), reference, debit, credit, money(entry.balance)
        ])
    if len(activity_rows) == 1:
        activity_rows.append(["No account activity in this period.", "", "", "", "", ""])
    at = Table(activity_rows, repeatRows=1,
               colWidths=[27*mm, 30*mm, 42*mm, 25*mm, 25*mm, 31*mm])
    at.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0b5c39")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7.5),
        ("GRID", (0,0), (-1,-1), .3, colors.HexColor("#d7dfda")),
        ("ALIGN", (3,1), (-1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story += [
        at, Spacer(1, 10),
        Paragraph(
            f"<b>Opening available buying power:</b> {money(context['opening_available'])}"
            f"&nbsp;&nbsp;&nbsp; <b>Closing available buying power:</b> {money(context['closing_available'])}",
            styles["Normal"],
        ),
        Spacer(1, 8),
        Paragraph(
            "This statement records Trade Assist buying-power utilisation and settlements. "
            "It is not a tax invoice. No interest or finance charge is applied by this statement.",
            styles["Italic"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()


@login_required
@staff_required
def credit_statement_view(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)
    try:
        start_date, end_date, label = _statement_period(
            request.GET.get("period", "current"),
            request.GET.get("start_date", ""),
            request.GET.get("end_date", ""),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("credit-view", client_id=client.id)

    context = _statement_context(client, account, start_date, end_date, label)
    return render(request, "credit/credit_statement.html", context)


@login_required
@staff_required
def credit_statement_download(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)
    try:
        start_date, end_date, label = _statement_period(
            request.GET.get("period", "current"),
            request.GET.get("start_date", ""),
            request.GET.get("end_date", ""),
        )
    except ValueError as exc:
        return HttpResponse(str(exc), status=400, content_type="text/plain")

    context = _statement_context(client, account, start_date, end_date, label)
    pdf = _build_statement_pdf(context)
    filename = f"TradeAssist_Statement_{client.pk}_{start_date}_{end_date}.pdf"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@staff_required
@require_POST
def credit_statement_email(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    account, _ = CreditAccount.objects.get_or_create(client=client)
    try:
        start_date, end_date, label = _statement_period(
            request.POST.get("period", "current"),
            request.POST.get("start_date", ""),
            request.POST.get("end_date", ""),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("credit-view", client_id=client.id)

    context = _statement_context(client, account, start_date, end_date, label)
    recipient = (request.POST.get("recipient_email") or context["customer_email"]).strip()
    if not recipient:
        messages.error(request, "No customer email address is available. Enter a recipient email address.")
        return redirect(
            f"{reverse('credit-statement', args=[client.id])}"
            f"?period={request.POST.get('period', 'current')}"
            f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
        )

    subject = (
        f"Trade Assist account statement – {client.name} "
        f"({start_date:%d %b %Y} to {end_date:%d %b %Y})"
    )
    text_body = (
        f"Dear {client.name},\n\n"
        f"Please find attached your Trade Assist account statement for "
        f"{start_date:%d %b %Y} to {end_date:%d %b %Y}.\n\n"
        "The statement includes buying-power utilisation, settlement due dates, "
        "repayments and account activity.\n\n"
        "Regards,\nThe Daily Market"
    )
    communication = _create_email_communication_log(
        recipient=recipient,
        recipient_name=client.name,
        subject=subject,
        message=text_body,
        related_object=client,
        sent_by=request.user,
    )
    try:
        pdf = _build_statement_pdf(context)
        email_message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        email_message.attach(
            f"TradeAssist_Statement_{client.pk}_{start_date}_{end_date}.pdf",
            pdf,
            "application/pdf",
        )
        sent = _send_email_and_update_log(
            communication=communication,
            email_message=email_message,
        )
        if sent:
            messages.success(request, f"Statement email accepted by the email service for {recipient}.")
        else:
            messages.error(request, "The statement email could not be sent. Check the communication log.")
    except Exception as exc:
        communication.status = CommunicationLog.STATUS_FAILED
        communication.failed_at = now()
        communication.error_message = str(exc)
        communication.save(update_fields=["status", "failed_at", "error_message", "updated_at"])
        logger.exception("Could not email Trade Assist statement for client %s.", client.pk)
        messages.error(request, "The statement could not be prepared or emailed. Check the server log.")

    return redirect(
        f"{reverse('credit-statement', args=[client.id])}?period={request.POST.get('period', 'current')}"
        f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
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
