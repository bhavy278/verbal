"""Idempotent SubmitOrder via the outbox pattern.

The submission record + order-state change + outbox message are written in a
single Mongo transaction. A unique index on ``(tenant_id, idempotency_key)`` is
the deterministic guard: any duplicate/retried/crashed submit yields exactly one
accepted order.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from . import db as dbmod
from .errors import NotConfirmedError, OrderNotFoundError
from .order.models import Order, OrderStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot(order: Order) -> dict:
    """Authoritative payload handed to the POS (server numbers only)."""
    q = order.quote
    return {
        "order_id": order.id,
        "tenant_id": order.tenant_id,
        "revision": order.revision,
        "currency": order.currency,
        "lines": [ln.model_dump() for ln in order.lines],
        "total": q.total.model_dump() if q else None,
    }


async def _load(order_id: str, session=None) -> Order:
    doc = await dbmod.orders().find_one({"_id": order_id}, session=session)
    if not doc:
        raise OrderNotFoundError(f"No order '{order_id}'")
    return dbmod.load_doc(Order, doc)


async def submit_order(order_id: str, idempotency_key: str) -> Order:
    """Submit an order idempotently. Returns the (possibly already-submitted) order."""
    # Fast path: this idempotency key was already used -> replay current state.
    order = await _load(order_id)
    existing = await dbmod.submissions().find_one(
        {"tenant_id": order.tenant_id, "idempotency_key": idempotency_key}
    )
    if existing is not None:
        return await _load(existing["order_id"])

    if order.status not in (OrderStatus.CONFIRMED, OrderStatus.SUBMITTED, OrderStatus.ACCEPTED):
        raise NotConfirmedError("Order must be confirmed before submitting")
    if order.status in (OrderStatus.SUBMITTED, OrderStatus.ACCEPTED):
        return order  # already in flight / done

    async def _txn(session):
        current = await _load(order_id, session=session)
        if current.status in (OrderStatus.SUBMITTED, OrderStatus.ACCEPTED):
            return current
        submission = {
            "_id": uuid.uuid4().hex,
            "tenant_id": current.tenant_id,
            "idempotency_key": idempotency_key,
            "order_id": current.id,
            "revision": current.revision,
            "created_at": _now_iso(),
        }
        await dbmod.submissions().insert_one(submission, session=session)

        current.status = OrderStatus.SUBMITTED
        current.idempotency_key = idempotency_key
        current.updated_at = datetime.now(timezone.utc)
        await dbmod.orders().replace_one(
            {"_id": current.id}, dbmod.dump_doc(current), session=session
        )

        message = {
            "_id": uuid.uuid4().hex,
            "tenant_id": current.tenant_id,
            "type": "submit_order",
            "order_id": current.id,
            "idempotency_key": idempotency_key,
            "payload": _snapshot(current),
            "status": "pending",
            "attempts": 0,
            "available_at": _now_iso(),
            "created_at": _now_iso(),
            "last_error": None,
        }
        await dbmod.outbox().insert_one(message, session=session)
        return current

    try:
        return await dbmod.in_transaction(_txn)
    except DuplicateKeyError:
        # Concurrent duplicate submit lost the race — replay the winner's state.
        existing = await dbmod.submissions().find_one(
            {"tenant_id": order.tenant_id, "idempotency_key": idempotency_key}
        )
        return await _load(existing["order_id"])
