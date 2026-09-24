"""FastAPI voice gateway: TwiML, Twilio Media Streams WS, and a text simulate WS/REST."""

from __future__ import annotations

import re

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..config import get_settings
from .orchestrator import MediaOrchestrator, SimulateOrchestrator
from .order_agent import resolve_agent_kind
from .transcript_store import get_call
from . import twilio_control

router = APIRouter(prefix="/api/voice", tags=["voice"])

# In-process registry of live simulate sessions (single-process dev server).
_SIM_SESSIONS: dict[str, SimulateOrchestrator] = {}


class SimStart(BaseModel):
    tenant_id: str | None = None
    agent: str | None = None  # "mock" | "llm"; default follows config


class SimTurn(BaseModel):
    call_sid: str
    text: str


class VerifyCallerBody(BaseModel):
    phone_number: str
    confirm: bool = False  # must be true to place the real (billable) Twilio call


_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


@router.get("/verified-callers")
async def verified_callers() -> dict:
    """List Twilio verified caller IDs (numbers trial calls can connect to)."""
    return {
        "twilio_credentials": twilio_control.has_credentials(),
        "verified": await twilio_control.list_verified_callers(),
    }


@router.post("/verify-caller")
async def verify_caller(body: VerifyCallerBody) -> dict:
    """Start caller-ID verification: Twilio calls the number with a code to key in."""
    number = body.phone_number.strip()
    if not _E164.match(number):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_phone", "message": "Use E.164 format, e.g. +14155550123"},
        )
    if not twilio_control.has_credentials():
        return JSONResponse(
            status_code=400,
            content={"error": "twilio_not_configured", "message": "Twilio credentials are not set"},
        )
    if not body.confirm:
        return JSONResponse(
            status_code=400,
            content={
                "error": "confirmation_required",
                "message": f"This places a real (billable) call to {number}. Resend with confirm=true to proceed.",
            },
        )
    try:
        result = await twilio_control.start_caller_verification(number)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"error": "twilio_error", "message": str(exc)[:300]},
        )
    return {
        **result,
        "message": (
            f"Twilio is calling {result['phone_number']}. When it asks, enter the "
            f"code {result['validation_code']} on your phone keypad to verify."
        ),
    }


@router.get("/readiness")
async def readiness() -> dict:
    """Which voice/LLM/telephony pieces are configured (no secrets leaked)."""
    s = get_settings()
    return {
        "order_agent": resolve_agent_kind(),
        "order_agent_setting": s.order_agent,
        "llm_model": s.llm_model,
        "openai_key_present": bool(s.openai_api_key),
        "voice_provider": s.voice_provider,
        "twilio_configured": twilio_control.is_configured(),
        "twilio_from_number": s.twilio_from_number,
        "twilio_budget_usd": s.twilio_budget_usd,
        "call_cost_per_min_usd": s.call_cost_per_min_usd,
        "public_base_url": s.public_base_url,
        "store_call_audio": s.store_call_audio,
        "store_call_transcript": s.store_call_transcript,
    }


def _public_host(request: Request) -> str:
    """Prefer the exact configured public base URL (needed for signatures)."""
    s = get_settings()
    if s.public_base_url:
        return s.public_base_url.rstrip("/").split("://", 1)[-1]
    return request.url.hostname


@router.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request) -> Response:
    """TwiML that opens a bidirectional Media Stream to our WS."""
    s = get_settings()
    host = _public_host(request)
    # Validate the Twilio signature when credentials are configured.
    if s.twilio_auth_token:
        url = f"https://{host}{request.url.path}"
        if request.method == "POST":
            form = await request.form()
            params = {k: v for k, v in form.multi_items()}
        else:
            params = dict(request.query_params)
        sig = request.headers.get("X-Twilio-Signature", "")
        if not twilio_control.validate_signature(url, params, sig):
            return Response(content="Invalid Twilio signature", status_code=403)

    ws_url = f"wss://{host}/api/voice/media"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Say>Thanks for calling PizzaHub. Connecting you to our ordering assistant.</Say>"
        f'<Connect><Stream url="{ws_url}"/></Connect>'
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


@router.websocket("/media")
async def media_stream(ws: WebSocket) -> None:
    """Twilio <Connect><Stream> bidirectional WebSocket (mu-law 8kHz)."""
    tenant_id = get_settings().default_tenant_id
    orchestrator = MediaOrchestrator(ws, tenant_id)
    try:
        await orchestrator.run()
    except WebSocketDisconnect:
        pass


@router.websocket("/simulate")
async def simulate_ws(ws: WebSocket) -> None:
    """Fake WS for the voice loop without telephony: JSON text turns in/out."""
    await ws.accept()
    orch = SimulateOrchestrator(get_settings().default_tenant_id)
    greeting = await orch.start()
    await ws.send_json({"type": "agent", **greeting})
    try:
        while True:
            data = await ws.receive_json()
            text = data.get("text", "")
            if data.get("type") == "hangup" or text.strip().lower() in ("bye", "hang up"):
                await orch.end()
                await ws.send_json({"type": "ended", "call_sid": orch.call_sid})
                break
            result = await orch.handle_user(text)
            await ws.send_json({"type": "agent", **result})
    except WebSocketDisconnect:
        await orch.end()


@router.post("/simulate/start")
async def simulate_start(body: SimStart) -> dict:
    orch = SimulateOrchestrator(
        body.tenant_id or get_settings().default_tenant_id, agent_kind=body.agent
    )
    greeting = await orch.start()
    _SIM_SESSIONS[orch.call_sid] = orch
    return {**greeting, "agent": orch.agent.name}


@router.post("/simulate/turn")
async def simulate_turn(body: SimTurn) -> dict:
    orch = _SIM_SESSIONS.get(body.call_sid)
    if orch is None:
        return {"error": "unknown_call", "message": "Start a simulate session first"}
    return await orch.handle_user(body.text)


@router.get("/calls/{call_sid}")
async def read_call(call_sid: str) -> dict:
    call = await get_call(call_sid)
    if not call:
        return {"error": "not_found"}
    return call
