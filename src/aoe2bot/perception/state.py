from __future__ import annotations
import time
from typing import Any
from pydantic import BaseModel, Field


class EntityObservation(BaseModel):
    kind: str
    owner: str | None = None
    position: tuple[float, float] | None = None
    confidence: float = 1


class GameState(BaseModel):
    timestamp: float = Field(default_factory=time.time)
    age: str | None = None
    population_current: int | None = None
    population_cap: int | None = None
    food: int | None = None
    wood: int | None = None
    gold: int | None = None
    stone: int | None = None
    selected_unit_type: str | None = None
    town_center_visible: bool | None = None
    idle_villager_detected: bool | None = None
    notes: list[str] = Field(default_factory=list)
    known_units: list[EntityObservation] = Field(default_factory=list)
    known_buildings: list[EntityObservation] = Field(default_factory=list)
    map_locations: dict[str, Any] = Field(default_factory=dict)
    resource_locations: list[dict[str, Any]] = Field(default_factory=list)
    army_groups: dict[str, Any] = Field(default_factory=dict)
    enemy_observations: list[dict[str, Any]] = Field(default_factory=list)
    upgrades: set[str] = Field(default_factory=set)
    production_queues: dict[str, list[str]] = Field(default_factory=dict)
    strategic_hypotheses: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    threat_assessments: list[dict[str, Any]] = Field(default_factory=list)
