"""MongoDB access layer: client, collections, indexes, and doc <-> model helpers.

Documents use a string ``_id`` (the domain UUID) so we never leak ``ObjectId``
across the API boundary. Every collection carries ``tenant_id`` and all reads
are tenant-scoped (cross-tenant isolation invariant).
"""

from __future__ import annotations

from typing import Type, TypeVar

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(get_settings().mongo_url)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[get_settings().db_name]


# -- collection accessors ---------------------------------------------
def catalogs():
    return get_db().catalogs


def orders():
    return get_db().orders


def submissions():
    return get_db().submissions


def outbox():
    return get_db().outbox


def pos_orders():
    return get_db().pos_orders


def calls():
    return get_db().calls


async def ensure_indexes() -> None:
    """Create the indexes that enforce correctness invariants."""
    # Idempotency guard: exactly one submission per (tenant, idempotency_key).
    await submissions().create_index(
        [("tenant_id", 1), ("idempotency_key", 1)], unique=True, name="uniq_idem_key"
    )
    # Fake POS is idempotent by (tenant, idempotency_key) too.
    await pos_orders().create_index(
        [("tenant_id", 1), ("idempotency_key", 1)], unique=True, name="uniq_pos_idem"
    )
    await outbox().create_index([("status", 1), ("available_at", 1)], name="outbox_ready")
    await outbox().create_index([("tenant_id", 1)], name="outbox_tenant")
    await orders().create_index([("tenant_id", 1), ("status", 1)], name="orders_tenant_status")
    await catalogs().create_index([("tenant_id", 1)], name="catalog_tenant")
    await calls().create_index([("tenant_id", 1), ("call_sid", 1)], name="calls_sid")


# -- doc conversion ----------------------------------------------------
def dump_doc(model: BaseModel) -> dict:
    """Serialise a model for Mongo: datetimes/enums -> JSON-safe, id -> _id."""
    d = model.model_dump(mode="json")
    if "id" in d:
        d["_id"] = d.pop("id")
    return d


def load_doc(cls: Type[T], doc: dict) -> T:
    """Rehydrate a model from a Mongo doc: _id -> id."""
    data = dict(doc)
    if "_id" in data:
        data["id"] = data.pop("_id")
    return cls.model_validate(data)


async def in_transaction(coro_factory):
    """Run ``coro_factory(session)`` inside a Mongo transaction.

    Requires a replica set (single-node RS is fine for dev). This is what makes
    the order-state-change + outbox write atomic.
    """
    client = get_client()
    async with await client.start_session() as session:
        return await session.with_transaction(lambda s: coro_factory(s))
