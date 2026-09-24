"""Twilio control-plane helpers: signature validation + server-side hang-up.

All guarded by credentials; when Twilio is not configured these are no-ops so
the mock/dev paths keep working. Secrets come only from the environment.
"""

from __future__ import annotations

import logging

from ..config import get_settings

logger = logging.getLogger("verbal.voice.twilio")


def is_configured() -> bool:
    s = get_settings()
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number)


def _validator():
    from twilio.request_validator import RequestValidator

    return RequestValidator(get_settings().twilio_auth_token)


def validate_signature(url: str, params: dict, signature: str) -> bool:
    """Validate an X-Twilio-Signature. True (skip) when no auth token is set."""
    s = get_settings()
    if not s.twilio_auth_token:
        return True  # dev/mock: signature enforcement disabled
    try:
        return _validator().validate(url, params, signature or "")
    except Exception:  # noqa: BLE001
        logger.exception("Twilio signature validation error")
        return False


async def hang_up_call(call_sid: str) -> bool:
    """End a live PSTN call (used by the budget guard). No-op if unconfigured."""
    if not is_configured() or not call_sid:
        return False
    s = get_settings()
    from fastapi.concurrency import run_in_threadpool
    from twilio.rest import Client

    client = Client(s.twilio_account_sid, s.twilio_auth_token)
    try:
        await run_in_threadpool(client.calls(call_sid).update, status="completed")
        logger.info("Hung up call %s", call_sid)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to hang up call %s", call_sid)
        return False
