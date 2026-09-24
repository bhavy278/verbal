"""Catalog schema + a read-optimised view with lookup maps and validation.

Untrusted menu data is validated at this boundary (Pydantic v2) and treated as
data only — never as instructions to the model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from ..errors import (
    CatalogError,
    InvalidModifierComboError,
    ItemNotFoundError,
    ItemUnavailableError,
    ModifierNotFoundError,
    VariantNotFoundError,
)


class ModifierDef(BaseModel):
    id: str
    name: str
    price: int = 0  # minor units, delta added to the line unit price
    available: bool = True


class ModifierGroup(BaseModel):
    id: str
    name: str
    min_select: int = 0
    max_select: int = 1
    required: bool = False
    modifiers: list[ModifierDef]

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.min_select < 0 or self.max_select < self.min_select:
            raise CatalogError(f"Invalid select bounds on group {self.id}")
        return self


class VariantDef(BaseModel):
    id: str
    name: str
    price: int  # absolute minor-unit price for this variant/size
    available: bool = True


class MenuItem(BaseModel):
    id: str
    name: str
    category: str
    variants: list[VariantDef]
    modifier_group_ids: list[str] = Field(default_factory=list)
    available: bool = True

    @model_validator(mode="after")
    def _has_variant(self):
        if not self.variants:
            raise CatalogError(f"Item {self.id} has no variants")
        return self


class Catalog(BaseModel):
    id: str
    tenant_id: str
    name: str
    currency: str
    tax_rate_bps: int = 0
    version: int = 1
    items: list[MenuItem]
    modifier_groups: list[ModifierGroup]

    @model_validator(mode="after")
    def _referential_integrity(self):
        group_ids = {g.id for g in self.modifier_groups}
        for item in self.items:
            for gid in item.modifier_group_ids:
                if gid not in group_ids:
                    raise CatalogError(
                        f"Item {item.id} references unknown modifier group {gid}"
                    )
        return self


class CatalogView:
    """Lookup + validation helper built over a validated :class:`Catalog`."""

    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self._items = {i.id: i for i in catalog.items}
        self._groups = {g.id: g for g in catalog.modifier_groups}
        self._mods: dict[str, tuple[ModifierGroup, ModifierDef]] = {}
        for g in catalog.modifier_groups:
            for m in g.modifiers:
                self._mods[m.id] = (g, m)

    @property
    def currency(self) -> str:
        return self.catalog.currency

    @property
    def tax_rate_bps(self) -> int:
        return self.catalog.tax_rate_bps

    def item(self, item_id: str) -> MenuItem:
        try:
            return self._items[item_id]
        except KeyError:
            raise ItemNotFoundError(f"Unknown item '{item_id}'")

    def variant(self, item: MenuItem, variant_id: str) -> VariantDef:
        for v in item.variants:
            if v.id == variant_id:
                return v
        raise VariantNotFoundError(f"Item '{item.id}' has no variant '{variant_id}'")

    def modifier(self, modifier_id: str) -> tuple[ModifierGroup, ModifierDef]:
        try:
            return self._mods[modifier_id]
        except KeyError:
            raise ModifierNotFoundError(f"Unknown modifier '{modifier_id}'")

    # -- the modifier validator (rejects invalid combos, not the model) --
    def validate_selection(self, item: MenuItem, variant_id: str, modifier_ids: list[str]):
        if not item.available:
            raise ItemUnavailableError(f"'{item.name}' is not available")
        variant = self.variant(item, variant_id)
        if not variant.available:
            raise ItemUnavailableError(f"'{item.name} {variant.name}' is not available")

        allowed_groups = set(item.modifier_group_ids)
        per_group: dict[str, int] = {}
        for mid in modifier_ids:
            group, mod = self.modifier(mid)
            if group.id not in allowed_groups:
                raise InvalidModifierComboError(
                    f"'{mod.name}' does not apply to '{item.name}'"
                )
            if not mod.available:
                raise ItemUnavailableError(f"'{mod.name}' is not available")
            per_group[group.id] = per_group.get(group.id, 0) + 1

        for gid in allowed_groups:
            group = self._groups[gid]
            count = per_group.get(gid, 0)
            if group.required and count < max(group.min_select, 1):
                raise InvalidModifierComboError(
                    f"'{group.name}' requires at least {max(group.min_select, 1)} selection(s)"
                )
            if count < group.min_select:
                raise InvalidModifierComboError(
                    f"'{group.name}' requires at least {group.min_select} selection(s)"
                )
            if count > group.max_select:
                raise InvalidModifierComboError(
                    f"'{group.name}' allows at most {group.max_select} selection(s)"
                )
        return variant
