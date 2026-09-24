"""Verbal backend API tests - Phase 0/1/2 vertical slice + edge cases + voice sim.

Covers:
- Health / Menu
- Full HTTP vertical slice (start -> lines -> modify -> quote -> readback ->
  confirmation -> confirm -> submit -> worker delivery -> accepted)
- Idempotent duplicate submit
- Stale/edit-after-confirmation invalidation
- Domain error codes (invalid_modifier_combo, item_not_found, empty_order)
- Voice text-simulator REST flow
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

def _load_base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        # read /app/frontend/.env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    if not v:
        raise RuntimeError("REACT_APP_BACKEND_URL not set")
    return v.rstrip("/")


BASE = _load_base()
HEADERS = {"User-Agent": "Mozilla/5.0 pytest", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def s() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(HEADERS)
    return sess


# ---------- helpers ----------
def _pizza_line_body(variant="sz_large", qty=1, extra_toppings=None):
    mods = ["crust_classic", "sauce_tomato"] + (extra_toppings or ["top_pepperoni"])
    return {
        "item_id": "pizza_pepperoni",
        "variant_id": variant,
        "quantity": qty,
        "modifier_ids": mods,
    }


def _wait_for_accepted(s, order_id, timeout=8.0):
    """Poll GET /orders/{id} until pos_order_id exists or timeout. Also force worker tick."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = s.get(f"{BASE}/api/orders/{order_id}")
        last = r.json()
        if last.get("pos_order_id") and last.get("status") == "accepted":
            return last
        # nudge the worker
        s.post(f"{BASE}/api/worker/tick", json={})
        time.sleep(0.4)
    return last


