"""Domain tools facade — the single surface reused by the CLI, the HTTP API,
and the voice orchestrator. The voice model may ONLY call these; it computes no
prices, availability, or acceptance itself.
"""

from __future__ import annotations

from . import db as dbmod
from . import quote as quote_mod
from . import submit as submit_mod
from .catalog.loader import get_catalog, get_catalog_view
from .config import get_settings
from .errors import OrderNotFoundError
from .order import aggregate
from .order import commands as cmd
from .order.models import Order
from .views import order_view


async def _load(order_id: str) -> Order:
    doc = await dbmod.orders().find_one({"_id": order_id})
    if not doc:
        raise OrderNotFoundError(f"No order '{order_id}'")
    return dbmod.load_doc(Order, doc)


async def _save(order: Order) -> None:
    await dbmod.orders().replace_one({"_id": order.id}, dbmod.dump_doc(order), upsert=True)


async def _view(order: Order) -> dict:
    view = await get_catalog_view(order.tenant_id)
    return order_view(order, view)


# -- lifecycle --------------------------------------------------------
async def start_order(tenant_id: str | None = None) -> dict:
    tenant_id = tenant_id or get_settings().default_tenant_id
    catalog = await get_catalog(tenant_id)
    order = Order(tenant_id=tenant_id, currency=catalog.currency)
    await _save(order)
    return await _view(order)


async def get_order(order_id: str) -> dict:
    return await _view(await _load(order_id))


# -- mutating commands ------------------------------------------------
async def add_line(order_id: str, item_id: str, variant_id: str, quantity: int = 1, modifier_ids: list[str] | None = None) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    aggregate.add_line(order, view, cmd.AddLine(item_id=item_id, variant_id=variant_id, quantity=quantity, modifier_ids=modifier_ids or []))
    await _save(order)
    return order_view(order, view)


async def set_line_quantity(order_id: str, line_id: str, quantity: int) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    aggregate.set_line_quantity(order, view, cmd.SetLineQuantity(line_id=line_id, quantity=quantity))
    await _save(order)
    return order_view(order, view)


async def change_variant(order_id: str, line_id: str, variant_id: str) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    aggregate.change_variant(order, view, cmd.ChangeVariant(line_id=line_id, variant_id=variant_id))
    await _save(order)
    return order_view(order, view)


async def remove_line(order_id: str, line_id: str) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    aggregate.remove_line(order, view, cmd.RemoveLine(line_id=line_id))
    await _save(order)
    return order_view(order, view)


async def replace_modifiers(order_id: str, line_id: str, modifier_ids: list[str]) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    aggregate.replace_modifiers(order, view, cmd.ReplaceModifiers(line_id=line_id, modifier_ids=modifier_ids))
    await _save(order)
    return order_view(order, view)


# -- quote / confirm / submit ----------------------------------------
async def create_quote(order_id: str) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    quote_mod.build_quote(view, order, get_settings().quote_ttl_seconds)
    await _save(order)
    return order_view(order, view)


async def get_readback(order_id: str) -> dict:
    order = await _load(order_id)
    text = quote_mod.readback_text(order)
    return {"order_id": order.id, "revision": order.revision, "readback": text}


async def issue_confirmation(order_id: str) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    confirmation = quote_mod.issue_confirmation(order)
    await _save(order)
    return {
        "order_id": order.id,
        "revision": order.revision,
        "confirmation_id": confirmation.confirmation_id,
        "challenge": confirmation.challenge,
    }


async def confirm(order_id: str, confirmation_id: str) -> dict:
    order = await _load(order_id)
    view = await get_catalog_view(order.tenant_id)
    quote_mod.accept_confirmation(order, confirmation_id)
    await _save(order)
    return order_view(order, view)


async def submit_order(order_id: str, idempotency_key: str) -> dict:
    order = await submit_mod.submit_order(order_id, idempotency_key)
    return await _view(order)


async def menu(tenant_id: str | None = None) -> dict:
    from .views import menu_view

    tenant_id = tenant_id or get_settings().default_tenant_id
    return menu_view(await get_catalog(tenant_id))
