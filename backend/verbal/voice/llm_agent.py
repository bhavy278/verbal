"""LLM-driven natural-language order-taker (BYOK OpenAI, via the integration lib).

Same contract as :class:`MockTextAgent` (``handle(session, text, dispatch)``) so
the orchestrator/gateway are unchanged. The model may ONLY select the fixed
order tools; the server executes them and returns authoritative numbers, which
the model reads back. It computes nothing itself.

Uses the user's OWN OpenAI key (``OPENAI_API_KEY``). Falls back to the mock
agent automatically when no key is configured (see ``order_agent`` factory).
"""

from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

from .. import service
from ..config import get_settings
from .tools import TOOL_SPECS
from .voice_model import SYSTEM_PROMPT

logger = logging.getLogger("verbal.voice.llm")

Dispatch = Callable[[str, dict], Awaitable[dict]]


def _chat_tools() -> list[dict]:
    """Convert Realtime-style tool specs to Chat-Completions function schema."""
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
        for t in TOOL_SPECS
    ]


async def _menu_reference(tenant_id: str) -> str:
    """Compact id map so the model can resolve speech -> ids without guessing."""
    menu = await service.menu(tenant_id)
    lines = [f"Restaurant: {menu['name']} (currency {menu['currency']}). Item ids, variant ids, prices (minor units):"]
    for it in menu["items"]:
        variants = ", ".join(f"{v['id']}={v['name']}({v['price']})" for v in it["variants"])
        groups = ",".join(it["modifier_group_ids"]) or "none"
        lines.append(f"- {it['id']} '{it['name']}': variants [{variants}]; modifier_groups [{groups}]")
    lines.append("Modifier groups (id: name [min-max]: modifier ids):")
    for g in menu["modifier_groups"]:
        mods = ", ".join(f"{m['id']}({m['price']})" for m in g["modifiers"])
        lines.append(f"- {g['id']} '{g['name']}' [{g['min_select']}-{g['max_select']}{' required' if g['required'] else ''}]: {mods}")
    lines.append(
        "Pizzas require exactly one crust and one sauce. Always pass valid ids. "
        "Call quote_order then read_back before asking the caller to confirm. "
        "When the caller affirms they want to place the order (e.g. 'yes', 'go "
        "ahead', 'place it'), do NOT ask them to repeat a code word: in the same "
        "turn call request_confirmation, then confirm_order with the returned "
        "confirmation_id, then submit_order, and finally tell them the order is "
        "placed with the POS confirmation number. Read back server totals verbatim "
        "and never invent prices."
    )
    return "\n".join(lines)


class LLMOrderAgent:
    name = "llm"

    def __init__(self, call_sid: str, tenant_id: str):
        self.call_sid = call_sid
        self.tenant_id = tenant_id
        self._chat = None

    async def _ensure_chat(self):
        if self._chat is not None:
            return self._chat
        settings = get_settings()
        from emergentintegrations.llm.chat import LlmChat

        system = SYSTEM_PROMPT + "\n\n" + await _menu_reference(self.tenant_id)
        provider, model = "openai", settings.llm_model
        self._chat = (
            LlmChat(api_key=settings.openai_api_key, session_id=self.call_sid, system_message=system)
            .with_model(provider, model)
            .with_tools(_chat_tools(), tool_choice="auto")
        )
        return self._chat

    async def handle(self, session: dict, text: str, dispatch: Dispatch) -> dict:
        from emergentintegrations.llm.chat import UserMessage

        chat = await self._ensure_chat()
        steps: list[dict] = []
        try:
            resp = await chat.send_message_with_tools(UserMessage(text=text))
            guard = 0
            while getattr(resp, "tool_calls", None) and guard < 12:
                guard += 1
                for tc in resp.tool_calls:
                    args = tc.arguments if isinstance(tc.arguments, dict) else json.loads(tc.arguments or "{}")
                    try:
                        result = await dispatch(tc.name, args)
                    except Exception as exc:  # domain error -> hand back to model as data
                        result = {"error": getattr(exc, "code", "error"), "message": str(exc)}
                    steps.append({"tool": tc.name, "args": args, "result": result})
                    chat.add_tool_result(tc.id, json.dumps(result, default=str))
                resp = await chat.send_message_with_tools()
            reply = (getattr(resp, "content", None) or "").strip() or "Okay."
        except Exception:  # noqa: BLE001
            logger.exception("LLM order-taker failed")
            return {"reply": "Sorry, I'm having trouble right now. Please try again.", "steps": steps, "order": None, "status": None}

        order = None
        status = None
        if session.get("order_id"):
            order = await service.get_order(session["order_id"])
            status = order["status"]
        return {"reply": reply, "steps": steps, "order": order, "status": status}
