"""Runtime configuration, sourced only from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent  # /app/backend
load_dotenv(ROOT_DIR / ".env")


class Settings:
    """Environment-backed settings. No secrets are hardcoded here."""

    def __init__(self) -> None:
        self.mongo_url: str = os.environ["MONGO_URL"]
        self.db_name: str = os.environ["DB_NAME"]

        # Single-tenant pilot; multi-tenant fields present but not exercised.
        self.default_tenant_id: str = os.environ.get("VERBAL_TENANT_ID", "pizzahub")

        # Quote lifecycle
        self.quote_ttl_seconds: int = int(os.environ.get("VERBAL_QUOTE_TTL_SECONDS", "180"))

        # Outbox worker
        self.outbox_lease_seconds: int = int(os.environ.get("VERBAL_OUTBOX_LEASE_SECONDS", "30"))
        self.outbox_max_attempts: int = int(os.environ.get("VERBAL_OUTBOX_MAX_ATTEMPTS", "8"))
        self.worker_poll_seconds: float = float(os.environ.get("VERBAL_WORKER_POLL_SECONDS", "0.5"))

        # Fake POS behaviour (sandbox only)
        self.pos_reconcile_after_seconds: int = int(
            os.environ.get("VERBAL_POS_RECONCILE_AFTER_SECONDS", "10")
        )

        # Voice (Phase 2). No live keys required for the mock path.
        # provider: "mock" (default) | "openai_realtime" | "stitched"
        self.voice_provider: str = os.environ.get("VERBAL_VOICE_PROVIDER", "mock")
        self.openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
        self.openai_realtime_model: str = os.environ.get(
            "VERBAL_OPENAI_REALTIME_MODEL", "gpt-realtime"
        )
        self.openai_realtime_voice: str = os.environ.get("VERBAL_OPENAI_REALTIME_VOICE", "alloy")

        # Natural-language order-taker (text simulate + console + orchestrator brain).
        # "auto" -> LLM when OPENAI_API_KEY is present, else deterministic mock.
        self.order_agent: str = os.environ.get("VERBAL_ORDER_AGENT", "auto")
        self.llm_model: str = os.environ.get("VERBAL_LLM_MODEL", "gpt-5.4")

        # Twilio telephony (Phase 2 live). Build-and-verify; secrets added later.
        self.twilio_account_sid: str | None = os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token: str | None = os.environ.get("TWILIO_AUTH_TOKEN")
        self.twilio_from_number: str | None = os.environ.get("TWILIO_FROM_NUMBER")
        self.twilio_budget_usd: float = float(os.environ.get("VERBAL_TWILIO_BUDGET_USD", "10"))
        # Store both call audio + transcript (per product decision).
        self.store_call_audio: bool = os.environ.get("VERBAL_STORE_CALL_AUDIO", "true") == "true"
        self.store_call_transcript: bool = (
            os.environ.get("VERBAL_STORE_CALL_TRANSCRIPT", "true") == "true"
        )
        self.max_call_seconds: int = int(os.environ.get("VERBAL_MAX_CALL_SECONDS", "600"))
        self.silence_timeout_seconds: int = int(
            os.environ.get("VERBAL_SILENCE_TIMEOUT_SECONDS", "15")
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
