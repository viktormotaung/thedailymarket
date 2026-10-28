"""
Public campaign landing-page views for The Daily Market.

Keep this module separate from the large existing home/views.py file.
The public form creates a Lead and campaign-response records only; it does
not create a Prospect or Client. After a successful database commit, the view
submits a confirmation SMS to SMSPortal and records the provider result.
"""

import hashlib
import logging

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from clients.forms import (
    CampaignLeadSubmissionForm,
    build_campaign_question_form,
)
from communications.services.smsportal import send_sms

from clients.models import (
    Campaign,
    CampaignResponse,
    CampaignResponseAnswer,
    CampaignSMSConfirmation,
)

logger = logging.getLogger(__name__)

def _contact_consent_text(campaign):
    """Return consent wording that identifies the relevant campaign brand."""
    brand = "Trade Assist" if campaign.campaign_type == "TRADE_ASSIST" else "The Daily Market"
    return f"I agree that {brand} may contact me by phone and SMS about this enquiry."

# Only values supported by Lead.SOURCE_CHOICES and Campaign.CHANNEL_CHOICES.
CHANNEL_MAP = {
    "facebook": ("FACEBOOK", "FACEBOOK"),
    "instagram": ("INSTAGRAM", "INSTAGRAM"),
    "tiktok": ("TIKTOK", "TIKTOK"),
    "website": ("WEBSITE", "WEBSITE"),
    "print": ("WEBSITE", "PRINT"),
    "other": ("OTHER", "OTHER"),
}


def _first_value(request, key, default=""):
    """Read an attribution value from POST first, then GET."""
    value = request.POST.get(key)
    if value in (None, ""):
        value = request.GET.get(key, default)
    return (value or "").strip()


def _campaign_attribution(request):
    """Collect attribution parameters safely for the hidden form fields."""
    keys = (
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "ttclid",
        "ad_name",
    )
    return {key: _first_value(request, key) for key in keys}


def _campaign_channel(request, campaign):
    """
    Resolve channel from UTM/ad parameters first, then from the campaign's
    configured channels. Default to WEBSITE when the source is not known.
    """
    raw_source = (
        _first_value(request, "utm_source")
        or _first_value(request, "source")
        or _first_value(request, "channel")
    ).lower()

    if raw_source in CHANNEL_MAP:
        lead_source, response_channel = CHANNEL_MAP[raw_source]
        return lead_source, response_channel

    configured = campaign.channels or []
    for value in configured:
        normalised = str(value).strip().lower()
        if normalised in CHANNEL_MAP:
            lead_source, response_channel = CHANNEL_MAP[normalised]
            return lead_source, response_channel

    return "WEBSITE", "WEBSITE"


def _campaign_is_open(campaign):
    today = timezone.localdate()
    if campaign.status != "ACTIVE":
        return False
    if campaign.start_date and campaign.start_date > today:
        return False
    if campaign.end_date and campaign.end_date < today:
        return False
    return True


def _send_campaign_confirmation_sms(sms_record):
    """Send the campaign confirmation through the shared SMSPortal service."""
    sms_record.status = "SENDING"
    sms_record.attempt_count += 1
    sms_record.last_attempt_at = timezone.now()
    sms_record.provider = "SMSPortal"
    sms_record.last_error = ""
    sms_record.save(update_fields=[
        "status", "attempt_count", "last_attempt_at", "provider", "last_error", "updated_at"
    ])

    try:
        # Use the same central SMS service as invoice SMS messages. This keeps
        # credentials, provider configuration, and connection handling in one place.
        result = send_sms(
            to=sms_record.phone_number,
            message=sms_record.message,
        )
        if not isinstance(result, dict) or not result.get("success"):
            detail = "SMSPortal did not confirm successful delivery submission."
            if isinstance(result, dict):
                detail = (
                    result.get("error")
                    or result.get("message")
                    or str(result.get("response") or detail)
                )
            raise RuntimeError(str(detail)[:4000])

    except Exception as exc:  # SMS errors must not prevent the lead being saved.
        logger.exception(
            "Campaign confirmation SMS failed for response %s",
            sms_record.response_id,
        )
        sms_record.status = "FAILED"
        sms_record.last_error = str(exc)[:4000]
        sms_record.save(update_fields=["status", "last_error", "updated_at"])
        return False

    provider_message_id = ""
    if isinstance(result, dict):
        provider_message_id = (
            result.get("message_id")
            or result.get("id")
            or result.get("provider_message_id")
            or ""
        )
        messages = result.get("messages") or []
        if not provider_message_id and isinstance(messages, list) and messages:
            first = messages[0] if isinstance(messages[0], dict) else {}
            provider_message_id = first.get("id") or first.get("message_id") or ""

    sms_record.status = "SENT"
    sms_record.sent_at = timezone.now()
    sms_record.provider_message_id = str(provider_message_id)[:200]
    sms_record.last_error = ""
    sms_record.save(update_fields=[
        "status", "sent_at", "provider_message_id", "last_error", "updated_at"
    ])
    return True


