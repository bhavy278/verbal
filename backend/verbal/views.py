"""Server-authoritative view builders (dicts returned to CLI / API / voice).

All monetary figures come from the pricing engine so the voice model only ever
reads back numbers the server computed.
"""

from __future__ import annotations

from .catalog.schema import Catalog, CatalogView
from .money import Money
from .order.models import Order
from .pricing import price_line


def money_view(m: Money) -> dict:
    return {"amount": m.amount, "currency": m.currency, "display": m.format()}


def order_view(order: Order, view: CatalogView) -> dict:
    lines = []
    for ln in order.lines:
        unit, line_total, description = price_line(
            view, ln.item_id, ln.variant_id, ln.quantity, ln.modifier_ids
        )
        lines.append(
            {
                "line_id": ln.line_id,
                "item_id": ln.item_id,
                "variant_id": ln.variant_id,
                "quantity": ln.quantity,
                "modifier_ids": ln.modifier_ids,
                "description": description,
                "unit_price": money_view(unit),
                "line_total": money_view(line_total),
            }
        )
    out = {
        "order_id": order.id,
        "tenant_id": order.tenant_id,
        "currency": order.currency,
        "revision": order.revision,
        "status": order.status.value,
        "lines": lines,
        "pos_order_id": order.pos_order_id,
        "quote": quote_view(order) if order.quote else None,
        "confirmation": (
            {
                "confirmation_id": order.confirmation.confirmation_id,
                "revision": order.confirmation.revision,
                "challenge": order.confirmation.challenge,
                "bound_to_current_revision": order.confirmation.revision == order.revision,
            }
            if order.confirmation
            else None
        ),
    }
    return out


def quote_view(order: Order) -> dict | None:
    q = order.quote
    if q is None:
        return None
    return {
        "quote_id": q.quote_id,
        "revision": q.revision,
        "is_current": q.revision == order.revision,
        "expires_at": q.expires_at.isoformat(),
        "lines": [
            {
                "line_id": ql.line_id,
                "description": ql.description,
                "quantity": ql.quantity,
                "unit_price": money_view(ql.unit_price),
                "line_total": money_view(ql.line_total),
            }
            for ql in q.lines
        ],
        "subtotal": money_view(q.subtotal),
        "tax": money_view(q.tax),
        "total": money_view(q.total),
    }


def menu_view(catalog: Catalog) -> dict:
    return {
        "tenant_id": catalog.tenant_id,
        "name": catalog.name,
        "currency": catalog.currency,
        "tax_rate_bps": catalog.tax_rate_bps,
        "modifier_groups": [g.model_dump() for g in catalog.modifier_groups],
        "items": [i.model_dump() for i in catalog.items],
    }
