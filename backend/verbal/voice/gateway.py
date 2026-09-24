"""FastAPI voice gateway: TwiML, Twilio Media Streams WS, and a text simulate WS/REST."""

from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from ..config import get_settings
from .orchestrator import MediaOrchestrator, SimulateOrchestrator
from .order_agent import resolve_agent_kind
from .transcript_store import get_call

router = APIRouter(prefix="/api/voice", tags=["voice"])

# In-process registry of live simulate sessions (single-process dev server).
_SIM_SESSIONS: dict[str, SimulateOrchestrator] = {}


class SimStart(BaseModel):
    tenant_id: str | None = None


class SimTurn(BaseModel):
    call_sid: str
    text: str


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
        "twilio_configured": bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number),
        "twilio_from_number": s.twilio_from_number,
        "twilio_budget_usd": s.twilio_budget_usd,
        "store_call_audio": s.store_call_audio,
        "store_call_transcript": s.store_call_transcript,
    }


@router.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request) -> Response:
    """TwiML that opens a bidirectional Media Stream to our WS."""
    host = request.url.hostname
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
    orch = SimulateOrchestrator(body.tenant_id or get_settings().default_tenant_id)
    greeting = await orch.start()
    _SIM_SESSIONS[orch.call_sid] = orch
    return greeting


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
