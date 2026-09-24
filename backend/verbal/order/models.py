"""Order aggregate domain models.

The :class:`Order` is server-authoritative. Every mutating command bumps
``revision`` and invalidates any outstanding confirmation, so a confirmation is
always bound to the exact cart state the caller heard read back.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from ..money import Money


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OrderStatus(str, Enum):
    DRAFT = "draft"
    QUOTED = "quoted"
    CONFIRMED = "confirmed"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class OrderLine(BaseModel):
    line_id: str = Field(default_factory=_uuid)
    item_id: str
    variant_id: str
    quantity: int = 1
    modifier_ids: list[str] = Field(default_factory=list)


class QuoteLine(BaseModel):
    line_id: str
    description: str
    unit_price: Money
    quantity: int
    line_total: Money


class Quote(BaseModel):
    quote_id: str = Field(default_factory=_uuid)
    revision: int
    currency: str
    lines: list[QuoteLine]
    subtotal: Money
    tax: Money
    total: Money
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or _now()
        return now >= self.expires_at


class Confirmation(BaseModel):
    confirmation_id: str = Field(default_factory=_uuid)
    revision: int          # the revision this confirmation is bound to
    quote_id: str
    challenge: str         # spoken phrase the caller must affirm
    created_at: datetime = Field(default_factory=_now)


class Order(BaseModel):
    id: str = Field(default_factory=_uuid)
    tenant_id: str
    currency: str
    revision: int = 0
    status: OrderStatus = OrderStatus.DRAFT
    lines: list[OrderLine] = Field(default_factory=list)
    quote: Quote | None = None
    confirmation: Confirmation | None = None
    idempotency_key: str | None = None
    pos_order_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def line(self, line_id: str) -> OrderLine | None:
        for ln in self.lines:
            if ln.line_id == line_id:
                return ln
        return None
