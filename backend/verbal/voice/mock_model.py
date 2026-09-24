"""MockTextAgent — deterministic, keyword-driven NLU for the text simulate path.

This is the testable heart of the Phase 2 voice loop without any keys: it maps
caller utterances to the SAME domain tools the real voice model would call, and
speaks back ONLY server-returned numbers. It is intentionally simple and
predictable (no ML), tuned to the pilot pizza menu vocabulary.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

from .. import service
from ..config import get_settings

Dispatch = Callable[[str, dict], Awaitable[dict]]

_WORD_NUM = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_SIZE = {
    "small": "sz_small", "medium": "sz_medium", "large": "sz_large",
    "6": "sz_6pc", "twelve": "sz_12pc", "12": "sz_12pc", "can": "sz_can", "bottle": "sz_bottle",
}
_ITEMS = {
    "margherita": "pizza_margherita", "cheese pizza": "pizza_margherita",
    "pepperoni": "pizza_pepperoni",
    "veggie": "pizza_veggie", "garden": "pizza_veggie", "vegetable": "pizza_veggie",
    "garlic bread": "side_garlic_bread",
    "wings": "side_wings", "wing": "side_wings",
    "soda": "drink_soda", "coke": "drink_soda", "drink": "drink_soda",
}
_TOPPINGS = {
    "extra cheese": "top_extra_cheese", "pepperoni": "top_pepperoni",
    "mushroom": "top_mushrooms", "olive": "top_olives", "onion": "top_onions",
    "pepper": "top_peppers", "sausage": "top_sausage", "bacon": "top_bacon",
    "pineapple": "top_pineapple", "jalapeno": "top_jalapenos",
}
_PIZZA_ITEMS = {"pizza_margherita", "pizza_pepperoni", "pizza_veggie"}


class MockTextAgent:
    name = "mock-text"

    def _num(self, text: str) -> int:
        for w, n in _WORD_NUM.items():
            if re.search(rf"\b{w}\b", text):
                return n
        m = re.search(r"\b(\d+)\b", text)
        if m and m.group(1) not in ("6", "12"):
            return int(m.group(1))
        return 1

    def _size(self, text: str) -> str | None:
        for w, sid in _SIZE.items():
            if re.search(rf"\b{re.escape(w)}\b", text):
                return sid
        return None

    def _item(self, text: str) -> str | None:
        for kw, iid in _ITEMS.items():
            if kw in text:
                return iid
        return None

    def _toppings(self, text: str) -> list[str]:
        found = []
        for kw, mid in _TOPPINGS.items():
            if kw in text and mid not in found:
                found.append(mid)
        return found

    async def handle(self, session: dict, text: str, dispatch: Dispatch) -> dict:
        t = text.lower().strip()
        steps: list[dict] = []

        async def run(name: str, args: dict | None = None):
            result = await dispatch(name, args or {})
            steps.append({"tool": name, "args": args or {}, "result": result})
            return result

        reply = ""

        # menu
        if re.search(r"\b(menu|what do you have|options)\b", t):
            await run("get_menu")
            reply = "We have pizzas (Margherita, Pepperoni, Garden Veggie), wings, garlic bread, and drinks."
            return self._finish(session, steps, reply)

        # confirm / submit
        if re.search(r"\b(yes|confirm|place (the )?order|that's? (all|it)|go ahead|sounds good)\b", t) and session.get("order_id"):
            return await self._confirm_and_submit(session, steps, run)

        # remove
        if re.search(r"\bremove|cancel that|take off\b", t):
            last = session.get("last_line_id")
            if last:
                await run("remove_item", {"line_id": last})
                reply = "Removed that item."
            else:
                reply = "There's nothing to remove yet."
            return self._finish(session, steps, reply)

        # change size on last line
        if re.search(r"\b(make it|change (it )?to|resize)\b", t) and self._size(t) and session.get("last_line_id"):
            await run("change_size", {"line_id": session["last_line_id"], "variant_id": self._size(t)})
            reply = "Updated the size."
            return self._finish(session, steps, reply)

        # set quantity on last line
        if re.search(r"\b(make that|quantity|instead)\b", t) and session.get("last_line_id"):
            qty = self._num(t)
            await run("set_quantity", {"line_id": session["last_line_id"], "quantity": qty})
            reply = f"Set the quantity to {qty}."
            return self._finish(session, steps, reply)

        # add extra toppings to last line
        if re.search(r"\b(add|swap|with|extra)\b", t) and self._toppings(t) and session.get("last_line_id") and not self._item(t):
            iid_line = session.get("last_line_item")
            new_tops = self._toppings(t)
            base = []
            if iid_line in _PIZZA_ITEMS:
                base = ["crust_classic", "sauce_tomato"]
            await run("set_toppings", {"line_id": session["last_line_id"], "modifier_ids": base + new_tops})
            reply = "Updated the toppings."
            return self._finish(session, steps, reply)

        # quote / total
        if re.search(r"\b(quote|total|how much|price|read.?back|repeat)\b", t):
            await run("quote_order")
            rb = await run("read_back")
            reply = rb["readback"] + " Shall I place the order?"
            return self._finish(session, steps, reply)

        # add item
        item_id = self._item(t)
        if item_id:
            if not session.get("order_id"):
                await run("start_order")
            variant = self._size(t) or self._default_variant(item_id)
            scan = t
            for kw, iid in _ITEMS.items():
                if iid == item_id and kw in scan:
                    scan = scan.replace(kw, " ")
            mods = self._default_mods(item_id) + self._toppings(scan)
            qty = self._num(t)
            res = await run("add_item", {"item_id": item_id, "variant_id": variant, "quantity": qty, "modifier_ids": mods})
            line = res["lines"][-1]
            session["last_line_id"] = line["line_id"]
            session["last_line_item"] = item_id
            reply = f"Added {qty} x {line['description']} at {line['line_total']['display']}."
            return self._finish(session, steps, reply)

        # greeting / start
        if re.search(r"\b(hi|hello|hey|order|want)\b", t):
            if not session.get("order_id"):
                await run("start_order")
            reply = "Hi! This is Verbal. What would you like to order today?"
            return self._finish(session, steps, reply)

        reply = "Sorry, I didn't catch that. You can order a pizza, ask for the menu, or say your total."
        return self._finish(session, steps, reply)

    async def _confirm_and_submit(self, session: dict, steps: list, run) -> dict:
        q = await run("quote_order")
        if not q["lines"]:
            return self._finish(session, steps, "Your order is empty. What would you like?")
        conf = await run("request_confirmation")
        await run("confirm_order", {"confirmation_id": conf["confirmation_id"]})
        sub = await run("submit_order")
        pos_id = sub.get("pos_order_id")
        reply = "Your order is confirmed and submitted. " + (
            f"Your confirmation number is {pos_id}." if pos_id
            else "It's being sent to the kitchen now."
        )
        return self._finish(session, steps, reply, status=sub["status"], order=sub)

    def _default_variant(self, item_id: str) -> str:
        return {
            "side_garlic_bread": "sz_one", "side_wings": "sz_6pc", "drink_soda": "sz_can",
        }.get(item_id, "sz_medium")

    def _default_mods(self, item_id: str) -> list[str]:
        if item_id in _PIZZA_ITEMS:
            return ["crust_classic", "sauce_tomato"]
        if item_id == "side_wings":
            return ["wing_buffalo"]
        return []

    def _finish(self, session: dict, steps, reply: str, status: str | None = None, order: dict | None = None) -> dict:
        if order is None:
            for s in reversed(steps):
                res = s.get("result") or {}
                if isinstance(res, dict) and "lines" in res:
                    order = res
                    break
        return {"reply": reply, "steps": steps, "order": order, "status": status or (order or {}).get("status")}