# ---------- health / menu ----------
class TestHealthAndMenu:
    def test_health_ok(self, s):
        r = s.get(f"{BASE}/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "verbal"

    def test_menu_structure(self, s):
        r = s.get(f"{BASE}/api/menu")
        assert r.status_code == 200
        m = r.json()
        assert m["tenant_id"] == "pizzahub"
        assert m["currency"] == "USD"
        assert isinstance(m["tax_rate_bps"], int)
        item_ids = [i["id"] for i in m["items"]]
        assert "pizza_pepperoni" in item_ids
        assert "drink_soda" in item_ids
        pep = next(i for i in m["items"] if i["id"] == "pizza_pepperoni")
        # prices minor units
        for v in pep["variants"]:
            assert isinstance(v["price"], int)
        group_ids = [g["id"] for g in m["modifier_groups"]]
        for gid in ("grp_crust", "grp_sauce", "grp_toppings"):
            assert gid in group_ids


# ---------- vertical slice ----------
class TestVerticalSlice:
    def test_full_flow_accepted(self, s):
        # start
        r = s.post(f"{BASE}/api/orders", json={})
        assert r.status_code == 200, r.text
        order = r.json()
        oid = order["order_id"]
        assert order["status"] == "draft"

        # add pizza line
        r = s.post(f"{BASE}/api/orders/{oid}/lines", json=_pizza_line_body("sz_medium"))
        assert r.status_code == 200, r.text
        line = r.json()["line"] if "line" in r.json() else r.json()
        # find line id from GET order
        odoc = s.get(f"{BASE}/api/orders/{oid}").json()
        assert len(odoc["lines"]) == 1
        lid = odoc["lines"][0]["line_id"]

        # resize variant
        r = s.patch(f"{BASE}/api/orders/{oid}/lines/{lid}/variant",
                    json={"variant_id": "sz_large"})
        assert r.status_code == 200, r.text

        # swap modifiers (crust+sauce+different topping)
        r = s.put(f"{BASE}/api/orders/{oid}/lines/{lid}/modifiers",
                  json={"modifier_ids": ["crust_classic", "sauce_tomato", "top_extra_cheese"]})
        assert r.status_code == 200, r.text

        # change qty
        r = s.patch(f"{BASE}/api/orders/{oid}/lines/{lid}/quantity", json={"quantity": 2})
        assert r.status_code == 200, r.text

        # add soda
        r = s.post(f"{BASE}/api/orders/{oid}/lines", json={
            "item_id": "drink_soda", "variant_id": "sz_can", "quantity": 1, "modifier_ids": []
        })
        assert r.status_code == 200, r.text

        # quote
        r = s.post(f"{BASE}/api/orders/{oid}/quote", json={})
        assert r.status_code == 200, r.text
        q = r.json()
        # status quoted (either at top-level order or inside quote)
        odoc = s.get(f"{BASE}/api/orders/{oid}").json()
        assert odoc["status"] == "quoted"
        # totals
        # totals - nested in q["quote"] as Money objects with .amount
        qq = q["quote"] if "quote" in q else q
        subtotal = qq["subtotal"]["amount"]
        tax = qq["tax"]["amount"]
        total = qq["total"]["amount"]
        assert isinstance(subtotal, int) and isinstance(tax, int) and isinstance(total, int)
        assert total == subtotal + tax

        # readback
        r = s.get(f"{BASE}/api/orders/{oid}/readback")
        assert r.status_code == 200
        rb = r.json()
        text = rb.get("text") or rb.get("readback") or ""
        assert "total" in text.lower() or "$" in text

        # confirmation
        r = s.post(f"{BASE}/api/orders/{oid}/confirmation", json={})
        assert r.status_code == 200, r.text
        c = r.json()
        cid = c["confirmation_id"]
        assert "challenge" in c

        # confirm
        r = s.post(f"{BASE}/api/orders/{oid}/confirm", json={"confirmation_id": cid})
        assert r.status_code == 200, r.text
        odoc = s.get(f"{BASE}/api/orders/{oid}").json()
        assert odoc["status"] == "confirmed"

        # submit
        idem = f"idem-{uuid.uuid4()}"
        r = s.post(f"{BASE}/api/orders/{oid}/submit", json={"idempotency_key": idem})
        assert r.status_code == 200, r.text
        sub = r.json()
        assert sub.get("status") in ("submitted", "accepted")

        # wait for worker
        final = _wait_for_accepted(s, oid, timeout=10)
        assert final["status"] == "accepted", f"final={final}"
        assert final.get("pos_order_id"), f"no pos_order_id: {final}"


# ---------- idempotent duplicate submit ----------
class TestIdempotentSubmit:
    def test_duplicate_submit_same_key(self, s):
        oid = _make_confirmed_order(s)
        idem = f"idem-{uuid.uuid4()}"
        r1 = s.post(f"{BASE}/api/orders/{oid}/submit", json={"idempotency_key": idem})
        assert r1.status_code == 200, r1.text
        r2 = s.post(f"{BASE}/api/orders/{oid}/submit", json={"idempotency_key": idem})
        assert r2.status_code == 200, r2.text
        # let worker deliver
        final = _wait_for_accepted(s, oid, timeout=10)
        assert final["status"] == "accepted"
        pos_id = final.get("pos_order_id")
        assert pos_id

        # outbox: at most one non-failed message for this order (exactly one submission)
        ob = s.get(f"{BASE}/api/outbox").json()
        msgs = [m for m in ob["messages"] if m["order_id"] == oid]
        assert len(msgs) == 1, f"expected 1 outbox msg got {msgs}"
        assert msgs[0]["pos_order_id"] == pos_id


# ---------- stale after edit ----------
class TestStaleAfterEdit:
    def test_edit_invalidates_confirmation(self, s):
        oid = _make_confirmed_order(s)
        # get line id
        odoc = s.get(f"{BASE}/api/orders/{oid}").json()
        lid = odoc["lines"][0]["line_id"]

        # edit -> quantity change should drop confirmation
        r = s.patch(f"{BASE}/api/orders/{oid}/lines/{lid}/quantity", json={"quantity": 3})
        assert r.status_code == 200, r.text
        odoc = s.get(f"{BASE}/api/orders/{oid}").json()
        assert odoc["status"] == "draft", f"expected draft got {odoc['status']}"

        # submit should fail 422 not_confirmed
        r = s.post(f"{BASE}/api/orders/{oid}/submit",
                   json={"idempotency_key": f"idem-{uuid.uuid4()}"})
        assert r.status_code == 422, r.text
        body = r.json()
        assert body.get("error") == "not_confirmed", body

        # re-quote / re-confirm / re-submit works
        assert s.post(f"{BASE}/api/orders/{oid}/quote", json={}).status_code == 200
        c = s.post(f"{BASE}/api/orders/{oid}/confirmation", json={}).json()
        assert s.post(f"{BASE}/api/orders/{oid}/confirm",
                      json={"confirmation_id": c["confirmation_id"]}).status_code == 200
        r = s.post(f"{BASE}/api/orders/{oid}/submit",
                   json={"idempotency_key": f"idem-{uuid.uuid4()}"})
        assert r.status_code == 200, r.text


# ---------- error cases ----------
class TestDomainErrors:
    def test_invalid_modifier_combo_two_crusts(self, s):
        oid = s.post(f"{BASE}/api/orders", json={}).json()["order_id"]
        r = s.post(f"{BASE}/api/orders/{oid}/lines", json={
            "item_id": "pizza_pepperoni",
            "variant_id": "sz_large",
            "quantity": 1,
            "modifier_ids": ["crust_thin", "crust_stuffed", "sauce_tomato"],
        })
        assert r.status_code == 422, r.text
        assert r.json().get("error") == "invalid_modifier_combo"

    def test_missing_required_crust_sauce(self, s):
        oid = s.post(f"{BASE}/api/orders", json={}).json()["order_id"]
        r = s.post(f"{BASE}/api/orders/{oid}/lines", json={
            "item_id": "pizza_pepperoni",
            "variant_id": "sz_large",
            "quantity": 1,
            "modifier_ids": [],  # no crust or sauce
        })
        assert r.status_code == 422, r.text
        assert r.json().get("error") == "invalid_modifier_combo"

    def test_unknown_item(self, s):
        oid = s.post(f"{BASE}/api/orders", json={}).json()["order_id"]
        r = s.post(f"{BASE}/api/orders/{oid}/lines", json={
            "item_id": "pizza_unicorn",
            "variant_id": "sz_large",
            "quantity": 1,
            "modifier_ids": [],
        })
        assert r.status_code == 422, r.text
        assert r.json().get("error") == "item_not_found"

    def test_empty_order_quote(self, s):
        oid = s.post(f"{BASE}/api/orders", json={}).json()["order_id"]
        r = s.post(f"{BASE}/api/orders/{oid}/quote", json={})
        assert r.status_code == 422, r.text
        assert r.json().get("error") == "empty_order"


# ---------- voice text simulator ----------
class TestVoiceSimulator:
    def test_voice_flow(self, s):
        # Pin to the deterministic mock agent so the test is free + reliable
        # regardless of whether an LLM key is configured.
        r = s.post(f"{BASE}/api/voice/simulate/start", json={"agent": "mock"})
        assert r.status_code == 200, r.text
        start = r.json()
        assert "call_sid" in start and "reply" in start
        sid = start["call_sid"]

        turns = [
            "I would like a large pepperoni pizza with extra cheese",
            "make that two",
            "and a can of soda",
            "what's my total",
            "yes place the order",
        ]
        last = None
        for t in turns:
            r = s.post(f"{BASE}/api/voice/simulate/turn",
                       json={"call_sid": sid, "text": t})
            assert r.status_code == 200, r.text
            body = r.json()
            assert "reply" in body
            assert "tool_calls" in body
            last = body
            time.sleep(0.2)

        # final turn: submit invoked
        tool_names = [tc.get("name") or tc.get("tool") for tc in (last.get("tool_calls") or [])]
        # Sometimes submit lands in the last turn as SubmitOrder; be permissive
        assert any("submit" in (n or "").lower() for n in tool_names), \
            f"expected submit tool call, got {tool_names}"

        # call transcript
        r = s.get(f"{BASE}/api/voice/calls/{sid}")
        assert r.status_code == 200, r.text
        call = r.json()
        transcript = call.get("transcript") or call.get("turns") or []
        assert len(transcript) >= 5, f"transcript too short: {len(transcript)}"
        assert call.get("order_id"), f"missing linked order_id: {call}"


# ---------- caller-ID verification (Twilio trial) ----------
class TestCallerVerification:
    def test_verified_callers_readonly(self, s):
        r = s.get(f"{BASE}/api/voice/verified-callers")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("twilio_credentials") is True, body
        assert isinstance(body.get("verified"), list), body

    @pytest.mark.parametrize("phone", ["12345", "555-1234", "notaphone", "", "+0"])
    def test_verify_caller_invalid_phone(self, s, phone):
        r = s.post(f"{BASE}/api/voice/verify-caller", json={"phone_number": phone})
        assert r.status_code == 400, r.text
        assert r.json().get("error") == "invalid_phone"


# ---------- readiness ----------
class TestReadiness:
    def test_readiness_shape(self, s):
        r = s.get(f"{BASE}/api/voice/readiness")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["voice_provider"] == "openai_realtime", body
        assert body["openai_key_present"] is True, body
        assert body["twilio_configured"] is False, body
        assert body["twilio_budget_usd"] == 10.0, body
        assert "call_cost_per_min_usd" in body and body["call_cost_per_min_usd"] is not None
        assert body.get("public_base_url"), body


# ---------- voice simulator: budget object presence ----------
class TestVoiceSimulatorBudget:
    def test_mock_agent_budget_present(self, s):
        r = s.post(f"{BASE}/api/voice/simulate/start", json={"agent": "mock"})
        assert r.status_code == 200, r.text
        start = r.json()
        assert start.get("agent") == "mock-text", start
        sid = start["call_sid"]

        turns = [
            "I would like a large pepperoni pizza with extra cheese",
            "make that two",
            "and a can of soda",
            "what's my total",
            "yes place the order",
        ]
        last = None
        for t in turns:
            r = s.post(
                f"{BASE}/api/voice/simulate/turn",
                json={"call_sid": sid, "text": t},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert "budget" in body, body
            budget = body["budget"]
            assert "estimated_cost_usd" in budget, budget
            assert "cap_usd" in budget, budget
            assert "exceeded" in budget, budget
            last = body
            time.sleep(0.1)

        tool_names = [tc.get("name") or tc.get("tool") for tc in (last.get("tool_calls") or [])]
        assert any("submit" in (n or "").lower() for n in tool_names), tool_names


# ---------- helpers ----------
def _make_confirmed_order(s: requests.Session) -> str:
    oid = s.post(f"{BASE}/api/orders", json={}).json()["order_id"]
    r = s.post(f"{BASE}/api/orders/{oid}/lines", json=_pizza_line_body("sz_medium"))
    assert r.status_code == 200, r.text
    r = s.post(f"{BASE}/api/orders/{oid}/quote", json={})
    assert r.status_code == 200, r.text
    c = s.post(f"{BASE}/api/orders/{oid}/confirmation", json={}).json()
    r = s.post(f"{BASE}/api/orders/{oid}/confirm",
               json={"confirmation_id": c["confirmation_id"]})
    assert r.status_code == 200, r.text
    return oid
