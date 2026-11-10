"""SMS-only order status notifications through SMSPortal.

The out-for-delivery SMS contains a link to the signed-in customer's
membership delivery-note page.
"""
import logging

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from communications.models import CommunicationLog
from communications.services.smsportal import send_sms

logger = logging.getLogger(__name__)

MESSAGES = {
    "out_for_delivery": (
        "The Daily Market: Your order #{id} is out for delivery! "
        "View your delivery note and delivery details here: {delivery_url}"
    ),
    "complete": (
        "The Daily Market: Your order #{id} has been marked as complete. "
        "Thank you for choosing The Daily Market! We look forward to serving you again."
    ),
}


def _public_base_url():
    """Return the configured public website origin, without a trailing slash."""
    for setting_name in ("TDM_PUBLIC_BASE_URL", "SITE_URL", "BASE_URL"):
        value = getattr(settings, setting_name, "")
        if value:
            return str(value).strip().rstrip("/")

    # Optional Django Sites fallback.
    if "django.contrib.sites" in getattr(settings, "INSTALLED_APPS", []):
        try:
            from django.contrib.sites.models import Site
            site = Site.objects.get_current()
            if site.domain:
                scheme = getattr(settings, "SITE_SCHEME", "https")
                return f"{scheme}://{site.domain}".rstrip("/")
        except Exception:
            logger.exception("Could not resolve the current Django Site.")

    return ""


def _delivery_note_url(order_id):
    path = reverse("membership_delivery_note", kwargs={"order_id": order_id})
    base_url = _public_base_url()
    if not base_url:
        raise RuntimeError(
            "Set TDM_PUBLIC_BASE_URL (for example https://www.yourdomain.co.za) "
            "to generate the customer delivery-note link."
        )
    return f"{base_url}{path}"


def send_order_status_sms(order_id, status, using="default"):
    from orders.models import Order

    if status not in MESSAGES:
        return None

    try:
        order = (
            Order.objects.using(using)
            .select_related("client", "end_user")
            .get(pk=order_id)
        )
        client = order.client

        # For an order delivered to an End User, use the DeliveryStop contact
        # snapshot first; otherwise use the Client contact number.
        delivery_stop = (
            order.delivery_stops.using(using).order_by("id").first()
        )
        phone = ""
        recipient_name = ""
        if delivery_stop:
            phone = str(delivery_stop.phone or "").strip()
            recipient_name = str(delivery_stop.customer_name or "").strip()

        if not phone and order.end_user:
            phone = str(
                getattr(order.end_user, "phone", "")
                or getattr(order.end_user, "whatsapp", "")
                or ""
            ).strip()
            recipient_name = recipient_name or str(
                getattr(order.end_user, "full_name", "") or ""
            )

        phone = phone or str(getattr(client, "phone", "") or "").strip()
        recipient_name = (
            recipient_name
            or str(getattr(client, "organization", "") or getattr(client, "name", "") or "Client")
        )

        delivery_url = ""
        if status == "out_for_delivery":
            delivery_url = _delivery_note_url(order.pk)

        message = MESSAGES[status].format(
            id=order.pk,
            delivery_url=delivery_url,
        )

        log = CommunicationLog.objects.using(using).create(
            channel=CommunicationLog.CHANNEL_SMS,
            status=CommunicationLog.STATUS_PENDING,
            recipient_name=recipient_name,
            recipient_contact=phone,
            subject=f"Order #{order.pk} - {order.get_status_display()}",
            message=message,
            related_model="Order",
            related_object_id=order.pk,
            provider="SMSPortal",
        )

        if not phone:
            log.status = CommunicationLog.STATUS_FAILED
            log.error_message = "No customer delivery/contact phone number is available."
        else:
            try:
                result = send_sms(to=phone, message=message)
                log.provider_response = (
                    result if isinstance(result, (dict, list))
                    else {"response": str(result)}
                )
                if isinstance(result, dict) and result.get("success"):
                    log.status = CommunicationLog.STATUS_SENT
                    log.sent_at = timezone.now()
                else:
                    log.status = CommunicationLog.STATUS_FAILED
                    log.error_message = str(
                        result.get("response", result)
                        if isinstance(result, dict) else result
                    )
            except Exception as exc:
                log.status = CommunicationLog.STATUS_FAILED
                log.error_message = str(exc)
                logger.exception("Order %s status SMS failed", order_id)

        log.save(using=using)
        return log

    except Exception:
        logger.exception("Could not log/send order %s status SMS", order_id)
        return None
