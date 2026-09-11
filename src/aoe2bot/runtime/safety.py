from __future__ import annotations
import time
from collections.abc import Callable
from aoe2bot.agent.schemas import Action


class SafetyController:
    def __init__(
        self, max_actions: int, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic
    ):
        self.max_actions = max_actions
        self.cooldown = cooldown_seconds
        self.clock = clock
        self.last: dict[str, float] = {}
        self.paused = False
        self.emergency_stopped = False

    def filter(self, actions: list[Action]) -> list[Action]:
        if self.paused or self.emergency_stopped:
            return []
        now = self.clock()
        safe = []
        for action in actions[: self.max_actions]:
            key = action.model_dump_json()
            if key in self.last and now - self.last[key] < self.cooldown:
                continue
            safe.append(action)
            self.last[key] = now
        return safe

    def emergency_stop(self) -> None:
        self.emergency_stopped = True
        self.paused = True

    def toggle_pause(self) -> None:
        if not self.emergency_stopped:
            self.paused = not self.paused
