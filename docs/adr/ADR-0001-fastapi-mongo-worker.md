# ADR-0001 — FastAPI + MongoDB (replica set) + async outbox worker

**Status:** Accepted (Phase 0)

## Context
We need a server-authoritative ordering core that is safe under duplicate and
crashed submits, testable in isolation, and reusable by both a text simulator
and a live voice loop.

## Decision
- **API/runtime:** FastAPI (Python), strict typing, Pydantic v2 validation at
  every external boundary (menus, transcripts, POS echoes, HTTP bodies).
- **Database:** MongoDB running as a **replica set** (single-node RS in dev).
  A replica set is required for multi-document transactions, which we use to
  write the order-state change and the outbox message atomically.
- **Worker:** a separate async process (`python -m verbal.worker`) drains the
  outbox: `enqueue → lease (TTL, atomic findOneAndUpdate) → deliver → done`.
- **Idempotency:** a unique index on `(tenant_id, idempotency_key)` in the
  `submissions` collection is the deterministic guard against duplicates.

## Consequences
- Transactions require an RS; we provision a single-node RS in dev/staging.
- The worker is independently scalable and crash-safe (lease reclaim on TTL).
- Every collection carries `tenant_id`; all queries are tenant-scoped, keeping
  the multi-tenant isolation invariant true even while single-tenant in pilot.

## Alternatives considered
- **Postgres + SKIP LOCKED outbox:** solid, but the team standardised on Mongo
  and the document order aggregate maps cleanly to a single document.
- **In-process background task instead of a worker:** rejected — a crash would
  lose in-flight deliveries and couples API latency to POS latency.
