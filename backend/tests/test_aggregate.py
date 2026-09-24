import pytest

from verbal.catalog.loader import load_catalog_from_file
from verbal.catalog.schema import CatalogView
from verbal.order.models import Order, OrderStatus
from verbal.order import aggregate, commands as cmd
from verbal.errors import InvalidModifierComboError, InvalidStateError, LineNotFoundError


def _order():
    view = CatalogView(load_catalog_from_file())
    return Order(tenant_id="pizzahub", currency="USD"), view


def test_add_line_bumps_revision():
    order, view = _order()
    assert order.revision == 0
    aggregate.add_line(order, view, cmd.AddLine(item_id="drink_soda", variant_id="sz_can"))
    assert order.revision == 1
    assert len(order.lines) == 1


def test_set_quantity_zero_removes():
    order, view = _order()
    line = aggregate.add_line(order, view, cmd.AddLine(item_id="drink_soda", variant_id="sz_can"))
    aggregate.set_line_quantity(order, view, cmd.SetLineQuantity(line_id=line.line_id, quantity=0))
    assert order.lines == []


def test_invalid_combo_rejected():
    order, view = _order()
    with pytest.raises(InvalidModifierComboError):
        aggregate.add_line(order, view, cmd.AddLine(
            item_id="pizza_margherita", variant_id="sz_small",
            modifier_ids=["crust_thin", "crust_stuffed", "sauce_tomato"]))


def test_line_not_found():
    order, view = _order()
    with pytest.raises(LineNotFoundError):
        aggregate.remove_line(order, view, cmd.RemoveLine(line_id="nope"))


def test_cannot_edit_submitted():
    order, view = _order()
    aggregate.add_line(order, view, cmd.AddLine(item_id="drink_soda", variant_id="sz_can"))
    order.status = OrderStatus.SUBMITTED
    with pytest.raises(InvalidStateError):
        aggregate.add_line(order, view, cmd.AddLine(item_id="drink_soda", variant_id="sz_can"))
