"""The domain tool surface exposed to the voice model.

The model may ONLY call these tools; it never computes prices, availability, or
acceptance. Each tool delegates to :mod:`verbal.service` and returns the
server-authoritative result. Tool schemas are OpenAI function-calling shaped so
the same list drops straight into the Realtime session config.
"""

from __future__ import annotations

from .. import service
from ..config import get_settings

TOOL_SPECS = [
    {
        "type": "function",
        "name": "get_menu",
        "description": "List available menu items, sizes, and modifiers. Data only.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "start_order",
        "description": "Start a new empty order for the caller.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "add_item",
        "description": "Add a menu item line to the current order.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "variant_id": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 1},
                "modifier_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["item_id", "variant_id"],
        },
    },
    {
        "type": "function",
        "name": "set_quantity",
        "description": "Set the quantity of a line (0 removes it).",
        "parameters": {
            "type": "object",
            "properties": {"line_id": {"type": "string"}, "quantity": {"type": "integer"}},
            "required": ["line_id", "quantity"],
        },
    },
    {
        "type": "function",
        "name": "change_size",
        "description": "Change the size/variant of a line.",
        "parameters": {
            "type": "object",
            "properties": {"line_id": {"type": "string"}, "variant_id": {"type": "string"}},
            "required": ["line_id", "variant_id"],
        },
    },
    {
        "type": "function",
        "name": "remove_item",
        "description": "Remove a line from the order.",
        "parameters": {
            "type": "object",
            "properties": {"line_id": {"type": "string"}},
            "required": ["line_id"],
        },
    },
    {
        "type": "function",
        "name": "set_toppings",
        "description": "Replace the modifiers/toppings on a line.",
        "parameters": {
            "type": "object",
            "properties": {
                "line_id": {"type": "string"},
                "modifier_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["line_id", "modifier_ids"],
        },
    },
    {
        "type": "function",
        "name": "quote_order",
        "description": "Compute an authoritative priced quote for the current order.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "read_back",
        "description": "Get the server-authored readback text to speak to the caller.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "request_confirmation",
        "description": "Issue a confirmation challenge bound to the current order revision.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "confirm_order",
        "description": "Accept the pending confirmation challenge.",
        "parameters": {
            "type": "object",
            "properties": {"confirmation_id": {"type": "string"}},
            "required": ["confirmation_id"],
        },
    },
    {
        "type": "function",
        "name": "submit_order",
        "description": "Submit the confirmed order to the POS (idempotent).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]

TOOL_NAMES = [t["name"] for t in TOOL_SPECS]


async def dispatch(session: dict, name: str, args: dict) -> dict:
    """Execute a tool call. ``session`` holds mutable per-call state (order_id).

    Untrusted args are passed as data only; the domain layer validates them.
    """
    args = args or {}
    tenant_id = session.get("tenant_id") or get_settings().default_tenant_id

    if name == "get_menu":
        return await service.menu(tenant_id)

    if name == "start_order":
        result = await service.start_order(tenant_id)
        session["order_id"] = result["order_id"]
        return result

    order_id = session.get("order_id")
    if order_id is None and name not in ("get_menu",):
        # Auto-start so the model can't get wedged.
        result = await service.start_order(tenant_id)
        session["order_id"] = order_id = result["order_id"]

    if name == "add_item":
        return await service.add_line(
            order_id, args["item_id"], args["variant_id"], args.get("quantity", 1), args.get("modifier_ids", [])
        )
    if name == "set_quantity":
        return await service.set_line_quantity(order_id, args["line_id"], args["quantity"])
    if name == "change_size":
        return await service.change_variant(order_id, args["line_id"], args["variant_id"])
    if name == "remove_item":
        return await service.remove_line(order_id, args["line_id"])
    if name == "set_toppings":
        return await service.replace_modifiers(order_id, args["line_id"], args["modifier_ids"])
    if name == "quote_order":
        return await service.create_quote(order_id)
    if name == "read_back":
        return await service.get_readback(order_id)
    if name == "request_confirmation":
        result = await service.issue_confirmation(order_id)
        session["confirmation_id"] = result["confirmation_id"]
        return result
    if name == "confirm_order":
        cid = args.get("confirmation_id") or session.get("confirmation_id")
        return await service.confirm(order_id, cid)
    if name == "submit_order":
        # Idempotency key derived from the order so any retry yields one order.
        return await service.submit_order(order_id, idempotency_key=f"submit:{order_id}")

    raise ValueError(f"Unknown tool '{name}'")
