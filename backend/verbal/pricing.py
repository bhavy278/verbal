"""Deterministic pricing engine. Integer minor units only — no floats."""

from __future__ import annotations

from .catalog.schema import CatalogView
from .money import Money, sum_money
from .order.models import Order, QuoteLine


def _describe_line(view: CatalogView, item_name: str, variant_name: str, modifier_ids: list[str]) -> str:
    parts = [f"{variant_name} {item_name}"]
    mod_names = [view.modifier(mid)[1].name for mid in modifier_ids]
    if mod_names:
        parts.append("(" + ", ".join(mod_names) + ")")
    return " ".join(parts)


def price_line(view: CatalogView, item_id: str, variant_id: str, quantity: int, modifier_ids: list[str]) -> tuple[Money, Money, str]:
    """Return (unit_price, line_total, description) for a single line."""
    item = view.item(item_id)
    variant = view.variant(item, variant_id)
    unit = Money.of(variant.price, view.currency)
    for mid in modifier_ids:
        _, mod = view.modifier(mid)
        unit = unit.add(Money.of(mod.price, view.currency))
    line_total = unit.multiply(quantity)
    description = _describe_line(view, item.name, variant.name, modifier_ids)
    return unit, line_total, description


def price_order(view: CatalogView, order: Order) -> tuple[list[QuoteLine], Money, Money, Money]:
    """Return (quote_lines, subtotal, tax, total) for the whole order."""
    currency = view.currency
    quote_lines: list[QuoteLine] = []
    for ln in order.lines:
        unit, line_total, description = price_line(
            view, ln.item_id, ln.variant_id, ln.quantity, ln.modifier_ids
        )
        quote_lines.append(
            QuoteLine(
                line_id=ln.line_id,
                description=description,
                unit_price=unit,
                quantity=ln.quantity,
                line_total=line_total,
            )
        )
    subtotal = sum_money([q.line_total for q in quote_lines], currency)
    tax = subtotal.tax(view.tax_rate_bps)
    total = subtotal.add(tax)
    return quote_lines, subtotal, tax, total
