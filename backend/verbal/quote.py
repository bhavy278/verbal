"""Quote lifecycle + confirmation challenge (pure domain logic)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .catalog.schema import CatalogView
from .errors import (
    EmptyOrderError,
    ExpiredQuoteError,
    NoConfirmationError,
    NoQuoteError,
    StaleConfirmationError,
    StaleQuoteError,
)
from .order.models import Confirmation, Order, OrderStatus, Quote
from .pricing import price_order

_WORDS = ["apple", "river", "maple", "cobalt", "harbor", "ember", "sparrow", "lunar"]


def _hold_phrase(quote: Quote, now: datetime) -> str:
    """Human phrase for how long the quoted price is valid."""
    remaining = (quote.expires_at - now).total_seconds()
    minutes = max(1, round(remaining / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return f"This price holds for {minutes} {unit}."


def build_quote(view: CatalogView, order: Order, ttl_seconds: int, now: datetime | None = None) -> Quote:
    """Price the current cart and attach a fresh, revision-bound quote."""
    if not order.lines:
        raise EmptyOrderError("Cannot quote an empty order")
    now = now or datetime.now(timezone.utc)
    lines, subtotal, tax, total = price_order(view, order)
    quote = Quote(
        revision=order.revision,
        currency=view.currency,
        lines=lines,
        subtotal=subtotal,
        tax=tax,
        total=total,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    order.quote = quote
    order.status = OrderStatus.QUOTED
    order.updated_at = now
    return quote


def _valid_quote(order: Order, now: datetime) -> Quote:
    if order.quote is None:
        raise NoQuoteError("No quote on order; please request a quote first")
    if order.quote.revision != order.revision:
        raise StaleQuoteError("Order changed since the quote; please re-quote")
    if order.quote.is_expired(now):
        raise ExpiredQuoteError("Quote expired; please re-quote")
    return order.quote


def readback_text(order: Order, now: datetime | None = None) -> str:
    """Server-authored readback string built only from server numbers."""
    now = now or datetime.now(timezone.utc)
    quote = _valid_quote(order, now)
    parts = ["Here is your order."]
    for ln in quote.lines:
        parts.append(
            f"{ln.quantity} x {ln.description} at {ln.unit_price.format()} each, "
            f"{ln.line_total.format()}."
        )
    parts.append(
        f"Subtotal {quote.subtotal.format()}, tax {quote.tax.format()}, "
        f"total {quote.total.format()}."
    )
    parts.append(_hold_phrase(quote, now))
    return " ".join(parts)


def issue_confirmation(order: Order, now: datetime | None = None, rng: random.Random | None = None) -> Confirmation:
    """Bind a confirmation challenge to the current revision + valid quote."""
    now = now or datetime.now(timezone.utc)
    quote = _valid_quote(order, now)
    rng = rng or random.Random()
    word = rng.choice(_WORDS)
    confirmation = Confirmation(
        revision=order.revision,
        quote_id=quote.quote_id,
        challenge=(
            f"Your total is {quote.total.format()}. {_hold_phrase(quote, now)} "
            f"To place the order, please confirm with the word '{word}'."
        ),
    )
    order.confirmation = confirmation
    order.updated_at = now
    return confirmation


def accept_confirmation(order: Order, confirmation_id: str, now: datetime | None = None) -> None:
    """Validate a caller's confirmation. Any drift => rejected, must re-do."""
    now = now or datetime.now(timezone.utc)
    if order.confirmation is None:
        raise NoConfirmationError("No confirmation is pending")
    if order.confirmation.revision != order.revision:
        raise StaleConfirmationError("Order changed after confirmation; please re-confirm")
    if order.confirmation.confirmation_id != confirmation_id:
        # Bound to the challenge that was actually issued.
        raise StaleConfirmationError("Confirmation does not match the pending challenge")
    # The quote must still be valid at the moment of confirmation.
    _valid_quote(order, now)
    order.status = OrderStatus.CONFIRMED
    order.updated_at = now
