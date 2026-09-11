from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from .schemas import ActionType, Plan, ScreenPoint, VisualState


class _ParameterlessAction(BaseModel):
    type: Literal[
        ActionType.TRAIN_VILLAGER,
        ActionType.BUILD_HOUSE,
        ActionType.BUILD_LUMBER_CAMP,
        ActionType.SELECT_IDLE_VILLAGER,
        ActionType.SELECT_TOWN_CENTER,
        ActionType.RESEARCH_FEUDAL,
        ActionType.WAIT,
        ActionType.NO_OP,
    ]
    count: None = None
    direction: None = None
    target: None = None


class _BuildAction(BaseModel):
    type: Literal[ActionType.BUILD_HOUSE, ActionType.BUILD_LUMBER_CAMP]
    count: None = None
    direction: None = None
    target: ScreenPoint


class _AssignmentAction(BaseModel):
    type: Literal[
        ActionType.ASSIGN_TO_FOOD,
        ActionType.ASSIGN_TO_WOOD,
        ActionType.ASSIGN_TO_GOLD,
    ]
    count: int | None = Field(default=None, ge=1, le=20)
    direction: None = None
    target: ScreenPoint


class _ScoutAction(BaseModel):
    type: Literal[ActionType.SCOUT_DIRECTION]
    count: None = None
    direction: Literal["north", "south", "east", "west"]
    target: None = None


_OutputAction = _ParameterlessAction | _BuildAction | _AssignmentAction | _ScoutAction


class _PlanOutput(BaseModel):
    goal: str = Field(min_length=1, max_length=200)
    observed_state: VisualState
    actions: list[_OutputAction] = Field(max_length=4)
    recheck_after_seconds: float = Field(ge=0.5, le=5)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


class StructuredAgentClient:
    def __init__(self, model: str, max_output_tokens: int):
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.client = OpenAI()

    def request(self, system: str, text: str, image_url: str | None) -> tuple[Plan, Usage]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
        if image_url:
            content.append({"type": "input_image", "image_url": image_url})
        response = self.client.responses.parse(
            model=self.model,
            max_output_tokens=self.max_output_tokens,
            input=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            text_format=_PlanOutput,
            store=False,
        )
        if response.output_parsed is None:
            details = [f"status={response.status}"]
            incomplete = getattr(response, "incomplete_details", None)
            if incomplete is not None:
                details.append(f"reason={incomplete.reason}")
            error = getattr(response, "error", None)
            if error is not None:
                details.append(f"error={error.code}: {error.message}")
            details.append(f"max_output_tokens={self.max_output_tokens}")
            raise ValueError("strategist returned no validated plan (" + ", ".join(details) + ")")
        usage = getattr(response, "usage", None)
        plan = Plan.model_validate(response.output_parsed.model_dump())
        return plan, Usage(getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
