# PRD — Verbal: AI Voice Phone Ordering Agent

## Original problem statement
Web-based backend service (no consumer/staff UI in scope). Phase 0 = discovery,
contracts, threat model, fixtures. Phase 1 = deterministic domain core + text
simulator. Phase 2 = real voice loop (Twilio + STT/LLM/TTS) reusing the same
domain tools. POS is a fake/sandbox adapter throughout. Server-authoritative
order aggregate; deterministic integer-money pricing; quote lifecycle with
expiration; confirmation bound to revision (edits invalidate it); idempotent
SubmitOrder via outbox → fake POS (duplicate submit ⇒ exactly one accepted);
lost POS ack reconciles. Stack: FastAPI + MongoDB replica set + separate outbox
worker; pytest; Twilio + OpenAI Realtime behind an adapter interface.

## User choices (this session)
- Deliver Phase 0 + 1 fully; Phase 2 behind adapters with a MOCK voice model +
  fake WS (real Twilio/OpenAI wired later, BYOK OpenAI key).
- Store both call audio + transcript.
- CLI = interactive REPL + scripted scenario runner.

## Architecture
- **Backend** `/app/backend/verbal/`: `money`, `catalog/`, `order/` (aggregate,
  commands, models), `pricing`, `quote`, `submit`, `worker`, `pos/`, `service`
  (tool facade), `views`, `voice/` (tools, adapters, orchestrator, gateway,
  call_state, transcript_store), `simulator/` (cli, scenarios), `api/routes`.
- **DB**: MongoDB single-node replica set `rs0` (transactions). Unique index on
  `(tenant_id, idempotency_key)` = duplicate guard. Every collection tenant-scoped.
- **Worker**: separate supervisor process `verbal-worker` (lease/TTL outbox drain
  + reconciliation stub).
- **Frontend** `/app/frontend/src/App.js`: dark "Voice Ordering Console" (call
  simulator chat + live order ticket + menu). Full Phase 3 staff console deferred.

## User personas
- Restaurant callers (Phase 2 voice end users).
- Operators/devs driving the text simulator (this phase).
- Staff (future Phase 3 console).

## Core requirements (static)
- Server authority over all prices/availability/acceptance; model reads back only.
- Integer minor-unit money; no floats.
- Revision-bound confirmation; edits invalidate.
- Idempotent submit ⇒ exactly one accepted order; lost ack reconciles.
- Tenant isolation invariant; untrusted inputs treated as data.

## Implemented (2026-06)
- ✅ Phase 0: docs skeleton, ADR-0001/0002/0003, pizza fixture + catalog schema,
  threat model, backlog, discovery, contracts.
- ✅ Phase 1: Mongo schema/indexes, Money, catalog loader/validator, order
  aggregate + 5 commands, deterministic pricing, quote lifecycle + expiration,
  revision-bound confirmation (property-tested), outbox + async worker, fake POS,
  idempotent SubmitOrder, text simulator CLI (REPL + runner), 12 canonical
  scenarios. Exit gate met: vertical slice E2E; duplicate submit ⇒ one accepted;
  lost-response reconciles.
- ✅ Phase 2 (mock path): TwiML + Twilio Media WS gateway, `VoiceModel` adapter
  interface + Mock + dormant OpenAI Realtime (BYOK), orchestrator reusing domain
  tools, barge-in (Twilio `clear` + transcript truncation), call state machine +
  timers, call transcript + audio storage, text simulate WS/REST.
- ✅ Frontend developer console (call simulator + live order + menu).
- ✅ 65 pytest tests + 12/12 scenarios; testing agent: backend 100%, frontend 100%.

## Backlog (prioritized)
- **P0 (Phase 2 live, needs human authorization + credentials):** wire real
  `OPENAI_API_KEY` + Twilio staging number; one live staging call completing the
  canonical scenarios; record p50/p95 first-audio latency; measure barge-in.
- **P1 (Phase 3):** staff console UI; real POS integration; promote
  reconciliation stub → full loop + dashboard; call audio/transcript retention
  & redaction policy.
- **P2 (Phases 4-8):** stitched pipeline provider (Deepgram + LLM + ElevenLabs);
  Gemini Live provider; multi-tenant platform; menu authoring tooling.

## Next tasks
1. Collect OpenAI Realtime + Twilio credentials (Bhavy authorizes); set
   `VERBAL_VOICE_PROVIDER=openai_realtime`.
2. Provision Twilio staging number + point voice webhook at `/api/voice/twiml`.
3. Run one live staging call; capture latency + barge-in metrics (ADR-0002).
