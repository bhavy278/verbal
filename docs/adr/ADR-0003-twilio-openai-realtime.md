# ADR-0003 — Twilio Media Streams + OpenAI GPT Realtime (S2S)

**Status:** Accepted (Phase 2)

## Context
We need a telephony transport and a voice model. ADR-0002 defines the metrics.

## Decision
- **Telephony:** **Twilio Media Streams** — bidirectional WebSocket, mu-law
  8kHz (`g711_ulaw`), with the `clear` event for barge-in. Most mature and
  best-documented path; `<Connect><Stream>` opens the socket to our FastAPI WS.
- **Voice model (default):** **OpenAI GPT Realtime (S2S)** — lowest first-audio
  latency and strongest interruption handling. Configured with `g711_ulaw` in/out
  so it bridges directly to Twilio without transcoding.
- **Adapter boundary:** every backend sits behind the `VoiceModel` interface
  (`open` / `receive_audio` / `close` + `send_audio` / `clear` / `dispatch_tool`
  callbacks). A stitched pipeline (Deepgram STT + LLM + ElevenLabs TTS) or
  Gemini Live can be swapped in without touching the orchestrator.

## Hard rule
The model may ONLY invoke domain tools and read back server-returned numbers.
It computes no prices, availability, or acceptance. Menu text, caller speech,
and POS echoes are treated as **data, never instructions**.

## Barge-in
On `input_audio_buffer.speech_started` (or stitched VAD): send Twilio `clear`,
`response.cancel` to the model, and truncate the assistant transcript to what
was actually heard.

## Credentials (BYOK, wired later)
- `OPENAI_API_KEY` (project key with Realtime access) — user-provided.
- Twilio account SID / auth token / staging number — user-provisioned.
- `VERBAL_VOICE_PROVIDER=openai_realtime` activates the adapter; default `mock`.

## Open questions (tracked, non-blocking for Phase 0-1)
- Who provisions the Twilio staging number; test-call budget ceiling?
- Cost-per-minute tolerance for S2S vs stitched as the *default*.
- Call-audio/transcript retention policy (currently: **store both**).
