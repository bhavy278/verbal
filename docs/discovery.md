# Discovery notes

## Problem
Restaurants miss phone orders at peak times. Verbal answers the phone, takes the
order conversationally, and submits it to the POS — with the **server** (not the
language model) in authority over every price and every acceptance.

## Users
- **Callers** — place orders by phone (Phase 2 end users).
- **Operators/devs** — drive the text simulator and observe behaviour (this phase).
- **Staff** — future consumers of a console UI (Phase 3).

## Constraints
- Single tenant / single restaurant this phase (multi-tenant fields present, not exercised).
- English-only pilot menu (pizza).
- Mongo as a replica set (transactions).
- Human authorization required for anything touching Twilio, secrets, or live calls.

## Success criteria
- Phase 1 vertical slice runs end-to-end in the simulator.
- Duplicate submit ⇒ one accepted order; lost-response reconciles.
- Phase 2 staging call completes the canonical scenarios with measured latency
  and working barge-in.
