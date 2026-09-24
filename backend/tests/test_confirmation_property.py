"""Property test: ANY edit after a confirmation invalidates it."""

import random

import pytest

from verbal.catalog.loader import load_catalog_from_file
from verbal.catalog.schema import CatalogView
from verbal.order.models import Order
from verbal.order import aggregate, commands as cmd
from verbal.quote import build_quote, issue_confirmation, accept_confirmation
from verbal.errors import NoConfirmationError, StaleConfirmationError, VerbalError


def _fresh_confirmed_order(view):
    order = Order(tenant_id="pizzahub", currency="USD")
    line = aggregate.add_line(order, view, cmd.AddLine(
        item_id="pizza_margherita", variant_id="sz_medium",
        modifier_ids=["crust_classic", "sauce_tomato"]))
    build_quote(view, order, ttl_seconds=300)
    conf = issue_confirmation(order)
    return order, line, conf


def _random_edit(order, view, line, rng):
    choice = rng.choice(["qty", "variant", "add", "remove", "mods"])
    if choice == "qty":
        aggregate.set_line_quantity(order, view, cmd.SetLineQuantity(line_id=line.line_id, quantity=rng.randint(1, 5)))
    elif choice == "variant":
        aggregate.change_variant(order, view, cmd.ChangeVariant(line_id=line.line_id, variant_id=rng.choice(["sz_small", "sz_large"])))
    elif choice == "add":
        aggregate.add_line(order, view, cmd.AddLine(item_id="drink_soda", variant_id="sz_can"))
    elif choice == "remove":
        aggregate.remove_line(order, view, cmd.RemoveLine(line_id=line.line_id))
    elif choice == "mods":
        aggregate.replace_modifiers(order, view, cmd.ReplaceModifiers(line_id=line.line_id, modifier_ids=["crust_thin", "sauce_bbq", "top_olives"]))


@pytest.mark.parametrize("seed", range(50))
def test_edit_always_invalidates_confirmation(seed):
    view = CatalogView(load_catalog_from_file())
    rng = random.Random(seed)
    order, line, conf = _fresh_confirmed_order(view)
    rev_before = order.revision
    _random_edit(order, view, line, rng)
    assert order.revision > rev_before
    assert order.confirmation is None
    with pytest.raises((NoConfirmationError, StaleConfirmationError, VerbalError)):
        accept_confirmation(order, conf.confirmation_id)


def test_confirmation_accepts_when_unchanged():
    view = CatalogView(load_catalog_from_file())
    order, line, conf = _fresh_confirmed_order(view)
    accept_confirmation(order, conf.confirmation_id)  # no edit -> valid
    assert order.status.value == "confirmed"
