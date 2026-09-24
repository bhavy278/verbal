"""Async outbox worker: enqueue -> lease -> deliver -> mark done.

Runs as a separate process (``python -m verbal.worker``). Leases messages with
a TTL via atomic ``find_one_and_update`` so multiple workers are safe. Delivery
to the fake POS is at-least-once; the POS is idempotent, and a reconciliation
stub recovers lost acks.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from . import db as dbmod
from . import pos
from .config import get_settings
from .order.models import Order, OrderStatus
from .submit import _load  # reuse loader

logger = logging.getLogger("verbal.worker")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _lease_one():
    settings = get_settings()
    now = _now()
    now_iso = _iso(now)
    lease_until = _iso(now + timedelta(seconds=settings.outbox_lease_seconds))
    return await dbmod.outbox().find_one_and_update(
        {
            "available_at": {"$lte": now_iso},
            "$or": [
                {"status": "pending"},
                {"status": "leased", "lease_expires": {"$lte": now_iso}},
            ],
        },
        {"$set": {"status": "leased", "lease_expires": lease_until}, "$inc": {"attempts": 1}},
        sort=[("available_at", 1)],
        return_document=ReturnDocument.AFTER,
    )


async def _mark_delivered(message: dict, pos_order_id: str) -> None:
    async def _txn(session):
        order = await _load(message["order_id"], session=session)
        order.status = OrderStatus.ACCEPTED
        order.pos_order_id = pos_order_id
        order.updated_at = _now()
        await dbmod.orders().replace_one(
            {"_id": order.id}, dbmod.dump_doc(order), session=session
        )
        await dbmod.outbox().update_one(
            {"_id": message["_id"]},
            {"$set": {"status": "done", "pos_order_id": pos_order_id, "completed_at": _iso(_now())}},
            session=session,
        )
    await dbmod.in_transaction(_txn)


async def _defer(message: dict, error: str) -> None:
    settings = get_settings()
    if message["attempts"] >= settings.outbox_max_attempts:
        await dbmod.outbox().update_one(
            {"_id": message["_id"]},
            {"$set": {"status": "dead", "last_error": error}},
        )
        order = await _load(message["order_id"])
        if order.status == OrderStatus.SUBMITTED:
            await dbmod.orders().update_one(
                {"_id": order.id}, {"$set": {"status": OrderStatus.FAILED.value}}
            )
        logger.error("Outbox message %s dead: %s", message["_id"], error)
        return
    backoff = min(2 ** message["attempts"], 30)
    await dbmod.outbox().update_one(
        {"_id": message["_id"]},
        {"$set": {"status": "pending", "available_at": _iso(_now() + timedelta(seconds=backoff)), "last_error": error}},
    )


async def process_once() -> bool:
    """Lease + process a single outbox message. Returns True if work was done."""
    message = await _lease_one()
    if message is None:
        return False
    try:
        result = await pos.submit(
            message["tenant_id"], message["idempotency_key"], message["order_id"], message["payload"]
        )
        await _mark_delivered(message, result["pos_order_id"])
        logger.info("Delivered order %s -> %s", message["order_id"], result["pos_order_id"])
    except pos.PosAckLost as exc:
        # POS accepted but ack lost; leave for retry / reconciliation.
        await _defer(message, f"pos_ack_lost:{exc.pos_order_id}")
        logger.warning("Lost POS ack for order %s (will reconcile)", message["order_id"])
    except Exception as exc:  # noqa: BLE001
        await _defer(message, str(exc))
        logger.exception("Delivery failed for order %s", message["order_id"])
    return True


async def reconcile_stub() -> int:
    """Recover lost POS acks: for still-SUBMITTED orders, ask the POS directly.

    Promoted to a full reconciliation loop in Phase 3.
    """
    settings = get_settings()
    cutoff = _iso(_now() - timedelta(seconds=settings.pos_reconcile_after_seconds))
    recovered = 0
    async for doc in dbmod.orders().find(
        {"status": OrderStatus.SUBMITTED.value, "updated_at": {"$lte": cutoff}}
    ):
        order = dbmod.load_doc(Order, doc)
        if not order.idempotency_key:
            continue
        result = await pos.query(order.tenant_id, order.idempotency_key)
        if result and result["accepted"]:
            await dbmod.orders().update_one(
                {"_id": order.id},
                {"$set": {"status": OrderStatus.ACCEPTED.value, "pos_order_id": result["pos_order_id"]}},
            )
            await dbmod.outbox().update_many(
                {"order_id": order.id, "status": {"$ne": "done"}},
                {"$set": {"status": "done", "pos_order_id": result["pos_order_id"], "completed_at": _iso(_now())}},
            )
            recovered += 1
    return recovered


async def run_forever() -> None:
    settings = get_settings()
    await dbmod.ensure_indexes()
    logger.info("Outbox worker started (poll=%ss)", settings.worker_poll_seconds)
    reconcile_every = 20
    ticks = 0
    while True:
        did = await process_once()
        ticks += 1
        if ticks % reconcile_every == 0:
            await reconcile_stub()
        if not did:
            await asyncio.sleep(settings.worker_poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
