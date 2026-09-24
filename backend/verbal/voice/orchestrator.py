"""Voice orchestrators reusing the domain tools.

Two entry points, one tool contract:
  * :class:`SimulateOrchestrator` — text-driven (MockTextAgent), fully testable
    without any keys; drives the exact same tools as the phone path.
  * :class:`MediaOrchestrator` — Twilio Media Streams bridge over a
    :class:`VoiceModel` adapter (mock or OpenAI Realtime), with barge-in.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from . import tools as voice_tools
from . import transcript_store as ts
from . import twilio_control
from .call_state import BUDGET_CLOSING, DURATION_CLOSING, CallState, CallStateMachine
from .order_agent import get_order_agent
from .voice_model import get_voice_model


class SimulateOrchestrator:
    """Text simulate loop for the fake WebSocket (no telephony/keys required)."""

    def __init__(self, tenant_id: str, call_sid: str | None = None, agent_kind: str | None = None):
        self.call_sid = call_sid or "sim-" + uuid.uuid4().hex[:10]
        self.session = {"tenant_id": tenant_id, "call_sid": self.call_sid}
        self.agent = get_order_agent(self.call_sid, tenant_id, agent_kind)
        self.fsm = CallStateMachine()

    async def start(self) -> dict:
        await ts.open_call(self.call_sid, self.session["tenant_id"], direction="simulate")
        self.fsm.transition(CallState.GREETING)
        greeting = "Hi, thanks for calling PizzaHub! This is Verbal. What can I get started for you?"
        await ts.add_transcript(self.call_sid, "assistant", greeting)
        self.fsm.transition(CallState.LISTENING)
        return {"call_sid": self.call_sid, "reply": greeting}

    async def handle_user(self, text: str) -> dict:
        self.fsm.mark_caller_input()
        # Budget guard: cut the call short politely if the ceiling is reached.
        if self.fsm.state != CallState.ENDED and self.fsm.budget_exceeded():
            await ts.add_transcript(self.call_sid, "user", text)
            await ts.add_transcript(self.call_sid, "assistant", BUDGET_CLOSING)
            self.fsm.end()
            await ts.close_call(self.call_sid)
            return {
                "call_sid": self.call_sid, "reply": BUDGET_CLOSING, "ended": True,
                "order": None, "status": None, "tool_calls": [],
                "budget": self._budget(),
            }

        self.fsm.transition(CallState.THINKING)
        await ts.add_transcript(self.call_sid, "user", text)

        async def dispatch(name: str, args: dict) -> dict:
            return await voice_tools.dispatch(self.session, name, args)

        result = await self.agent.handle(self.session, text, dispatch)
        reply = result["reply"]
        await ts.add_transcript(self.call_sid, "assistant", reply)
        if self.session.get("order_id"):
            await ts.link_order(self.call_sid, self.session["order_id"])
        self.fsm.transition(CallState.LISTENING)
        return {
            "call_sid": self.call_sid,
            "reply": reply,
            "order": result.get("order"),
            "status": result.get("status"),
            "tool_calls": [{"tool": s["tool"], "args": s["args"]} for s in result["steps"]],
            "budget": self._budget(),
        }

    def _budget(self) -> dict:
        return {
            "estimated_cost_usd": round(self.fsm.estimated_cost_usd(), 4),
            "cap_usd": self.fsm.budget_usd,
            "exceeded": self.fsm.budget_exceeded(),
        }

    async def end(self) -> None:
        self.fsm.end()
        await ts.close_call(self.call_sid)


class MediaOrchestrator:
    """Bridges a Twilio Media Streams WebSocket to a VoiceModel adapter."""

    def __init__(self, twilio_ws, tenant_id: str):
        self.ws = twilio_ws
        self.tenant_id = tenant_id
        self.stream_sid: str | None = None
        self.call_sid: str | None = None
        self.model = get_voice_model()
        self.session = {"tenant_id": tenant_id}
        self.fsm = CallStateMachine()
        self._monitor: asyncio.Task | None = None
        self._ending = False

    async def _send_audio(self, payload_b64: str) -> None:
        if self.stream_sid:
            self.fsm.transition(CallState.AGENT_SPEAKING)
            await self.ws.send_text(
                json.dumps({"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload_b64}})
            )
            if self.call_sid:
                await ts.add_audio(self.call_sid, "assistant", payload_b64)

    async def _clear_audio(self) -> None:
        # Barge-in: flush whatever Twilio has buffered and truncate transcript.
        if self.stream_sid:
            await self.ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))
        if self.call_sid:
            await ts.truncate_assistant(self.call_sid)
        self.fsm.transition(CallState.LISTENING)

    async def _dispatch(self, name: str, args: dict) -> dict:
        result = await voice_tools.dispatch(self.session, name, args)
        if self.call_sid and self.session.get("order_id"):
            await ts.link_order(self.call_sid, self.session["order_id"])
        return result

    async def _monitor_limits(self) -> None:
        """Watchdog: end the call politely on budget or max-duration limits."""
        while not self._ending:
            await asyncio.sleep(1.0)
            if self.fsm.budget_exceeded():
                await self._end_call(BUDGET_CLOSING, "budget")
                return
            if self.fsm.should_end_for_duration():
                await self._end_call(DURATION_CLOSING, "max_duration")
                return

    async def _end_call(self, closing: str, reason: str) -> None:
        if self._ending:
            return
        self._ending = True
        try:
            if self.call_sid:
                await ts.add_transcript(self.call_sid, "assistant", closing)
                await ts.mark_end_reason(self.call_sid, reason)
            await self.model.say(closing)     # speak the closing line to the caller
            await asyncio.sleep(2.0)           # let the audio flush
            await twilio_control.hang_up_call(self.call_sid)  # end the PSTN leg
        finally:
            self.fsm.end()
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def run(self) -> None:
        """Consume Twilio Media Stream frames until the call ends."""
        await self.ws.accept()
        try:
            async for raw in self.ws.iter_text():
                msg = json.loads(raw)
                event = msg.get("event")
                if event == "start":
                    start = msg["start"]
                    self.stream_sid = start["streamSid"]
                    self.call_sid = start.get("callSid", self.stream_sid)
                    await ts.open_call(self.call_sid, self.tenant_id, direction="inbound")
                    self.fsm.transition(CallState.GREETING)
                    await self.model.open(
                        send_audio=self._send_audio,
                        clear_audio=self._clear_audio,
                        dispatch_tool=self._dispatch,
                        session=self.session,
                    )
                    self._monitor = asyncio.create_task(self._monitor_limits())
                elif event == "media":
                    self.fsm.mark_caller_input()
                    payload = msg["media"]["payload"]
                    if self.call_sid:
                        await ts.add_audio(self.call_sid, "caller", payload)
                    await self.model.receive_audio(payload)
                elif event == "mark":
                    await self.model.on_mark(msg.get("mark", {}).get("name", ""))
                elif event == "stop":
                    break
        finally:
            self._ending = True
            if self._monitor:
                self._monitor.cancel()
            await self.model.close()
            if self.call_sid:
                await ts.close_call(self.call_sid)
