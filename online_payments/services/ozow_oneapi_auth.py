import logging
import time
import uuid
from typing import Optional

import requests
from django.conf import settings


logger = logging.getLogger(__name__)

_TOKEN_CACHE = {
    "access_token": None,
    "expires_at": 0,
    "scope": None,
}


class OzowOneAPIAuthError(Exception):
    pass


def _generate_correlation_id() -> str:
    return str(uuid.uuid4())


def _request_new_token(scope: Optional[str] = None) -> dict:
    requested_scope = scope or settings.OZOW_ONEAPI_SCOPE

    if not settings.OZOW_ONEAPI_CLIENT_ID:
        raise OzowOneAPIAuthError("OZOW_ONEAPI_CLIENT_ID is not configured.")

    if not settings.OZOW_ONEAPI_CLIENT_SECRET:
        raise OzowOneAPIAuthError("OZOW_ONEAPI_CLIENT_SECRET is not configured.")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Correlation-ID": _generate_correlation_id(),
    }

    data = {
        "client_id": settings.OZOW_ONEAPI_CLIENT_ID,
        "client_secret": settings.OZOW_ONEAPI_CLIENT_SECRET,
        "scope": requested_scope,
        "grant_type": "client_credentials",
    }

    response = requests.post(
        settings.OZOW_ONEAPI_TOKEN_URL,
        headers=headers,
        data=data,
        timeout=30,
    )

    logger.info("Ozow OneAPI token status: %s", response.status_code)

    if response.status_code != 200:
        logger.error("Ozow OneAPI token error: %s", response.text)
        raise OzowOneAPIAuthError(
            f"Failed to get Ozow OneAPI token. Status {response.status_code}: {response.text}"
        )

    payload = response.json()

    access_token = payload.get("access_token")
    token_type = str(payload.get("token_type", "")).lower()
    expires_in = payload.get("expires_in", "3600")

    if not access_token:
        raise OzowOneAPIAuthError("Token response missing access_token.")

    if token_type != "bearer":
        raise OzowOneAPIAuthError(f"Unexpected token_type: {token_type}")

    try:
        expires_in_seconds = int(expires_in)
    except (TypeError, ValueError):
        expires_in_seconds = 3600

    expires_at = int(time.time()) + max(expires_in_seconds - 60, 60)

    _TOKEN_CACHE["access_token"] = access_token
    _TOKEN_CACHE["expires_at"] = expires_at
    _TOKEN_CACHE["scope"] = requested_scope

    return payload


def get_oneapi_access_token(
    scope: Optional[str] = None,
    force_refresh: bool = False,
) -> str:
    requested_scope = scope or settings.OZOW_ONEAPI_SCOPE
    now_ts = int(time.time())

    if (
        not force_refresh
        and _TOKEN_CACHE["access_token"]
        and _TOKEN_CACHE["expires_at"] > now_ts
        and _TOKEN_CACHE["scope"] == requested_scope
    ):
        return _TOKEN_CACHE["access_token"]

    _request_new_token(scope=requested_scope)
    return _TOKEN_CACHE["access_token"]


def get_oneapi_auth_headers(
    scope: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    token = get_oneapi_access_token(scope=scope)

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Correlation-ID": correlation_id or _generate_correlation_id(),
    }


def generate_correlation_id() -> str:
    return _generate_correlation_id()