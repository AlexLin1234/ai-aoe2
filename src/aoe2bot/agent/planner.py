from __future__ import annotations
import json
from PIL import Image
from pydantic import ValidationError
from aoe2bot.config import AgentConfig
from aoe2bot.perception.state import GameState
from aoe2bot.capture.screenshot import agent_jpeg_data_url
from .client import StructuredAgentClient, Usage
from .prompt import SYSTEM_PROMPT
from .schemas import Action, ActionType, Plan


class PlannerError(RuntimeError):
    pass


class Planner:
    def __init__(self, config: AgentConfig, client: StructuredAgentClient | None = None):
        self.config = config
        self.client = client

    @staticmethod
    def parse(raw: str) -> Plan:
        try:
            return Plan.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            raise PlannerError("invalid strategist plan") from exc

    def create_plan(
        self, state: GameState, screenshot: Image.Image, recent_history: list[dict], objective: str
    ) -> tuple[Plan, Usage]:
        if not self.config.enabled:
            return Plan(
                goal="Dry local observation",
                actions=[Action(type=ActionType.WAIT)],
                recheck_after_seconds=self.config.default_recheck_seconds,
            ), Usage()
        if self.client is None:
            self.client = StructuredAgentClient(self.config.model, self.config.max_output_tokens)
        payload = json.dumps(
            {
                "objective": objective,
                "state": state.model_dump(mode="json"),
                "recent_history": recent_history[-8:],
            },
            separators=(",", ":"),
        )
        image = (
            agent_jpeg_data_url(screenshot, self.config.max_output_tokens * 4, 78)
            if self.config.include_full_screenshot
            else None
        )
        try:
            return self.client.request(SYSTEM_PROMPT, payload, image)
        except (ValidationError, ValueError) as exc:
            raise PlannerError("invalid strategist plan") from exc
