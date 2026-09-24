"""Catalog loader/validator + persistence."""

from __future__ import annotations

import json
from pathlib import Path

from .. import db
from ..errors import CatalogError
from .schema import Catalog, CatalogView

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "pizza_menu.json"


def load_catalog_from_file(path: Path | str = FIXTURE_PATH) -> Catalog:
    """Parse + validate a catalog fixture. Raises on any schema violation."""
    raw = json.loads(Path(path).read_text())
    try:
        return Catalog.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise CatalogError(f"Invalid catalog fixture: {exc}") from exc


async def seed_catalog(catalog: Catalog | None = None) -> Catalog:
    """Upsert a catalog into Mongo (idempotent)."""
    catalog = catalog or load_catalog_from_file()
    await db.catalogs().replace_one({"_id": catalog.id}, db.dump_doc(catalog), upsert=True)
    return catalog


async def get_catalog(tenant_id: str) -> Catalog:
    doc = await db.catalogs().find_one({"tenant_id": tenant_id})
    if not doc:
        raise CatalogError(f"No catalog for tenant '{tenant_id}'")
    return db.load_doc(Catalog, doc)


async def get_catalog_view(tenant_id: str) -> CatalogView:
    return CatalogView(await get_catalog(tenant_id))
