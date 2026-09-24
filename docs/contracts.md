# Domain tool contracts

The single tool surface reused by the CLI, the HTTP API, and the voice
orchestrator (`verbal/voice/tools.py` → `verbal/service.py`). Every tool returns
**server-authoritative** data. The model computes nothing.

| Tool | Purpose | Key result fields |
|------|---------|-------------------|
| `get_menu` | List items/sizes/modifiers (data only) | `items`, `modifier_groups` |
| `start_order` | New empty order | `order_id`, `revision`, `status` |
| `add_item` | Add a line (validated) | `lines[]`, `revision` |
| `set_quantity` | Set line qty (0 removes) | `lines[]`, `revision` |
| `change_size` | Change variant | `lines[]`, `revision` |
| `remove_item` | Remove a line | `lines[]`, `revision` |
| `set_toppings` | Replace modifiers | `lines[]`, `revision` |
| `quote_order` | Price the cart | `quote.subtotal/tax/total`, `revision` |
| `read_back` | Server-authored readback text | `readback` |
| `request_confirmation` | Issue revision-bound challenge | `confirmation_id`, `challenge` |
| `confirm_order` | Accept the challenge | `status=confirmed` |
| `submit_order` | Idempotent submit → outbox → POS | `status`, `pos_order_id` |

## Order lifecycle (status)
```
draft → quoted → confirmed → submitted → accepted
                                       ↘ failed (after max retries)
any edit → back to draft (revision++, confirmation cleared)
```

## Money
`{ "amount": <int minor units>, "currency": "USD", "display": "$41.10" }`

## Errors (coded, stable)
`item_not_found`, `variant_not_found`, `modifier_not_found`,
`invalid_modifier_combo`, `item_unavailable`, `line_not_found`, `order_not_found`,
`invalid_quantity`, `empty_order`, `no_quote`, `stale_quote`, `expired_quote`,
`no_confirmation`, `stale_confirmation`, `not_confirmed`, `invalid_state`,
`currency_mismatch`.

## Idempotency
`submit_order` uses an idempotency key (`submit:<order_id>` from the voice path).
A unique index on `(tenant_id, idempotency_key)` guarantees exactly one accepted
order across any number of retries.

## HTTP endpoints (prefix `/api`)
Orders: `POST /orders`, `GET /orders/{id}`, `POST /orders/{id}/lines`,
`PATCH …/lines/{lid}/quantity`, `PATCH …/lines/{lid}/variant`,
`DELETE …/lines/{lid}`, `PUT …/lines/{lid}/modifiers`,
`POST …/quote`, `GET …/readback`, `POST …/confirmation`, `POST …/confirm`,
`POST …/submit`. Ops: `GET /menu`, `GET /orders`, `GET /outbox`,
`POST /worker/tick`, `POST /admin/seed`, `GET /health`.
Voice: `GET|POST /voice/twiml`, `WS /voice/media`, `WS /voice/simulate`,
`POST /voice/simulate/start`, `POST /voice/simulate/turn`, `GET /voice/calls/{sid}`.
