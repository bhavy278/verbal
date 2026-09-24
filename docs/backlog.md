# Backlog (seed)

## Done — Phase 0
- [x] Docs skeleton, repo layout
- [x] ADR-0001 (FastAPI + Mongo + worker)
- [x] ADR-0002 (voice eval criteria)
- [x] ADR-0003 (Twilio + OpenAI Realtime)
- [x] Pizza menu fixture + catalog schema/validator
- [x] Threat model + constraints

## Done — Phase 1
- [x] Mongo schema + indexes; Money type
- [x] Catalog loader/validator
- [x] Order aggregate + commands (AddLine, SetLineQuantity, ChangeVariant, RemoveLine, ReplaceModifiers)
- [x] Deterministic pricing engine (integer minor units)
- [x] Quote lifecycle + expiration
- [x] Confirmation challenge bound to revision (property-tested)
- [x] Outbox + async worker (lease/TTL) ; fake POS adapter
- [x] Idempotent SubmitOrder (unique index + transaction)
- [x] Text simulator CLI (REPL + scenario runner)
- [x] 12 canonical scenarios (>= 10 required)

## Done — Phase 2 (mock path)
- [x] Voice gateway skeleton (TwiML + Twilio Media WS)
- [x] `VoiceModel` adapter interface + Mock + OpenAI Realtime (dormant/BYOK)
- [x] Orchestrator reusing domain tools (text simulate WS + media bridge)
- [x] Barge-in handling (Twilio `clear` + transcript truncation)
- [x] Call state machine + timers (silence / stall / max duration)
- [x] Call transcript + audio storage

## P0 — Phase 2 remaining (needs credentials / human authorization)
- [ ] Wire real `OPENAI_API_KEY` + Twilio staging number
- [ ] One live staging call completing the canonical scenarios
- [ ] Record p50/p95 first-audio latency; measure barge-in

## P1 — Phase 3
- [ ] Staff console UI (React + TS)
- [ ] Real POS integration (replace sandbox adapter)
- [ ] Promote reconciliation stub → full reconciliation loop + dashboard
- [ ] Retention/redaction policy for call audio + transcripts

## P2 — Phases 4-8
- [ ] Stitched pipeline (Deepgram STT + LLM + ElevenLabs TTS) provider
- [ ] Gemini Live provider
- [ ] Multi-tenant platform (exercise tenant fields, per-tenant catalogs/billing)
- [ ] Menu authoring tooling
