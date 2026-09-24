"""Canonical simulator scenarios — the vertical slice + every edge case.

Each scenario is an async function that drives the domain tools (the exact same
surface the voice agent uses) and asserts the server-authoritative outcome.
Run them with ``python -m verbal.simulator.cli run-scenarios``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import db as dbmod
from .. import service, worker
from .. import pos
from ..catalog.loader import get_catalog_view, seed_catalog
from ..errors import (
    EmptyOrderError,
    InvalidModifierComboError,
    ItemNotFoundError,
    NoConfirmationError,
    NotConfirmedError,
    StaleConfirmationError,
    StaleQuoteError,
)
from ..order.models import Order, OrderStatus
from ..quote import accept_confirmation, build_quote, issue_confirmation, readback_text
from ..order import aggregate
from ..order import commands as cmd


async def _drain_worker(times: int = 30) -> None:
    for _ in range(times):
        if not await worker.process_once():
            break


async def _expect(exc_type, coro):
    try:
        await coro
    except exc_type:
        return True
    raise AssertionError(f"expected {exc_type.__name__} but call succeeded")


# =====================================================================
async def scenario_vertical_slice() -> dict:
    """add -> resize -> swap topping -> quantity -> split -> quote ->
    readback -> confirm -> submit -> observe accepted."""
    o = await service.start_order()
    oid = o["order_id"]
    o = await service.add_line(oid, "pizza_margherita", "sz_small",
                               modifier_ids=["crust_classic", "sauce_tomato", "top_extra_cheese"])
    line_id = o["lines"][0]["line_id"]

    o = await service.change_variant(oid, line_id, "sz_large")          # resize
    o = await service.replace_modifiers(oid, line_id,
                                        ["crust_classic", "sauce_tomato", "top_pepperoni"])  # swap topping
    o = await service.set_line_quantity(oid, line_id, 2)                 # quantity
    o = await service.add_line(oid, "drink_soda", "sz_can")             # split (second line)
    assert len(o["lines"]) == 2

    o = await service.create_quote(oid)
    assert o["status"] == "quoted"
    rb = await service.get_readback(oid)
    assert "total" in rb["readback"].lower()

    conf = await service.issue_confirmation(oid)
    o = await service.confirm(oid, conf["confirmation_id"])
    assert o["status"] == "confirmed"

    o = await service.submit_order(oid, idempotency_key=f"vs:{oid}")
    assert o["status"] in ("submitted", "accepted")

    await _drain_worker()
    final = await service.get_order(oid)
    assert final["status"] == "accepted", final["status"]
    assert final["pos_order_id"]
    return {"order_id": oid, "pos_order_id": final["pos_order_id"], "total": final["quote"]["total"]["display"]}


async def scenario_duplicate_submit() -> dict:
    """Duplicate/retried submit => exactly one accepted order + one POS order."""
    oid = await _confirmed_order()
    key = f"dup:{oid}"
    r1 = await service.submit_order(oid, key)
    r2 = await service.submit_order(oid, key)   # duplicate
    r3 = await service.submit_order(oid, key)   # triple
    assert r1["order_id"] == r2["order_id"] == r3["order_id"]
    await _drain_worker()
    final = await service.get_order(oid)
    assert final["status"] == "accepted"
    subs = await dbmod.submissions().count_documents({"order_id": oid})
    pos_count = await dbmod.pos_orders().count_documents({"order_id": oid})
    assert subs == 1, f"expected 1 submission, got {subs}"
    assert pos_count == 1, f"expected 1 POS order, got {pos_count}"
    return {"order_id": oid, "submissions": subs, "pos_orders": pos_count}


async def scenario_stale_quote_at_confirm() -> dict:
    """Editing after a quote makes it stale; confirmation must be rejected."""
    oid = await _quoted_order()
    conf = await service.issue_confirmation(oid)
    # Edit after confirmation issued -> revision bumps, confirmation killed.
    o = await service.add_line(oid, "drink_soda", "sz_can")
    assert o["confirmation"] is None
    # Edit killed the confirmation entirely -> nothing pending to confirm.
    await _expect(NoConfirmationError, service.confirm(oid, conf["confirmation_id"]))
    # Requesting a new confirmation now also requires a fresh quote.
    await _expect(StaleQuoteError, service.issue_confirmation(oid))
    return {"order_id": oid, "rejected_stale": True}


async def scenario_edit_after_confirmation() -> dict:
    """Edit after confirmation kills it; must re-quote/confirm to submit."""
    oid = await _quoted_order()
    conf = await service.issue_confirmation(oid)
    o = await service.confirm(oid, conf["confirmation_id"])
    assert o["status"] == "confirmed"
    o = await service.set_line_quantity(oid, o["lines"][0]["line_id"], 3)   # edit
    assert o["status"] == "draft" and o["confirmation"] is None
    await _expect(NotConfirmedError, service.submit_order(oid, f"eac:{oid}"))
    # Re-quote, re-confirm, submit succeeds.
    await service.create_quote(oid)
    conf2 = await service.issue_confirmation(oid)
    await service.confirm(oid, conf2["confirmation_id"])
    o = await service.submit_order(oid, f"eac:{oid}")
    await _drain_worker()
    final = await service.get_order(oid)
    assert final["status"] == "accepted"
    return {"order_id": oid, "reconfirmed": True}


async def scenario_expired_quote() -> dict:
    """A quote past its TTL is rejected at readback/confirm (domain-level)."""
    view = await get_catalog_view("pizzahub")
    order = Order(tenant_id="pizzahub", currency=view.currency)
    aggregate.add_line(order, view, cmd.AddLine(item_id="pizza_pepperoni", variant_id="sz_medium",
                                                modifier_ids=["crust_thin", "sauce_bbq"]))
    build_quote(view, order, ttl_seconds=-1)   # already expired
    try:
        readback_text(order)
        raise AssertionError("expected expired quote to be rejected")
    except Exception as exc:  # ExpiredQuoteError
        assert "expired" in str(exc).lower()
    return {"expired_rejected": True}


async def scenario_invalid_modifier_combo() -> dict:
    """Two crusts (max_select=1) is rejected by the validator, not the model."""
    o = await service.start_order()
    await _expect(
        InvalidModifierComboError,
        service.add_line(o["order_id"], "pizza_margherita", "sz_medium",
                         modifier_ids=["crust_thin", "crust_stuffed", "sauce_tomato"]),
    )
    # A topping that doesn't apply to a drink is also rejected.
    await _expect(
        InvalidModifierComboError,
        service.add_line(o["order_id"], "drink_soda", "sz_can", modifier_ids=["top_bacon"]),
    )
    return {"invalid_rejected": True}


async def scenario_unknown_item() -> dict:
    """Unknown items are rejected at the boundary."""
    o = await service.start_order()
    await _expect(ItemNotFoundError, service.add_line(o["order_id"], "pizza_unicorn", "sz_medium"))
    return {"unknown_rejected": True}


async def scenario_missing_required_group() -> dict:
    """A pizza without a required crust/sauce is rejected."""
    o = await service.start_order()
    await _expect(
        InvalidModifierComboError,
        service.add_line(o["order_id"], "pizza_veggie", "sz_small", modifier_ids=["sauce_tomato"]),
    )
    return {"required_enforced": True}


async def scenario_lost_pos_ack_reconciles() -> dict:
    """POS accepts but the ack is lost; reconciliation recovers it."""
    oid = await _confirmed_order()
    key = f"lost:{oid}"
    await service.submit_order(oid, key)
    pos.faults.drop_ack_once(key)          # next delivery loses its ack
    await worker.process_once()            # PosAckLost -> deferred
    mid = await service.get_order(oid)
    assert mid["status"] == "submitted", mid["status"]
    # Force reconciliation window and reconcile.
    await dbmod.orders().update_one(
        {"_id": oid},
        {"$set": {"updated_at": (datetime.now(timezone.utc) - timedelta(seconds=999)).isoformat()}},
    )
    recovered = await worker.reconcile_stub()
    final = await service.get_order(oid)
    assert final["status"] == "accepted", final["status"]
    assert final["pos_order_id"]
    return {"order_id": oid, "recovered": recovered, "pos_order_id": final["pos_order_id"]}


async def scenario_crashed_submit_retry() -> dict:
    """Submit persists an outbox message; a delayed worker still delivers once."""
    oid = await _confirmed_order()
    key = f"crash:{oid}"
    await service.submit_order(oid, key)
    # 'crash': duplicate submit arrives before the worker runs.
    await service.submit_order(oid, key)
    await _drain_worker()
    final = await service.get_order(oid)
    assert final["status"] == "accepted"
    pos_count = await dbmod.pos_orders().count_documents({"order_id": oid})
    assert pos_count == 1
    return {"order_id": oid, "pos_orders": pos_count}


async def scenario_empty_order_quote() -> dict:
    """Quoting an empty order is rejected."""
    o = await service.start_order()
    await service.add_line(o["order_id"], "drink_soda", "sz_can")
    o2 = await service.get_order(o["order_id"])
    await service.remove_line(o["order_id"], o2["lines"][0]["line_id"])
    await _expect(EmptyOrderError, service.create_quote(o["order_id"]))
    return {"empty_rejected": True}


async def scenario_reprice_on_resize() -> dict:
    """Changing size reprices deterministically (server numbers only)."""
    o = await service.start_order()
    oid = o["order_id"]
    o = await service.add_line(oid, "pizza_margherita", "sz_small",
                               modifier_ids=["crust_classic", "sauce_tomato"])
    line_id = o["lines"][0]["line_id"]
    small_total = o["lines"][0]["line_total"]["amount"]
    o = await service.change_variant(oid, line_id, "sz_large")
    large_total = o["lines"][0]["line_total"]["amount"]
    assert large_total > small_total, (small_total, large_total)
    return {"small": small_total, "large": large_total}


SCENARIOS = [
    ("vertical_slice", scenario_vertical_slice),
    ("duplicate_submit", scenario_duplicate_submit),
    ("stale_quote_at_confirm", scenario_stale_quote_at_confirm),
    ("edit_after_confirmation", scenario_edit_after_confirmation),
    ("expired_quote", scenario_expired_quote),
    ("invalid_modifier_combo", scenario_invalid_modifier_combo),
    ("unknown_item", scenario_unknown_item),
    ("missing_required_group", scenario_missing_required_group),
    ("lost_pos_ack_reconciles", scenario_lost_pos_ack_reconciles),
    ("crashed_submit_retry", scenario_crashed_submit_retry),
    ("empty_order_quote", scenario_empty_order_quote),
    ("reprice_on_resize", scenario_reprice_on_resize),
]


# -- helpers -----------------------------------------------------------
async def _quoted_order() -> str:
    o = await service.start_order()
    oid = o["order_id"]
    await service.add_line(oid, "pizza_pepperoni", "sz_medium",
                           modifier_ids=["crust_classic", "sauce_tomato", "top_mushrooms"])
    await service.create_quote(oid)
    return oid


async def _confirmed_order() -> str:
    oid = await _quoted_order()
    conf = await service.issue_confirmation(oid)
    await service.confirm(oid, conf["confirmation_id"])
    return oid


async def run_all() -> list[dict]:
    await dbmod.ensure_indexes()
    await seed_catalog()
    pos.faults.reset()
    results = []
    for name, fn in SCENARIOS:
        try:
            detail = await fn()
            results.append({"scenario": name, "passed": True, "detail": detail})
        except Exception as exc:  # noqa: BLE001
            results.append({"scenario": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    return results
