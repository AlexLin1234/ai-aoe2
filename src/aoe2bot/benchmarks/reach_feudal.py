from __future__ import annotations
from dataclasses import dataclass
from aoe2bot.perception.state import GameState


@dataclass
class ReachFeudalBenchmark:
    started_at: float
    population_cap_incidents: int = 0
    feudal_at: float | None = None
    _was_capped: bool = False
    name: str = "reach_feudal"
    objective: str = "Reach Feudal Age reliably while producing villagers, avoiding population cap, and developing food and wood income."

    def observe(self, state: GameState) -> None:
        capped = (
            state.population_current is not None
            and state.population_cap is not None
            and state.population_current >= state.population_cap
        )
        if capped and not self._was_capped:
            self.population_cap_incidents += 1
        self._was_capped = capped
        if state.age and state.age.lower() not in {"dark", "dark age"} and self.feudal_at is None:
            self.feudal_at = state.timestamp

    def complete(self, state: GameState) -> bool:
        return self.feudal_at is not None

    def metrics(self) -> dict:
        return {
            "game_time_to_feudal": None
            if self.feudal_at is None
            else self.feudal_at - self.started_at,
            "population_cap_incidents": self.population_cap_incidents,
        }
