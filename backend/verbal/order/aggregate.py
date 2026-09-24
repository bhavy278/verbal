"""Order aggregate: pure command handlers.

These functions contain no I/O. They take an :class:`Order` plus a
:class:`CatalogView` and mutate the order in place, enforcing invariants and
bumping the revision. Persistence is the caller's concern.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..catalog.schema import CatalogView
from ..errors import InvalidStateError, InvalidQuantityError, LineNotFoundError
from . import commands as cmd
from .models import Order, OrderLine, OrderStatus

_EDITABLE = {OrderStatus.DRAFT, OrderStatus.QUOTED, OrderStatus.CONFIRMED}


def _require_editable(order: Order) -> None:
    if order.status not in _EDITABLE:
        raise InvalidStateError(
            f"Cannot edit an order in status '{order.status.value}'"
        )


def _touch(order: Order) -> None:
    """Bump revision, drop any confirmation, mark the order back to draft.

    Any edit invalidates an outstanding confirmation (and makes any existing
    quote stale by revision mismatch).
    """
    order.revision += 1
    order.confirmation = None
    order.status = OrderStatus.DRAFT
    order.updated_at = datetime.now(timezone.utc)


def _require_line(order: Order, line_id: str) -> OrderLine:
    line = order.line(line_id)
    if line is None:
        raise LineNotFoundError(f"No line '{line_id}' on order")
    return line


def add_line(order: Order, view: CatalogView, command: cmd.AddLine) -> OrderLine:
    _require_editable(order)
    if command.quantity < 1:
        raise InvalidQuantityError("Quantity must be at least 1")
    view.validate_selection(view.item(command.item_id), command.variant_id, command.modifier_ids)
    line = OrderLine(
        item_id=command.item_id,
        variant_id=command.variant_id,
        quantity=command.quantity,
        modifier_ids=list(command.modifier_ids),
    )
    order.lines.append(line)
    _touch(order)
    return line


def set_line_quantity(order: Order, view: CatalogView, command: cmd.SetLineQuantity) -> None:
    _require_editable(order)
    line = _require_line(order, command.line_id)
    if command.quantity == 0:
        order.lines = [ln for ln in order.lines if ln.line_id != command.line_id]
    else:
        line.quantity = command.quantity
    _touch(order)


def change_variant(order: Order, view: CatalogView, command: cmd.ChangeVariant) -> None:
    _require_editable(order)
    line = _require_line(order, command.line_id)
    item = view.item(line.item_id)
    view.validate_selection(item, command.variant_id, line.modifier_ids)
    line.variant_id = command.variant_id
    _touch(order)


def remove_line(order: Order, view: CatalogView, command: cmd.RemoveLine) -> None:
    _require_editable(order)
    _require_line(order, command.line_id)
    order.lines = [ln for ln in order.lines if ln.line_id != command.line_id]
    _touch(order)


def replace_modifiers(order: Order, view: CatalogView, command: cmd.ReplaceModifiers) -> None:
    _require_editable(order)
    line = _require_line(order, command.line_id)
    item = view.item(line.item_id)
    view.validate_selection(item, line.variant_id, command.modifier_ids)
    line.modifier_ids = list(command.modifier_ids)
    _touch(order)
