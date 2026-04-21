import logging
from typing import Optional

import requests
from django.conf import settings

from online_payments.services.ozow_oneapi_auth import get_oneapi_auth_headers


logger = logging.getLogger(__name__)


class OzowOneAPIMethodsError(Exception):
    pass


def get_oneapi_payment_methods(
    *,
    site_code: Optional[str] = None,
    region: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    forwarded_for: Optional[str] = None,
) -> dict:
    url = f"{settings.OZOW_ONEAPI_BASE_URL}/v1/paymentmethods"

    params = {
        "siteCode": site_code or settings.OZOW_ONEAPI_SITE_CODE,
        "region": region or settings.OZOW_ONEAPI_REGION,
        "limit": limit,
        "offset": offset,
    }

    headers = get_oneapi_auth_headers()

    if forwarded_for:
        headers["X-Forwarded-For"] = forwarded_for

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    logger.info("Ozow OneAPI payment methods status: %s", response.status_code)

    if response.status_code != 200:
        logger.error("Ozow OneAPI payment methods error: %s", response.text)
        raise OzowOneAPIMethodsError(
            f"Failed to get OneAPI payment methods. "
            f"Status {response.status_code}: {response.text}"
        )

    return response.json()