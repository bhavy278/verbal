# Threat model & constraints

## Trust boundaries
| Input | Trust | Handling |
|-------|-------|----------|
| Caller speech / transcript | Untrusted | Data only. Never interpreted as instructions to the server. |
| Menu / catalog fixture | Untrusted-at-load | Validated by Pydantic v2 at load; referential integrity enforced. |
| POS responses / echoes | Untrusted | Parsed as data; acceptance derives from our own POS record, not echoed text. |
| HTTP request bodies | Untrusted | Pydantic v2 validation at the boundary; coded domain errors. |
| Voice-model tool-call args | Untrusted | Validated by the domain layer (item/variant/modifier validator). |

## Key invariants
1. **Server authority:** all prices, availability, tax, totals, and acceptance
   are computed server-side. The model reads them back verbatim.
2. **No prompt injection escalation:** untrusted text can never change control
   flow — the model only selects among fixed tools with validated arguments.
3. **Money safety:** integer minor units only; no floats anywhere in pricing.
4. **Idempotency:** duplicate/retried/crashed submits ⇒ exactly one accepted
   order (unique index on `(tenant_id, idempotency_key)`).
5. **Confirmation binding:** a confirmation is bound to a revision; any edit
   invalidates it (must re-confirm).
6. **Tenant isolation:** every collection carries `tenant_id`; all queries are
   tenant-scoped even though the pilot is single-tenant.

## Abuse / failure cases handled
- Stale quote at confirm → rejected, re-quote.
- Edit after confirmation → confirmation killed.
- Invalid modifier combos → rejected by the validator, not the model.
- Lost POS ack → at-least-once delivery + idempotent POS + reconciliation stub.
- Barge-in / silence / model stall / max call duration → call state machine.

## Secrets & authorization
- All secrets from environment only (`OPENAI_API_KEY`, Twilio creds). None in code.
- Live staging calls, Twilio provisioning, and secrets require explicit human
  authorization (Bhavy).

## Privacy / retention
- Phase 2 stores **both** call audio and transcript (product decision). A formal
  retention/redaction policy is a Phase 3 deliverable.
