from __future__ import annotations
import json
import time
from pathlib import Path
from pydantic import BaseModel


class BudgetExceeded(RuntimeError):
    pass


class UsageTracker(BaseModel):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0

    def can_call(self, max_calls: int, max_usd: float) -> bool:
        return self.calls < max_calls and self.estimated_cost_usd < max_usd

    def record(
        self, input_tokens: int, output_tokens: int, input_rate: float, output_rate: float
    ) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.estimated_cost_usd += (
            input_tokens * input_rate + output_tokens * output_rate
        ) / 1_000_000


class TelemetryWriter:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, state: dict, plan: dict, execution: list[dict], metrics: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": time.time(),
                        "state": state,
                        "plan": plan,
                        "execution": execution,
                        "metrics": metrics,
                    },
                    default=str,
                )
                + "\n"
            )
