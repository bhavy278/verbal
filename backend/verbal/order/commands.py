"""Command DTOs for the order aggregate (validated at the boundary)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AddLine(BaseModel):
    item_id: str
    variant_id: str
    quantity: int = Field(default=1, ge=1)
    modifier_ids: list[str] = Field(default_factory=list)


class SetLineQuantity(BaseModel):
    line_id: str
    quantity: int = Field(ge=0)  # 0 removes the line


class ChangeVariant(BaseModel):
    line_id: str
    variant_id: str


class RemoveLine(BaseModel):
    line_id: str


class ReplaceModifiers(BaseModel):
    line_id: str
    modifier_ids: list[str] = Field(default_factory=list)
