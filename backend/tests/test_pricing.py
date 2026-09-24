from verbal.catalog.loader import load_catalog_from_file
from verbal.catalog.schema import CatalogView
from verbal.order.models import Order
from verbal.order import aggregate, commands as cmd
from verbal.pricing import price_order


def _view():
    return CatalogView(load_catalog_from_file())


def test_price_line_with_modifiers():
    view = _view()
    order = Order(tenant_id="pizzahub", currency="USD")
    # Large margherita (1599) + stuffed crust (200) + extra cheese (150) = 1949, x2
    aggregate.add_line(order, view, cmd.AddLine(
        item_id="pizza_margherita", variant_id="sz_large", quantity=2,
        modifier_ids=["crust_stuffed", "sauce_tomato", "top_extra_cheese"]))
    lines, subtotal, tax, total = price_order(view, order)
    assert lines[0].unit_price.amount == 1949
    assert lines[0].line_total.amount == 3898
    assert subtotal.amount == 3898
    assert tax.amount == round((3898 * 825 + 5000) // 10000)
    assert total.amount == subtotal.amount + tax.amount


def test_deterministic_repeatable():
    view = _view()
    totals = set()
    for _ in range(5):
        order = Order(tenant_id="pizzahub", currency="USD")
        aggregate.add_line(order, view, cmd.AddLine(
            item_id="pizza_pepperoni", variant_id="sz_medium",
            modifier_ids=["crust_thin", "sauce_bbq", "top_bacon", "top_mushrooms"]))
        _, _, _, total = price_order(view, order)
        totals.add(total.amount)
    assert len(totals) == 1  # fully deterministic
