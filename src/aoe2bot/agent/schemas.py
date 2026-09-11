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
    def parameters_match(self) -> Action:
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


class VisualState(BaseModel):
    screen: Literal["gameplay", "paused", "postgame", "menu", "loading", "unknown"] = "unknown"
    confidence: float = Field(default=0, ge=0, le=1)
    age: str | None = None
    population_current: int | None = Field(default=None, ge=0)
    population_cap: int | None = Field(default=None, ge=0)
    food: int | None = Field(default=None, ge=0)
    wood: int | None = Field(default=None, ge=0)
    gold: int | None = Field(default=None, ge=0)
    stone: int | None = Field(default=None, ge=0)
    selected_object: str | None = None
    town_center_visible: bool | None = None
    idle_villager_visible: bool | None = None
    can_train_villager: bool | None = None
    can_research_feudal: bool | None = None
    notes: list[str] = Field(default_factory=list, max_length=4)


class Plan(BaseModel):
    goal: str = Field(min_length=1, max_length=200)
    observed_state: VisualState = Field(default_factory=VisualState)
    actions: list[Action] = Field(max_length=4)
    recheck_after_seconds: float = Field(ge=0.5, le=5)


class ActionResult(BaseModel):
    action: ActionType
    success: bool
    duration_ms: float = Field(ge=0)
    message: str = ""
