from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class WindowConfig(BaseModel):
    title_contains: str
    process_names: list[str] = Field(default_factory=lambda: ["AoE2DE_s.exe"])
    # The bot never activates the game itself. It acts only while the user has
    # AoE2 in front and waits the moment they click away, so these only control
    # how often it checks and how long `--once` waits to be let in.
    foreground_poll_seconds: float = Field(default=1, ge=0.1, le=10)
    startup_wait_seconds: float = Field(default=20, ge=0, le=300)


class CaptureConfig(BaseModel):
    max_width_for_agent: int = 1280
    jpeg_quality: int = 78
    regions: dict[str, dict[str, float]] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    enabled: bool = True
    model: str
    default_recheck_seconds: float = 1
    max_calls_per_game: int = 200
    max_output_tokens: int = 768
    max_actions_per_plan: int = 4
    include_full_screenshot: bool = True
    min_state_confidence: float = Field(default=0.4, ge=0, le=1)
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
    live_enabled: bool = True
    key_interval_seconds: float = 0.06
    auto_resume: bool = True
    click_delay_seconds: float = Field(default=0.05, ge=0, le=1)


class CalibrationConfig(BaseModel):
    house_position: tuple[float, float]
    lumber_camp_position: tuple[float, float]
    food_position: tuple[float, float]
    wood_position: tuple[float, float]
    gold_position: tuple[float, float]


class BenchmarkConfig(BaseModel):
    name: str = "reach_feudal"
    max_town_center_idle_seconds: float = 120
    max_population_cap_seconds: float = 90


class TelemetryConfig(BaseModel):
    path: str = "logs/session.jsonl"


class EndGameConfig(BaseModel):
    enabled: bool = True
    model: str = "gpt-5-mini"
    player_name: str | None = None
    max_output_tokens: int = 4096
    max_image_width: int = 1600
    jpeg_quality: int = Field(default=85, ge=1, le=95)
    memory_path: str = "memory_bank/games.jsonl"
    overview_path: str = "memory_bank/overview.md"
    max_previous_games: int = Field(default=10, ge=0, le=50)
    tab_settle_seconds: float = Field(default=1, ge=0.25, le=5)
    graph_tabs: dict[str, tuple[float, float]] = Field(default_factory=dict)


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
    end_game: EndGameConfig = Field(default_factory=EndGameConfig)


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_config(path: str | Path | None = None) -> AppConfig:
    load_dotenv()
    return AppConfig.model_validate(
        load_yaml(path or os.getenv("ASTRA_CONFIG", "config/default.yaml"))
    )
