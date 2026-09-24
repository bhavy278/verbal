# Verbal — AI Voice Phone Ordering Agent (Handover)

Server-authoritative restaurant phone-ordering backend. A caller (phone or web
simulator) talks to an AI agent that may ONLY invoke domain tools and read back
server-computed numbers — it never computes prices, availability, or acceptance.

- **Backend:** FastAPI (Python), Pydantic v2, MongoDB (single-node replica set), async outbox worker
- **Order brain (text/console):** OpenAI `gpt-5.4` tool-calling (BYOK) with a deterministic mock fallback
- **Phone voice loop:** Twilio Media Streams ↔ OpenAI GPT Realtime (GA, `audio/pcmu`)
- **Frontend:** React "Voice Ordering Console" (dev tool; full staff console deferred)

---

## 1. Live URLs

| What | URL |
|------|-----|
| App / Console (frontend) | https://voice-order-engine.preview.emergentagent.com |
| API base | https://voice-order-engine.preview.emergentagent.com/api |
| Health | `GET /api/health` |
| Voice readiness | `GET /api/voice/readiness` |
| Twilio Voice number (dial to test) | **+1 442 205 5755** (`+14422055755`) |

---

## 2. Credentials & connections (ALL secrets)

> These are the project owner's own keys, included for AI-to-AI handover. Rotate if leaked.

### backend/.env
```
MONGO_URL="mongodb://localhost:27017"
DB_NAME="test_database"
CORS_ORIGINS="*"

# Domain
VERBAL_TENANT_ID="pizzahub"
VERBAL_QUOTE_TTL_SECONDS="180"

# Order-taker brain: auto -> LLM when OPENAI_API_KEY present, else deterministic mock
VERBAL_ORDER_AGENT="auto"
VERBAL_LLM_MODEL="gpt-5.4"

# Voice provider for the phone path: mock | openai_realtime | stitched
VERBAL_VOICE_PROVIDER="openai_realtime"
VERBAL_OPENAI_REALTIME_MODEL="gpt-realtime"
VERBAL_OPENAI_REALTIME_VOICE="alloy"

# Call storage (both stored per product decision)
VERBAL_STORE_CALL_AUDIO="true"
VERBAL_STORE_CALL_TRANSCRIPT="true"

# Budget guard (blended $/min vs soft cap; polite auto-hangup on breach)
VERBAL_TWILIO_BUDGET_USD="10"
VERBAL_CALL_COST_PER_MIN_USD="0.30"

# Exact public URL Twilio hits (for TwiML wss + signature validation)
PUBLIC_BASE_URL="https://voice-order-engine.preview.emergentagent.com"
# Opt-in strict Twilio signature check (off by default for robust first calls)
# VERBAL_ENFORCE_TWILIO_SIGNATURE="true"

# ---- SECRETS ----
OPENAI_API_KEY="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"
TWILIO_ACCOUNT_SID="AC12304578ceb02fe725b55cc16501a5ef"
TWILIO_AUTH_TOKEN="bd8b7a4f195fbb71a6b1c11281041a5c"
TWILIO_PHONE_NUMBER="+14422055755"
```

### frontend/.env
```
REACT_APP_BACKEND_URL=https://voice-order-engine.preview.emergentagent.com
```

### External accounts
- **OpenAI:** BYOK project key above. Uses `gpt-5.4` (Chat tool-calling for the text/console brain) and `gpt-realtime` (GA Realtime S2S for phone). Same key for both. Realtime GA shape: `session.type="realtime"`, `audio/pcmu`, no `OpenAI-Beta` header.
- **Twilio:** Account `AC12304578...`, upgraded/full, balance ~$18.85. One Voice number `+14422055755` (SID `PN2045f56164ea38b38c32d0687587b5b7`). Its **Voice webhook is set (POST)** to `https://voice-order-engine.preview.emergentagent.com/api/voice/twiml`.

---

## 3. Runtime / services (supervisor)

| Program | Command | Notes |
|---------|---------|-------|
| `backend` | uvicorn `server:app` on `0.0.0.0:8001` | FastAPI; `/api` prefix; hot reload |
| `frontend` | CRA on `:3000` | yarn only (never npm) |
| `mongodb` | `/usr/bin/mongod --bind_ip_all --replSet rs0` | **single-node replica set `rs0`** (required for transactions) |
| `verbal-worker` | `python -m verbal.worker` | separate outbox worker: lease→deliver→done + reconcile stub |

```bash
sudo supervisorctl status
sudo supervisorctl restart backend        # after .env or dependency changes
sudo supervisorctl restart verbal-worker
# Replica set was initialized once with:
#   mongosh --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27017"}]})'
```

Logs: `/var/log/supervisor/backend.*.log`, `/var/log/supervisor/verbal-worker.*.log`

