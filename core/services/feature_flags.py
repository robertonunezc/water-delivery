from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from django.conf import settings
from ldclient.client import LDClient
from ldclient.config import Config
from ldclient.context import Context

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_launchdarkly_client() -> LDClient | None:
    if not settings.LAUNCHDARKLY_ENABLED or not settings.LAUNCHDARKLY_SDK_KEY:
        return None

    try:
        return LDClient(
            Config(settings.LAUNCHDARKLY_SDK_KEY),
            start_wait=settings.LAUNCHDARKLY_START_WAIT_SECONDS,
        )
    except Exception:
        log.exception("Could not initialize LaunchDarkly client")
        return None


def is_feature_enabled(flag_key: str, *, user: Any = None, default: bool = False) -> bool:
    client = get_launchdarkly_client()
    if client is None:
        return default

    try:
        return bool(client.variation(flag_key, _build_context(user), default))
    except Exception:
        log.exception("Could not evaluate LaunchDarkly flag %s", flag_key)
        return default


def is_receipt_signature_enabled(user: Any = None) -> bool:
    return is_feature_enabled(
        settings.LAUNCHDARKLY_RECEIPT_SIGNATURE_FLAG_KEY,
        user=user,
        default=settings.LAUNCHDARKLY_RECEIPT_SIGNATURE_DEFAULT,
    )


def _build_context(user: Any = None) -> Context:
    if user is not None and getattr(user, "is_authenticated", False):
        key = f"user-{user.pk}" if getattr(user, "pk", None) else str(user)
        builder = Context.builder(key).name(getattr(user, "username", "") or key)
        email = getattr(user, "email", "")
        if email:
            builder.set("email", email)
        return builder.build()

    return Context.builder("anonymous").anonymous(True).build()
