"""HTTP surface for the domain tools + observability + worker tick."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import db as dbmod
from .. import service, worker
from ..catalog.loader import seed_catalog
from ..config import get_settings

router = APIRouter(prefix="/api", tags=["verbal"])


# -- request bodies ----------------------------------------------------
class StartOrderBody(BaseModel):
    tenant_id: str | None = None


class AddLineBody(BaseModel):
    item_id: str
    variant_id: str
    quantity: int = Field(default=1, ge=1)
    modifier_ids: list[str] = Field(default_factory=list)


class QuantityBody(BaseModel):
    quantity: int = Field(ge=0)


class VariantBody(BaseModel):
    variant_id: str


class ModifiersBody(BaseModel):
    modifier_ids: list[str] = Field(default_factory=list)


class ConfirmBody(BaseModel):
    confirmation_id: str


class SubmitBody(BaseModel):
    idempotency_key: str


# -- health / admin ----------------------------------------------------
@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "verbal", "tenant": get_settings().default_tenant_id}


@router.post("/admin/seed")
async def admin_seed() -> dict:
    await dbmod.ensure_indexes()
    catalog = await seed_catalog()
    return {"seeded": True, "catalog_id": catalog.id, "items": len(catalog.items)}


@router.get("/menu")
async def get_menu(tenant_id: str | None = None) -> dict:
    return await service.menu(tenant_id)


# -- order lifecycle ---------------------------------------------------
@router.post("/orders")
async def start_order(body: StartOrderBody) -> dict:
    return await service.start_order(body.tenant_id)


@router.get("/orders/{order_id}")
async def get_order(order_id: str) -> dict:
    return await service.get_order(order_id)


@router.post("/orders/{order_id}/lines")
async def add_line(order_id: str, body: AddLineBody) -> dict:
    return await service.add_line(order_id, body.item_id, body.variant_id, body.quantity, body.modifier_ids)


@router.patch("/orders/{order_id}/lines/{line_id}/quantity")
async def set_quantity(order_id: str, line_id: str, body: QuantityBody) -> dict:
    return await service.set_line_quantity(order_id, line_id, body.quantity)


@router.patch("/orders/{order_id}/lines/{line_id}/variant")
async def change_variant(order_id: str, line_id: str, body: VariantBody) -> dict:
    return await service.change_variant(order_id, line_id, body.variant_id)


@router.delete("/orders/{order_id}/lines/{line_id}")
async def remove_line(order_id: str, line_id: str) -> dict:
    return await service.remove_line(order_id, line_id)


@router.put("/orders/{order_id}/lines/{line_id}/modifiers")
async def replace_modifiers(order_id: str, line_id: str, body: ModifiersBody) -> dict:
    return await service.replace_modifiers(order_id, line_id, body.modifier_ids)


@router.post("/orders/{order_id}/quote")
async def quote(order_id: str) -> dict:
    return await service.create_quote(order_id)


@router.get("/orders/{order_id}/readback")
async def readback(order_id: str) -> dict:
    return await service.get_readback(order_id)


@router.post("/orders/{order_id}/confirmation")
async def issue_confirmation(order_id: str) -> dict:
    return await service.issue_confirmation(order_id)


@router.post("/orders/{order_id}/confirm")
async def confirm(order_id: str, body: ConfirmBody) -> dict:
    return await service.confirm(order_id, body.confirmation_id)


@router.post("/orders/{order_id}/submit")
async def submit(order_id: str, body: SubmitBody) -> dict:
    return await service.submit_order(order_id, body.idempotency_key)


# -- observability + worker -------------------------------------------
@router.get("/orders")
async def list_orders(tenant_id: str | None = None, limit: int = 25) -> dict:
    tenant_id = tenant_id or get_settings().default_tenant_id
    docs = await dbmod.orders().find({"tenant_id": tenant_id}).sort("created_at", -1).to_list(limit)
    return {
        "orders": [
            {
                "order_id": d["_id"],
                "status": d["status"],
                "revision": d["revision"],
                "lines": len(d.get("lines", [])),
                "pos_order_id": d.get("pos_order_id"),
                "created_at": d.get("created_at"),
            }
            for d in docs
        ]
    }


@router.post("/worker/tick")
async def worker_tick(max_messages: int = 20, reconcile: bool = True) -> dict:
    processed = 0
    while processed < max_messages and await worker.process_once():
        processed += 1
    recovered = await worker.reconcile_stub() if reconcile else 0
    return {"processed": processed, "reconciled": recovered}


@router.get("/outbox")
async def outbox_status(tenant_id: str | None = None) -> dict:
    tenant_id = tenant_id or get_settings().default_tenant_id
    docs = await dbmod.outbox().find({"tenant_id": tenant_id}).sort("created_at", -1).to_list(50)
    return {
        "messages": [
            {
                "id": d["_id"],
                "order_id": d["order_id"],
                "status": d["status"],
                "attempts": d.get("attempts", 0),
                "pos_order_id": d.get("pos_order_id"),
                "last_error": d.get("last_error"),
            }
            for d in docs
        ]
    }