---

## 4. Data model (MongoDB, db `test_database`)

All docs use string `_id` (domain UUID); every collection carries `tenant_id`.

| Collection | Purpose | Key index |
|-----------|---------|-----------|
| `catalogs` | menu (pizza fixture) | `tenant_id` |
| `orders` | order aggregate (revision, status, lines, quote, confirmation) | `tenant_id,status` |
| `submissions` | idempotency records | **unique `(tenant_id, idempotency_key)`** |
| `outbox` | outbox messages (pending/leased/done/dead) | `status,available_at` |
| `pos_orders` | fake/sandbox POS record | **unique `(tenant_id, idempotency_key)`** |
| `calls` | call transcript + audio + end_reason | `tenant_id,call_sid` |

Money = integer minor units + currency (no floats). Order lifecycle:
`draft → quoted → confirmed → submitted → accepted` (any edit → back to draft, revision++, confirmation cleared).

---

## 5. Key API endpoints (prefix `/api`)

Orders: `POST /orders`, `GET /orders/{id}`, `POST /orders/{id}/lines`,
`PATCH .../lines/{lid}/quantity`, `PATCH .../lines/{lid}/variant`,
`DELETE .../lines/{lid}`, `PUT .../lines/{lid}/modifiers`,
`POST .../quote`, `GET .../readback`, `POST .../confirmation`,
`POST .../confirm`, `POST .../submit`.
Ops: `GET /menu`, `GET /orders`, `GET /outbox`, `POST /worker/tick`, `POST /admin/seed`, `GET /health`.
Voice: `GET /voice/readiness`, `GET|POST /voice/twiml`, `WS /voice/media` (Twilio),
`WS /voice/simulate`, `POST /voice/simulate/start` (body `{agent:"mock"|"llm"}`),
`POST /voice/simulate/turn`, `GET /voice/calls/{sid}`,
`GET /voice/verified-callers`, `POST /voice/verify-caller` (`{phone_number, confirm}`).

---

## 6. Voice pipeline (phone)

1. Caller dials **+1 442 205 5755** → Twilio hits `POST /api/voice/twiml`.
2. TwiML returns `<Connect><Stream url="wss://<host>/api/voice/media"/>`.
3. Twilio opens the media WS (mu-law 8kHz). `MediaOrchestrator` bridges it to
   `OpenAIRealtimeVoiceModel` (GA Realtime, `audio/pcmu`).
4. Model calls domain tools (`verbal/voice/tools.py` → `verbal/service.py`);
   server returns authoritative cart/quote; model reads it back.
5. Barge-in: on caller speech, send Twilio `clear` + `response.cancel`, truncate transcript.
6. Budget guard: watchdog ends the call politely + `calls().update(status=completed)` when the $10 cap is hit.

Provider is swappable behind `VoiceModel` (mock / openai_realtime / stitched-TODO).
Text/console path uses the same tools via `LLMOrderAgent` (gpt-5.4) or the mock.

---

## 7. Run / test

```bash
cd /app/backend
python -m verbal.simulator.cli seed-catalog     # load pizza menu
python -m verbal.simulator.cli run-scenarios    # 12 canonical scenarios
python -m verbal.simulator.cli repl             # interactive text ordering
python -m pytest -q                             # 83 tests (units + property + integration)
```
Test creds/notes: `/app/memory/test_credentials.md`. Docs/ADRs: `/app/docs/`.
PRD/backlog: `/app/memory/PRD.md`.

---

## 8. Status & known items

- ✅ Phase 0/1 done; duplicate submit ⇒ one accepted; lost-ack reconciles.
- ✅ LLM order-taker (gpt-5.4) live in console; quote timer + graceful re-quote; budget guard.
- ✅ Twilio number wired; OpenAI Realtime **GA** bridge verified (simulated Twilio media stream returned agent audio, first audio ~0.8-1.0s).
- ✅ Real phone calls working (orders reached POS). **Voice quality pass:** fixed barge-in cancel-spam (only interrupt when agent is speaking; server-VAD handles cancel), 20ms/160-byte audio framing for smooth playback, tuned server-VAD (threshold 0.6, silence 600ms, far_field noise reduction), natural GA voice `marin`, and a warm human persona prompt.
- 🎚️ Voice is configurable via `VERBAL_OPENAI_REALTIME_VOICE` (e.g. `marin`, `cedar`, `alloy`).
- 🔒 To lock the webhook to Twilio: set `VERBAL_ENFORCE_TWILIO_SIGNATURE=true`.
- 💰 Console/simulate turns and live calls consume the OpenAI key (cost per turn/min).
- Tests: 84 passing (`python -m pytest -q`); scenarios 12/12.
