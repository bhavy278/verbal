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
- ✅ Phase 0/1/2 domain core + mock voice loop (see git history / docs).
- ✅ **Smarter Phrasing**: LLM-driven natural-language order-taker
  (`voice/llm_agent.py`, integration lib, model `gpt-5.4`, BYOK OpenAI key)
  behind an agent factory (`voice/order_agent.py`); `auto` mode uses the LLM
  when `OPENAI_API_KEY` is set, else the deterministic mock. The model only
  selects fixed tools and reads back server numbers. Console header + rest
  endpoint `/api/voice/readiness` report the active brain. **Now active (gpt-5.4).**
- ✅ **Quote Timer**: spoken "This price holds for N minutes" in readback +
  confirmation; live countdown in the console; graceful re-quote when the price
  lapses (agent refreshes and re-reads before submitting).
- ✅ **Live Staging Call — one-key-away**: OpenAI Realtime adapter (dormant),
  TwiML `<Connect><Stream>` + Twilio Media WS, Twilio config
  (`TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER`) + `$10` soft budget cap, all
  surfaced via `/api/voice/readiness`.
- ✅ 75 pytest tests + 12/12 scenarios pass; LLM full slice verified to accepted.

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
