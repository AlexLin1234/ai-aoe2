from __future__ import annotations

import argparse
import os

from aoe2bot.agent.planner import Planner
from aoe2bot.capture.screenshot import ScreenshotCapture
from aoe2bot.capture.window import WindowManager
from aoe2bot.config import load_config
from aoe2bot.control.executor import ActionExecutor
from aoe2bot.control.hotkeys import load_hotkeys
from aoe2bot.control.input import InputDriver
from aoe2bot.endgame import EndGameReviewService
from aoe2bot.perception.heuristics import StateReader
from aoe2bot.runtime.hotkey_monitor import EmergencyHotkeyMonitor
from aoe2bot.runtime.loop import BotLoop
from aoe2bot.runtime.safety import SafetyController
from aoe2bot.runtime.telemetry import TelemetryWriter
from aoe2bot.utils.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Astra AoE2 semantic controller")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument(
        "--analyze-end-game",
        action="store_true",
        help="capture the visible post-game statistics and update the memory bank",
    )
    parser.add_argument("--config", default=os.getenv("ASTRA_CONFIG", "config/default.yaml"))
    parser.add_argument("--hotkeys", default=os.getenv("ASTRA_HOTKEYS", "config/hotkeys.yaml"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    c = load_config(args.config)
    needs_live_input = bool(args.live or (args.analyze_end_game and c.end_game.graph_tabs))
    if needs_live_input and not c.input.live_enabled:
        parser.error("live input also requires input.live_enabled: true in config")
    live = bool(args.live or (args.analyze_end_game and c.end_game.graph_tabs))
    windows = WindowManager(c.window.title_contains, c.window.process_names)
    capture = ScreenshotCapture()
    driver = InputDriver(live, c.safety.max_events_per_second, c.input.key_interval_seconds)

    end_game_review = (
        EndGameReviewService(c.end_game, windows, capture, driver)
        if c.end_game.enabled or args.analyze_end_game
        else None
    )
    if args.analyze_end_game:
        assert end_game_review is not None
        review = end_game_review.run()
        print(f"Recorded {review.result} review in {c.end_game.memory_path}")
        print(f"Updated improvement overview at {c.end_game.overview_path}")
        return

    def preflight() -> None:
        target = windows.require()
        if not windows.is_foreground(target):
            if not c.window.focus_before_input:
                raise RuntimeError("AoE2 is not foreground")
            windows.focus(target)
        if not windows.is_foreground(target):
            raise RuntimeError("could not focus positively identified AoE2 window")
        driver.set_allowed_bounds(target.rect)

    safety = SafetyController(c.safety.max_actions_per_cycle, c.safety.duplicate_cooldown_seconds)
    monitor = EmergencyHotkeyMonitor(
        c.safety.emergency_stop_hotkey,
        c.safety.pause_resume_hotkey,
        safety.emergency_stop,
        safety.toggle_pause,
    )
    monitor.start()
    executor = ActionExecutor(
        driver,
        load_hotkeys(args.hotkeys),
        c.calibration,
        preflight,
        c.safety.action_timeout_seconds,
    )
    BotLoop(
        c,
        windows,
        capture,
        StateReader(),
        Planner(
            c.agent,
            max_image_width=c.capture.max_width_for_agent,
            image_quality=c.capture.jpeg_quality,
        ),
        executor,
        safety,
        TelemetryWriter(c.telemetry.path),
        end_game_review.run if end_game_review else None,
    ).run(args.once)


if __name__ == "__main__":
    main()
