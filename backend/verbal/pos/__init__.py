"""Fake / sandbox POS adapter (Phase 0-2). Never talks to a real POS.

The adapter is idempotent by ``(tenant_id, idempotency_key)`` via a unique
index, mirroring how a real POS de-dupes retries. A fault injector lets tests
simulate a *lost ack* (POS accepted, but the response never came back), which
the reconciliation stub then recovers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from .. import db as dbmod


class PosAckLost(Exception):
    """The POS accepted the order but the acknowledgement was lost in transit."""

    def __init__(self, pos_order_id: str):
        super().__init__("POS ack lost")
        self.pos_order_id = pos_order_id


class _FaultInjector:
    """Process-local fault injection for sandbox testing only."""

    def __init__(self) -> None:
        self._drop_ack_once: set[str] = set()

    def drop_ack_once(self, idempotency_key: str) -> None:
        self._drop_ack_once.add(idempotency_key)

    def should_drop_ack(self, idempotency_key: str) -> bool:
        if idempotency_key in self._drop_ack_once:
            self._drop_ack_once.discard(idempotency_key)
            return True
        return False

    def reset(self) -> None:
        self._drop_ack_once.clear()


faults = _FaultInjector()


async def submit(tenant_id: str, idempotency_key: str, order_id: str, payload: dict) -> dict:
    """Submit to the fake POS. Idempotent; may raise :class:`PosAckLost`."""
    existing = await dbmod.pos_orders().find_one(
        {"tenant_id": tenant_id, "idempotency_key": idempotency_key}
    )
    if existing is None:
        pos_order_id = "POS-" + uuid.uuid4().hex[:12].upper()
        doc = {
            "_id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
            "order_id": order_id,
            "pos_order_id": pos_order_id,
            "payload": payload,
            "status": "accepted",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await dbmod.pos_orders().insert_one(doc)
        except DuplicateKeyError:
            existing = await dbmod.pos_orders().find_one(
                {"tenant_id": tenant_id, "idempotency_key": idempotency_key}
            )
            pos_order_id = existing["pos_order_id"]
    else:
        pos_order_id = existing["pos_order_id"]

    # The order is durably accepted on the POS side at this point.
    if faults.should_drop_ack(idempotency_key):
        raise PosAckLost(pos_order_id)

    return {"accepted": True, "pos_order_id": pos_order_id}


async def query(tenant_id: str, idempotency_key: str) -> dict | None:
    """Reconciliation lookup: has the POS already accepted this order?"""
    doc = await dbmod.pos_orders().find_one(
        {"tenant_id": tenant_id, "idempotency_key": idempotency_key}
    )
    if not doc:
        return None
    return {"accepted": doc["status"] == "accepted", "pos_order_id": doc["pos_order_id"]}
