from __future__ import annotations
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class ActionType(StrEnum):
    TRAIN_VILLAGER = "TRAIN_VILLAGER"
    BUILD_HOUSE = "BUILD_HOUSE"
    BUILD_LUMBER_CAMP = "BUILD_LUMBER_CAMP"
    ASSIGN_TO_FOOD = "ASSIGN_TO_FOOD"
    ASSIGN_TO_WOOD = "ASSIGN_TO_WOOD"
    ASSIGN_TO_GOLD = "ASSIGN_TO_GOLD"
    SELECT_IDLE_VILLAGER = "SELECT_IDLE_VILLAGER"
    SELECT_TOWN_CENTER = "SELECT_TOWN_CENTER"
    RESEARCH_FEUDAL = "RESEARCH_FEUDAL"
    SCOUT_DIRECTION = "SCOUT_DIRECTION"
    WAIT = "WAIT"
    NO_OP = "NO_OP"


class Action(BaseModel):
    type: ActionType
    count: int | None = Field(default=None, ge=1, le=20)
    direction: Literal["north", "south", "east", "west"] | None = None

    @model_validator(mode="after")
    def parameters_match(self) -> "Action":
        if self.type == ActionType.SCOUT_DIRECTION and self.direction is None:
            raise ValueError("direction required")
        if self.type != ActionType.SCOUT_DIRECTION and self.direction is not None:
            raise ValueError("direction not allowed")
        if self.count is not None and self.type not in {
            ActionType.ASSIGN_TO_FOOD,
            ActionType.ASSIGN_TO_WOOD,
            ActionType.ASSIGN_TO_GOLD,
        }:
            raise ValueError("count not allowed")
        return self


class Plan(BaseModel):
    goal: str = Field(min_length=1, max_length=200)
    actions: list[Action] = Field(max_length=4)
    recheck_after_seconds: float = Field(ge=2, le=60)


class ActionResult(BaseModel):
    action: ActionType
    success: bool
    duration_ms: float = Field(ge=0)
    message: str = ""
