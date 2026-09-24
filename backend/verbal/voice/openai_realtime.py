"""OpenAI GPT Realtime (S2S) adapter over Twilio Media Streams.

DORMANT BY DEFAULT. Activates only when ``VERBAL_VOICE_PROVIDER=openai_realtime``
and ``OPENAI_API_KEY`` is set (BYOK — the user's own key). Uses g711_ulaw audio
so it bridges directly to Twilio's mu-law 8kHz stream. Wired for a live staging
call in Phase 2; not exercised without credentials.

Model tool calls are routed to the same domain tools as every other path, so
the model computes no prices/availability/acceptance.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from ..config import get_settings
from .tools import TOOL_SPECS
from .voice_model import SYSTEM_PROMPT, VoiceModel

logger = logging.getLogger("verbal.voice.openai")

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model={model}"


class OpenAIRealtimeVoiceModel(VoiceModel):
    name = "openai_realtime"

    def __init__(self) -> None:
        self._ws = None
        self._pump_task: asyncio.Task | None = None
        self._send_audio = None
        self._clear_audio = None
        self._dispatch_tool = None
        self._session = None
        self._assistant_speaking = False

    async def open(self, *, send_audio, clear_audio, dispatch_tool, session) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set; cannot open Realtime session")
        try:
            import websockets  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("`websockets` package required for OpenAI Realtime") from exc

        self._send_audio = send_audio
        self._clear_audio = clear_audio
        self._dispatch_tool = dispatch_tool
        self._session = session

        import websockets

        self._ws = await websockets.connect(
            OPENAI_REALTIME_URL.format(model=settings.openai_realtime_model),
            additional_headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            max_size=None,
        )
        await self._configure_session()
        self._pump_task = asyncio.create_task(self._pump_upstream())

    async def _configure_session(self) -> None:
        # GA Realtime shape (session.type=realtime, nested audio, audio/pcmu).
        await self._ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "instructions": SYSTEM_PROMPT,
                        "output_modalities": ["audio"],
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcmu"},
                                "noise_reduction": {"type": "far_field"},
                                "turn_detection": {
                                    "type": "server_vad",
                                    "threshold": 0.6,
                                    "prefix_padding_ms": 300,
                                    "silence_duration_ms": 600,
                                    "interrupt_response": True,
                                    "create_response": True,
                                },
                            },
                            "output": {
                                "format": {"type": "audio/pcmu"},
                                "voice": get_settings().openai_realtime_voice,
                            },
                        },
                        "tools": TOOL_SPECS,
                        "tool_choice": "auto",
                    },
                }
            )
        )
        # Greet first.
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def receive_audio(self, mulaw_b64: str) -> None:
        if self._ws is None:
            return
        await self._ws.send(
            json.dumps({"type": "input_audio_buffer.append", "audio": mulaw_b64})
        )

    async def _pump_upstream(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                event = json.loads(raw)
                await self._handle_event(event)
        except Exception:  # noqa: BLE001
            logger.exception("OpenAI Realtime pump stopped")

    async def _handle_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype in ("response.output_audio.delta", "response.audio.delta"):
            self._assistant_speaking = True
            await self._emit_framed(event["delta"])
        elif etype in ("response.output_audio.done", "response.audio.done", "response.done"):
            self._assistant_speaking = False
        elif etype == "input_audio_buffer.speech_started":
            # Barge-in: only act if the agent is actually talking. Server VAD
            # already interrupts the model, so we just flush Twilio's buffer.
            if self._assistant_speaking:
                self._assistant_speaking = False
                await self._clear_audio()
        elif etype == "response.function_call_arguments.done":
            await self._run_tool(event)
        elif etype == "error":
            logger.warning("OpenAI Realtime error: %s", event.get("error"))

    async def _emit_framed(self, delta_b64: str) -> None:
        """Split an audio delta into 20ms (160-byte) mu-law frames for Twilio."""
        try:
            raw = base64.b64decode(delta_b64)
        except Exception:  # noqa: BLE001
            await self._send_audio(delta_b64)
            return
        for i in range(0, len(raw), 160):
            frame = raw[i:i + 160]
            await self._send_audio(base64.b64encode(frame).decode())

    async def _run_tool(self, event: dict) -> None:
        name = event.get("name")
        call_id = event.get("call_id")
        try:
            args = json.loads(event.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            result = await self._dispatch_tool(name, args)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
        await self._ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result),
                    },
                }
            )
        )
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def close(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def say(self, text: str) -> None:
        """Make the model speak an exact server-authored closing line."""
        if self._ws is None:
            return
        await self._ws.send(
            json.dumps(
                {
                    "type": "response.create",
                    "response": {"modalities": ["audio", "text"], "instructions": f"Say exactly: {text}"},
                }
            )
        )
