# ADR-0002 — Voice evaluation criteria

**Status:** Accepted (Phase 0)

## Context
Before choosing a voice stack we fix *how we will judge it*, so the Phase 2
decision is evidence-driven and the staging call has objective exit criteria.

## Metrics
1. **First-audio latency** — time from caller end-of-speech to first agent
   audio frame. Target **p50 < 800ms, p95 < 1500ms**.
2. **Barge-in responsiveness** — time from caller speech onset (while the agent
   is talking) to Twilio `clear` + TTS/LLM cancel. Target **< 300ms**; assistant
   transcript truncated to what was actually heard.
3. **Tool-call correctness** — 100% of prices/availability/acceptance come from
   tool results; **zero** model-authored numbers (audited via transcript +
   tool-call logs).
4. **Task completion rate** — % of calls that reach an accepted order without
   human fallback across the canonical scenarios.
5. **Word error rate (WER)** on the pilot menu vocabulary (sizes, toppings,
   quantities) — informative, not gating.
6. **Cost per minute** — S2S vs stitched; recorded for the go/no-go on default.
7. **Robustness** — behaviour under silence, model stall, and max-call-duration
   timers must degrade gracefully (see call state machine).

## Method
Replay the 12 canonical simulator scenarios over a live staging call; record
p50/p95 for metrics 1-2, audit metric 3 from stored transcripts, and log cost.

## Consequences
Any voice backend must expose enough hooks (audio deltas, speech-started,
function-call events) to measure the above — captured in the `VoiceModel`
adapter contract.