@require_http_methods(["GET", "POST"])
def food_supply_campaign_form(request, campaign_code):
    """
    Public, mobile-friendly campaign form.

    URL example:
        /campaign/your-food-supply-campaign-code/

    campaign_code is Campaign.code, generated from the campaign name.
    Only ACTIVE campaigns within their configured dates accept submissions.
    """
    campaign = get_object_or_404(Campaign, code=campaign_code)

    if not _campaign_is_open(campaign):
        raise Http404("This campaign is not currently accepting enquiries.")

    if campaign.campaign_type not in {"FOOD_SUPPLY", "TRADE_ASSIST", "COMBINED"}:
        raise Http404("This campaign type is not supported.")

    if request.method == "POST":
        form = CampaignLeadSubmissionForm(request.POST)
        question_form = build_campaign_question_form(campaign, request.POST)

        if form.is_valid() and question_form.is_valid():
            with transaction.atomic():
                lead = form.save(commit=False)

                lead.source, response_channel = _campaign_channel(request, campaign)
                lead.temperature = "WARM"
                lead.status = "NEW"
                lead.campaign = campaign.name[:150]
                lead.advert = (
                    _first_value(request, "ad_name")
                    or _first_value(request, "utm_content")
                    or _first_value(request, "advert_reference")
                )[:150]
                lead.medium = (
                    _first_value(request, "utm_medium")
                    or "Paid social"
                )[:100]
                lead.country = "South Africa"

                # This is a sales enquiry, not a registration as a customer.
                # Do not create a Prospect or Client here.
                product_notes = (request.POST.get("business_notes") or "").strip()
                if product_notes:
                    existing_notes = (getattr(lead, "notes", "") or "").strip()
                    lead.notes = "\n".join(
                        part for part in [existing_notes, f"Products of interest: {product_notes}"]
                        if part
                    )

                if not lead.whatsapp:
                    lead.whatsapp = lead.phone

                lead.save()

                metadata = {
                    "utm_content": _first_value(request, "utm_content"),
                    "utm_term": _first_value(request, "utm_term"),
                    "fbclid": _first_value(request, "fbclid"),
                    "ttclid": _first_value(request, "ttclid"),
                    "referrer": (request.META.get("HTTP_REFERER") or "")[:500],
                    "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:500],
                    "campaign_type": campaign.campaign_type,
                }

                response = CampaignResponse.objects.create(
                    campaign=campaign,
                    lead=lead,
                    channel=response_channel,
                    advert_reference=lead.advert,
                    landing_page=request.build_absolute_uri(
                        reverse("food-supply-campaign-form", args=[campaign.code])
                    )[:500],
                    utm_source=_first_value(request, "utm_source")[:150],
                    utm_medium=_first_value(request, "utm_medium")[:150],
                    utm_campaign=_first_value(request, "utm_campaign")[:180],
                    utm_content=metadata["utm_content"][:180],
                    utm_term=metadata["utm_term"][:180],
                    fbclid=metadata["fbclid"][:250],
                    ttclid=metadata["ttclid"][:250],
                    consent_to_contact=bool(form.cleaned_data.get("contact_consent")),
                    consent_text=CONTACT_CONSENT_TEXT,
                    submitted_at=timezone.now(),
                    metadata=metadata,
                )

                for question in getattr(question_form, "campaign_questions", []):
                    answer = question_form.cleaned_data.get(f"question_{question.pk}")
                    if answer in (None, "", [], ()):
                        continue
                    CampaignResponseAnswer.objects.create(
                        response=response,
                        question=question,
                        question_text_snapshot=question.question_text,
                        answer_value=answer,
                    )

                # Create a durable queue record. This does not send an SMS by
                # itself; an SMS provider/worker must process QUEUED records.
                sms_brand = "Trade Assist" if campaign.campaign_type == "TRADE_ASSIST" else "The Daily Market"
                sms_message = (
                    f"Thank you for contacting {sms_brand}. "
                    f"We received your business enquiry ({lead.lead_number}) "
                    f"and our team will contact you. Reply STOP if you do not "
                    f"want further SMS messages."
                )
                idempotency_key = hashlib.sha256(
                    f"campaign-response:{response.pk}:sms-confirmation".encode("utf-8")
                ).hexdigest()

                sms_confirmation, _created = CampaignSMSConfirmation.objects.get_or_create(
                    response=response,
                    defaults={
                        "phone_number": lead.phone,
                        "message": sms_message,
                        "provider": "SMSPortal",
                        "status": "QUEUED",
                        "idempotency_key": idempotency_key,
                    },
                )

            # The lead and campaign response are committed before the provider
            # call. If SMSPortal is down, the enquiry remains safely recorded.
            _send_campaign_confirmation_sms(sms_confirmation)

            return redirect(
                "food-supply-campaign-thank-you",
                campaign_code=campaign.code,
            )
    else:
        form = CampaignLeadSubmissionForm()
        question_form = build_campaign_question_form(campaign)

    context = {
        "campaign": campaign,
        "form": form,
        "question_form": question_form,
        "page_title": campaign.form_title or ("Explore Trade Assist" if campaign.campaign_type == "TRADE_ASSIST" else "Quick Business Enquiry"),
        "page_description": campaign.form_description
        or "Tell us about your business. It takes around 2 minutes.",
        "brand_name": "Trade Assist" if campaign.campaign_type == "TRADE_ASSIST" else "The Daily Market",
        "brand_tagline": "Business support programme" if campaign.campaign_type == "TRADE_ASSIST" else "Business food supply",
        "is_trade_assist": campaign.campaign_type == "TRADE_ASSIST",
        "contact_consent_text": _contact_consent_text(campaign),
        "attribution": _campaign_attribution(request),
    }
    return render(request, "home/campaign_food_supply_form.html", context)


@require_http_methods(["GET"])
def food_supply_campaign_thank_you(request, campaign_code):
    campaign = get_object_or_404(Campaign, code=campaign_code)
    if campaign.campaign_type not in {"FOOD_SUPPLY", "TRADE_ASSIST", "COMBINED"}:
        raise Http404("This campaign type is not supported.")

    return render(
        request,
        "home/campaign_food_supply_thank_you.html",
        {
            "campaign": campaign,
            "page_title": "Thank you",
        },
    )
