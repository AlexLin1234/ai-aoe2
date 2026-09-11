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
    parser.add_argument("--config", default=os.getenv("ASTRA_CONFIG", "config/default.yaml"))
    parser.add_argument("--hotkeys", default=os.getenv("ASTRA_HOTKEYS", "config/hotkeys.yaml"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    c = load_config(args.config)
    if args.live and not c.input.live_enabled:
        parser.error("--live also requires input.live_enabled: true in config")
    live = bool(args.live)
    windows = WindowManager(c.window.title_contains, c.window.process_names)
    driver = InputDriver(live, c.safety.max_events_per_second, c.input.key_interval_seconds)

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
        ScreenshotCapture(),
        StateReader(),
        Planner(c.agent),
        executor,
        safety,
        TelemetryWriter(c.telemetry.path),
    ).run(args.once)


if __name__ == "__main__":
    main()
