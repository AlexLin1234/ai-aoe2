from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field

from aoe2bot.capture.screenshot import ScreenshotCapture, agent_jpeg_data_url
from aoe2bot.capture.window import TargetWindow, WindowManager
from aoe2bot.config import EndGameConfig
from aoe2bot.control.input import InputDriver

log = logging.getLogger(__name__)


class StatObservation(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    player_value: str | None = None
    comparison_value: str | None = None
    assessment: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0, le=1)


class GameReview(BaseModel):
    result: Literal["win", "loss", "unknown"]
    map_name: str | None = None
    player_civilization: str | None = None
    opponent_civilizations: list[str] = Field(max_length=8)
    game_duration: str | None = None
    summary: str = Field(min_length=1, max_length=800)
    metrics: list[StatObservation] = Field(max_length=24)
    strengths: list[str] = Field(max_length=6)
    weaknesses: list[str] = Field(max_length=6)
    priority_improvements: list[str] = Field(min_length=1, max_length=6)
    next_game_plan: list[str] = Field(min_length=1, max_length=6)
    long_term_trends: list[str] = Field(max_length=6)


END_GAME_SYSTEM_PROMPT = """You analyze Age of Empires II post-game statistics screenshots. Read every supplied graph or statistics page carefully. Extract only values and comparisons that are visibly supported; use null or state uncertainty when text is unreadable. Diagnose the few decisions that most affected the result, give concrete practice priorities for the next game, and compare against the supplied prior-game memory when present. Keep advice specific and concise. Never claim a metric that is not visible in the images or prior records."""


class EndGameAnalyzer:
    def __init__(self, config: EndGameConfig, api: Any | None = None):
        self.config = config
        self.api = api or OpenAI()

    def analyze(
        self, frames: dict[str, Image.Image], previous_reviews: list[dict[str, Any]]
    ) -> GameReview:
        history = json.dumps(previous_reviews[-self.config.max_previous_games :], default=str)
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    "Analyze the labeled post-game pages. Player to evaluate: "
                    f"{self.config.player_name or 'infer the local player from visible UI context'}. "
                    "Previous game memory, oldest to newest: " + history
                ),
            }
        ]
        for label, frame in frames.items():
            content.append({"type": "input_text", "text": f"Post-game page: {label}"})
            content.append(
                {
                    "type": "input_image",
                    "image_url": agent_jpeg_data_url(
                        frame, self.config.max_image_width, self.config.jpeg_quality
                    ),
                }
            )
        response = self.api.responses.parse(
            model=self.config.model,
            max_output_tokens=self.config.max_output_tokens,
            input=[
                {"role": "system", "content": END_GAME_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            text_format=GameReview,
            store=False,
        )
        if response.output_parsed is None:
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            raise ValueError(
                f"end-game analysis returned no review (status={response.status}, reason={reason})"
            )
        return response.output_parsed


class MemoryBank:
    def __init__(self, memory_path: str | Path, overview_path: str | Path):
        self.memory_path = Path(memory_path)
        self.overview_path = Path(overview_path)

    def load(self, limit: int | None = None) -> list[dict[str, Any]]:
        if limit == 0:
            return []
        if not self.memory_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.memory_path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("skipping malformed memory-bank line")
        return entries[-limit:] if limit is not None else entries

    def record(self, review: GameReview) -> dict[str, Any]:
        entry = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "review": review.model_dump(mode="json"),
        }
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        with self.memory_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self._write_overview(self.load())
        return entry

    def _write_overview(self, entries: list[dict[str, Any]]) -> None:
        latest = entries[-1]
        review = latest["review"]
        lines = [
            "# AoE2 Improvement Memory Bank",
            "",
            f"Updated: {latest['recorded_at']}",
            f"Games reviewed: {len(entries)}",
            "",
            "## Current focus",
            "",
        ]
        lines.extend(f"- {item}" for item in review["priority_improvements"])
        lines.extend(["", "## Next-game plan", ""])
        lines.extend(f"- {item}" for item in review["next_game_plan"])
        lines.extend(["", "## Long-term trends", ""])
        trends = review["long_term_trends"] or ["No recurring trend established yet."]
        lines.extend(f"- {item}" for item in trends)
        lines.extend(
            [
                "",
                "## Latest game",
                "",
                f"- Result: {review['result']}",
                f"- Civilization: {review['player_civilization'] or 'unknown'}",
                f"- Map: {review['map_name'] or 'unknown'}",
                f"- Duration: {review['game_duration'] or 'unknown'}",
                "",
                review["summary"],
                "",
                "## Latest strengths",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in review["strengths"])
        lines.extend(["", "## Latest weaknesses", ""])
        lines.extend(f"- {item}" for item in review["weaknesses"])
        lines.extend(["", "## Latest observed statistics", ""])
        if review["metrics"]:
            for metric in review["metrics"]:
                player_value = metric["player_value"] or "unreadable"
                comparison = (
                    f"; comparison: {metric['comparison_value']}"
                    if metric["comparison_value"]
                    else ""
                )
                confidence = round(metric["confidence"] * 100)
                lines.append(
                    f"- **{metric['name']}**: {player_value}{comparison}. "
                    f"{metric['assessment']} ({confidence}% confidence)"
                )
        else:
            lines.append("- No graph value was readable with enough confidence.")
        lines.append("")
        self.overview_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.overview_path.with_suffix(self.overview_path.suffix + ".tmp")
        temporary.write_text("\n".join(lines), encoding="utf-8")
        temporary.replace(self.overview_path)


class EndGameReviewService:
    def __init__(
        self,
        config: EndGameConfig,
        windows: WindowManager,
        capture: ScreenshotCapture,
        driver: InputDriver,
        analyzer: EndGameAnalyzer | None = None,
        sleeper: Any = time.sleep,
    ):
        self.config = config
        self.windows = windows
        self.capture = capture
        self.driver = driver
        self.analyzer = analyzer or EndGameAnalyzer(config)
        self.sleep = sleeper
        self.bank = MemoryBank(config.memory_path, config.overview_path)

    def _prepare(self) -> TargetWindow:
        target = self.windows.require()
        if not self.windows.is_foreground(target):
            self.windows.focus(target)
        if not self.windows.is_foreground(target):
            raise RuntimeError("could not focus AoE2 statistics window")
        self.driver.set_allowed_bounds(target.rect)
        return target

    def collect(self, initial_frame: Image.Image | None = None) -> dict[str, Image.Image]:
        target = self.windows.require()
        frames = {"current": initial_frame or self.capture.capture(target)}
        if self.config.graph_tabs and not self.driver.live:
            log.warning("graph-tab capture skipped because input is not live")
            return frames
        for label, (normalized_x, normalized_y) in self.config.graph_tabs.items():
            if not (0 <= normalized_x <= 1 and 0 <= normalized_y <= 1):
                raise ValueError(f"end-game tab {label!r} must use normalized coordinates")
            target = self._prepare()
            left, top, right, bottom = target.rect
            x = left + int((right - left) * normalized_x)
            y = top + int((bottom - top) * normalized_y)
            self.driver.click(x, y)
            self.sleep(self.config.tab_settle_seconds)
            frames[label] = self.capture.capture(self.windows.require())
        return frames

    def run(self, initial_frame: Image.Image | None = None) -> GameReview:
        frames = self.collect(initial_frame)
        prior_entries = self.bank.load(self.config.max_previous_games)
        prior_reviews = [entry["review"] for entry in prior_entries if "review" in entry]
        review = self.analyzer.analyze(frames, prior_reviews)
        self.bank.record(review)
        log.info("end-game review saved to %s", self.config.overview_path)
        return review
