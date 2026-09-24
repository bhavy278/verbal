"""Call state machine + timers (model stall / silence / max duration)."""

from __future__ import annotations

import time
from enum import Enum

from ..config import get_settings


class CallState(str, Enum):
    IDLE = "idle"
    GREETING = "greeting"
    LISTENING = "listening"      # caller may speak; agent awaits input
    AGENT_SPEAKING = "agent_speaking"
    THINKING = "thinking"        # tool/model in flight
    CONFIRMING = "confirming"
    SUBMITTING = "submitting"
    ENDED = "ended"


class CallStateMachine:
    def __init__(self) -> None:
        s = get_settings()
        self.state = CallState.IDLE
        self.started_at = time.monotonic()
        self.last_caller_input_at = self.started_at
        self.max_call_seconds = s.max_call_seconds
        self.silence_timeout_seconds = s.silence_timeout_seconds
        self.cost_per_min = s.call_cost_per_min_usd
        self.budget_usd = s.twilio_budget_usd
        self.history: list[str] = []

    def transition(self, to: CallState) -> None:
        self.history.append(f"{self.state.value}->{to.value}")
        self.state = to

    def mark_caller_input(self) -> None:
        self.last_caller_input_at = time.monotonic()

    def call_duration(self) -> float:
        return time.monotonic() - self.started_at

    def silence_duration(self) -> float:
        return time.monotonic() - self.last_caller_input_at

    def estimated_cost_usd(self) -> float:
        return (self.call_duration() / 60.0) * self.cost_per_min

    def budget_exceeded(self) -> bool:
        return self.budget_usd > 0 and self.estimated_cost_usd() >= self.budget_usd

    def should_end_for_duration(self) -> bool:
        return self.call_duration() >= self.max_call_seconds

    def should_prompt_for_silence(self) -> bool:
        return self.silence_duration() >= self.silence_timeout_seconds

    def end(self) -> None:
        self.transition(CallState.ENDED)


BUDGET_CLOSING = (
    "I'm sorry, we've reached the time limit for this call, so I have to wrap up "
    "now. Please call back to finish your order. Thanks for calling, goodbye!"
)
DURATION_CLOSING = (
    "We've reached the maximum call length, so I'll have to let you go. Please "
    "call back to complete your order. Goodbye!"
)
