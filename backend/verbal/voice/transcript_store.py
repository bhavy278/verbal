"""Call transcript + audio storage (both persisted, per product decision).

A ``calls`` document holds turn-by-turn transcript and (optionally) base64 audio
chunks. Retention/privacy policy is a Phase 3 concern; here we simply store both
when enabled by config.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import db as dbmod
from ..config import get_settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def open_call(call_sid: str, tenant_id: str, direction: str = "inbound") -> None:
    await dbmod.calls().update_one(
        {"call_sid": call_sid},
        {
            "$setOnInsert": {
                "_id": call_sid,
                "call_sid": call_sid,
                "tenant_id": tenant_id,
                "direction": direction,
                "started_at": _now_iso(),
                "transcript": [],
                "audio_chunks": 0,
                "order_id": None,
            }
        },
        upsert=True,
    )


async def add_transcript(call_sid: str, role: str, text: str) -> None:
    if not get_settings().store_call_transcript:
        return
    await dbmod.calls().update_one(
        {"call_sid": call_sid},
        {"$push": {"transcript": {"role": role, "text": text, "at": _now_iso()}}},
    )


async def add_audio(call_sid: str, role: str, payload_b64: str) -> None:
    if not get_settings().store_call_audio:
        return
    await dbmod.calls().update_one(
        {"call_sid": call_sid},
        {
            "$push": {"audio": {"role": role, "payload": payload_b64, "at": _now_iso()}},
            "$inc": {"audio_chunks": 1},
        },
    )


async def link_order(call_sid: str, order_id: str) -> None:
    await dbmod.calls().update_one({"call_sid": call_sid}, {"$set": {"order_id": order_id}})


async def truncate_assistant(call_sid: str) -> None:
    """Barge-in: drop the last assistant transcript turn (not fully heard)."""
    doc = await dbmod.calls().find_one({"call_sid": call_sid})
    if not doc:
        return
    transcript = doc.get("transcript", [])
    while transcript and transcript[-1]["role"] == "assistant":
        transcript.pop()
    await dbmod.calls().update_one(
        {"call_sid": call_sid}, {"$set": {"transcript": transcript}}
    )


async def close_call(call_sid: str) -> None:
    await dbmod.calls().update_one(
        {"call_sid": call_sid}, {"$set": {"ended_at": _now_iso()}}
    )


async def get_call(call_sid: str) -> dict | None:
    doc = await dbmod.calls().find_one({"call_sid": call_sid})
    if not doc:
        return None
    doc["id"] = doc.pop("_id")
    return doc
