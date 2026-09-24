"""Factory that picks the order-taker: LLM (BYOK OpenAI) or deterministic mock."""

from __future__ import annotations

import logging

from ..config import get_settings
from .mock_model import MockTextAgent

logger = logging.getLogger("verbal.voice.agent")


def resolve_agent_kind() -> str:
    settings = get_settings()
    choice = settings.order_agent
    if choice == "llm":
        return "llm" if settings.openai_api_key else "mock"
    if choice == "mock":
        return "mock"
    # auto
    return "llm" if settings.openai_api_key else "mock"


def get_order_agent(call_sid: str, tenant_id: str, kind: str | None = None):
    kind = kind or resolve_agent_kind()
    if kind == "llm":
        from .llm_agent import LLMOrderAgent

        return LLMOrderAgent(call_sid, tenant_id)
    return MockTextAgent()
