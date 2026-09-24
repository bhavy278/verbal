# Verbal — AI Voice Phone Ordering Agent

Server-authoritative backend for taking restaurant orders by phone. A caller
speaks to an AI agent; the agent may only **invoke domain tools** and **read
back server-computed numbers**. It never computes prices, availability, or
acceptance.

## Phases
- **Phase 0** — Discovery, contracts, threat model, fixtures. *(this repo)*
- **Phase 1** — Deterministic domain core + text simulator. *(this repo — DONE)*
- **Phase 2** — Real voice loop (Twilio + STT/LLM/TTS) reusing the same tools.
  *(this repo — mock path DONE; OpenAI Realtime adapter dormant/BYOK)*
- **Phase 3-8** — Staff console UI, real POS, reconciliation dashboards,
  multi-tenant platform. *(backlogged — see `backlog.md`)*

## Repo layout
```
backend/
  server.py                 FastAPI app (HTTP API + voice gateway)
  verbal/
    money.py                Money type (integer minor units + currency)
    config.py               env-backed settings
    db.py                   Mongo client, indexes, txn helper, doc<->model
    errors.py               coded domain errors
    pricing.py              deterministic pricing engine
    quote.py                quote lifecycle + confirmation challenge
    submit.py               idempotent SubmitOrder (outbox, in a txn)
    worker.py               async outbox worker + reconciliation stub
    service.py              domain tool facade (reused by CLI, API, voice)
    views.py                server-authoritative response views
    catalog/                catalog schema, loader, pizza fixture
    order/                  aggregate + commands + models
    pos/                    fake/sandbox POS adapter
    voice/                  Phase 2: tools, adapters, orchestrator, gateway
    simulator/              text simulator CLI + canonical scenarios
  tests/                    pytest units + property test + scenario integration
docs/                       ADRs, threat model, contracts, backlog
```

## Run
```bash
# MongoDB must run as a replica set (single-node RS is fine for dev).
python -m verbal.simulator.cli seed-catalog
python -m verbal.simulator.cli run-scenarios     # >=10 canonical scenarios
python -m verbal.simulator.cli repl              # interactive ordering
python -m verbal.worker                          # outbox worker (separate proc)
pytest                                            # units + integration
```

## Exit gates
- **Phase 1:** vertical slice runs end-to-end in the simulator; duplicate submit
  ⇒ exactly one accepted order; lost-response scenario reconciles. ✅
- **Phase 2:** real staging call completes simulator scenarios; p50/p95 latency
  and barge-in measured. *(pending live Twilio/OpenAI credentials)*
