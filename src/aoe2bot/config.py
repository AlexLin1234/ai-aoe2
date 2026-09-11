from __future__ import annotations
from pathlib import Path
from typing import Any
import os
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class WindowConfig(BaseModel):
    title_contains: str
    process_names: list[str] = Field(default_factory=lambda: ["AoE2DE_s.exe"])
    focus_before_input: bool = True


class CaptureConfig(BaseModel):
    max_width_for_agent: int = 1280
    jpeg_quality: int = 78
    regions: dict[str, dict[str, float]] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    enabled: bool = True
    model: str
    default_recheck_seconds: float = 10
    max_calls_per_game: int = 200
    max_output_tokens: int = 300
    max_actions_per_plan: int = 4
    include_full_screenshot: bool = True
    input_usd_per_million_tokens: float = 0
    output_usd_per_million_tokens: float = 0


class BudgetConfig(BaseModel):
    max_usd_per_game: float = 3


class SafetyConfig(BaseModel):
    emergency_stop_hotkey: str = "f12"
    pause_resume_hotkey: str = "f11"
    duplicate_cooldown_seconds: float = 4
    max_events_per_second: int = 8
    action_timeout_seconds: float = 3
    max_actions_per_cycle: int = 4


class InputConfig(BaseModel):
    live_enabled: bool = False
    key_interval_seconds: float = 0.06


class CalibrationConfig(BaseModel):
    house_position: tuple[int, int]
    lumber_camp_position: tuple[int, int]
    food_position: tuple[int, int]
    wood_position: tuple[int, int]
    gold_position: tuple[int, int]


class BenchmarkConfig(BaseModel):
    name: str = "reach_feudal"
    max_town_center_idle_seconds: float = 120
    max_population_cap_seconds: float = 90


class TelemetryConfig(BaseModel):
    path: str = "logs/session.jsonl"


class AppConfig(BaseModel):
    window: WindowConfig
    capture: CaptureConfig
    agent: AgentConfig
    budget: BudgetConfig
    safety: SafetyConfig
    input: InputConfig
    calibration: CalibrationConfig
    benchmark: BenchmarkConfig
    telemetry: TelemetryConfig


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_config(path: str | Path | None = None) -> AppConfig:
    load_dotenv()
    return AppConfig.model_validate(
        load_yaml(path or os.getenv("ASTRA_CONFIG", "config/default.yaml"))
    )
