"""Media WS test: verify OpenAI Realtime GA bridge returns agent audio.

Simulates a Twilio Media Streams client against wss://<host>/api/voice/media.
PASS = at least one inbound 'media' event from the agent audio path.
"""
import base64
import json
import os
import ssl
import threading
import time

import pytest
import websocket

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://voice-order-engine.preview.emergentagent.com").rstrip("/")
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/voice/media"

MU_LAW_SILENCE_FRAME = base64.b64encode(b"\xff" * 160).decode("ascii")


def test_media_ws_returns_agent_audio():
    ws = websocket.create_connection(WS_URL, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=15)
    inbound_media_count = 0
    other_events = []
    first_audio_at = None
    start_ts = time.time()
    stop_flag = {"stop": False}

    def reader():
        nonlocal inbound_media_count, first_audio_at
        try:
            while not stop_flag["stop"]:
                ws.settimeout(1.5)
                try:
                    msg = ws.recv()
                except websocket.WebSocketTimeoutException:
                    if time.time() - start_ts > 12:
                        return
                    continue
                except Exception:
                    return
                if not msg:
                    continue
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                ev = data.get("event")
                if ev == "media":
                    inbound_media_count += 1
                    if first_audio_at is None:
                        first_audio_at = time.time() - start_ts
                else:
                    other_events.append(ev)
        except Exception:
            return

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # (2) start
    ws.send(json.dumps({"event": "start", "start": {"streamSid": "MZtest", "callSid": "CAtest"}}))

    # (3) ~20 frames of silence spaced ~20ms
    for _ in range(20):
        ws.send(json.dumps({"event": "media", "media": {"payload": MU_LAW_SILENCE_FRAME}}))
        time.sleep(0.02)

    # (4) wait up to ~10s for inbound audio
    deadline = time.time() + 10
    while time.time() < deadline and inbound_media_count == 0:
        time.sleep(0.2)

    # give a little extra collection window
    time.sleep(1.0)

    try:
        ws.send(json.dumps({"event": "stop"}))
    except Exception:
        pass
    stop_flag["stop"] = True
    try:
        ws.close()
    except Exception:
        pass
    t.join(timeout=2)

    print(f"inbound media frames: {inbound_media_count}, first audio at: {first_audio_at}s, other events: {other_events[:20]}")
    assert inbound_media_count >= 1, f"Expected >=1 agent audio frame; got 0. other_events={other_events[:20]}"


if __name__ == "__main__":
    test_media_ws_returns_agent_audio()
    print("PASS")
