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

    def should_end_for_duration(self) -> bool:
        return self.call_duration() >= self.max_call_seconds

    def should_prompt_for_silence(self) -> bool:
        return self.silence_duration() >= self.silence_timeout_seconds

    def end(self) -> None:
        self.transition(CallState.ENDED)
