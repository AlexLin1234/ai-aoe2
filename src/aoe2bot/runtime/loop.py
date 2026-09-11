from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PIL import Image

from aoe2bot.agent.planner import Planner, PlannerError
from aoe2bot.agent.schemas import Action, ActionType, Plan
from aoe2bot.benchmarks.reach_feudal import ReachFeudalBenchmark
from aoe2bot.capture.screenshot import ScreenshotCapture
from aoe2bot.capture.window import TargetWindow, WindowManager, WindowNotForegroundError
from aoe2bot.config import AppConfig
from aoe2bot.control.executor import ActionExecutor
from aoe2bot.perception.heuristics import StateReader

from .safety import SafetyController
from .telemetry import TelemetryWriter, UsageTracker

log = logging.getLogger(__name__)


def executable_actions(plan: Plan, min_confidence: float) -> list[Action]:
    state = plan.observed_state
    if state.screen != "gameplay" or state.confidence < min_confidence:
        return [Action(type=ActionType.WAIT)]
    return plan.actions


class BotLoop:
    def __init__(
        self,
        config: AppConfig,
        windows: WindowManager,
        capture: ScreenshotCapture,
        reader: StateReader,
        planner: Planner,
        executor: ActionExecutor,
        safety: SafetyController,
        telemetry: TelemetryWriter,
        end_game_review: Callable[[Image.Image], object] | None = None,
    ):
        self.c = config
        self.windows = windows
        self.capture = capture
        self.reader = reader
        self.planner = planner
        self.executor = executor
        self.safety = safety
        self.telemetry = telemetry
        self.end_game_review = end_game_review
        self.usage = UsageTracker()
        self.history: list[dict] = []
        self.waiting_for_user = False

    def _acquire_target(self) -> TargetWindow | None:
        """The game window while the user has it in front, else None to skip.

        The bot has no way to bring AoE2 forward, by design. Control is handed
        over when the user clicks into the game and handed straight back when
        they click away, so switching windows is never a crash or a fight.
        """
        target = self.windows.require()  # disappearing window is a hard kill switch
        if not self.executor.driver.live:
            return target
        if self.windows.is_foreground(target):
            if self.waiting_for_user:
                log.info("AoE2 is in front again; resuming control")
                self.waiting_for_user = False
            return self.windows.refresh(target)
        if not self.waiting_for_user:
            log.info("waiting for AoE2 to be in front; click into the game to hand over control")
            self.waiting_for_user = True
        return None

    def _auto_resume(self, plan: Plan) -> dict[str, object] | None:
        if (
            not self.executor.driver.live
            or not self.c.input.auto_resume
            or self.safety.paused
            # Both, because the in-match pause overlay is titled "Main Menu" and
            # the model labels it menu as often as paused. The cost is that
            # Escape also lands while the user browses menus outside a match.
            or plan.observed_state.screen not in {"paused", "menu"}
        ):
            return None
        started = time.monotonic()
        try:
            self.executor.preflight()
            # Escape, not the unit Stop command: this dismisses a pause or menu
            # overlay. The two were the same config entry until the hotkeys came
            # from the game's own table, where "stop" is a unit order.
            self.executor.driver.key(self.executor.hotkeys.get_required("pause_menu_toggle"))
            return {
                "action": "AUTO_RESUME",
                "success": True,
                "duration_ms": (time.monotonic() - started) * 1000,
                "message": "sent configured pause/menu toggle",
            }
        except Exception as exc:  # noqa: BLE001 - live input must fail closed
            return {
                "action": "AUTO_RESUME",
                "success": False,
                "duration_ms": (time.monotonic() - started) * 1000,
                "message": str(exc),
            }

    def run(self, once: bool = False) -> None:
        benchmark = ReachFeudalBenchmark(time.time())
        handover_deadline = time.monotonic() + self.c.window.startup_wait_seconds
        while not self.safety.emergency_stopped:
            cycle_started = time.monotonic()
            target = self._acquire_target()
            if target is None:
                # An occluded window would only feed the planner other apps'
                # pixels, so skip capture and planning entirely this cycle.
                if once and time.monotonic() >= handover_deadline:
                    raise WindowNotForegroundError(
                        f"AoE2 was not brought to the front within "
                        f"{self.c.window.startup_wait_seconds:g}s; click into the game and rerun"
                    )
                time.sleep(self.c.window.foreground_poll_seconds)
                continue
            shot = self.capture.capture(target)
            state = self.reader.read_state(shot)
            benchmark.observe(state)
            if benchmark.complete(state):
                log.info("benchmark complete: %s", benchmark.metrics())
                return
            if not self.usage.can_call(
                self.c.agent.max_calls_per_game, self.c.budget.max_usd_per_game
            ):
                self.safety.paused = True
                log.error("LLM budget/call limit reached; bot paused")
                return
            try:
                planning_started = time.monotonic()
                plan, usage = self.planner.create_plan(
                    state, shot, self.history, benchmark.objective
                )
                planning_latency_ms = (time.monotonic() - planning_started) * 1000
            except PlannerError:
                planning_latency_ms = (time.monotonic() - planning_started) * 1000
                log.exception("invalid plan rejected; no fallback actions executed")
                plan = None
            results = []
            resumed = False
            if plan:
                self.usage.record(
                    usage.input_tokens,
                    usage.output_tokens,
                    self.c.agent.input_usd_per_million_tokens,
                    self.c.agent.output_usd_per_million_tokens,
                )
                if plan.observed_state.screen == "postgame" and self.end_game_review:
                    review_started = time.monotonic()
                    try:
                        self.end_game_review(shot)
                    except Exception:
                        log.exception("end-game review failed")
                    self.telemetry.write(
                        state.model_dump(mode="json"),
                        plan.model_dump(mode="json"),
                        [],
                        {
                            **benchmark.metrics(),
                            **self.usage.model_dump(),
                            "planning_latency_ms": planning_latency_ms,
                            "end_game_review_latency_ms": (time.monotonic() - review_started)
                            * 1000,
                            "cycle_latency_ms": (time.monotonic() - cycle_started) * 1000,
                        },
                    )
                    return
                resume_result = self._auto_resume(plan)
                if resume_result:
                    results.append(resume_result)
                    self.history.append(
                        {"action": {"type": "AUTO_RESUME"}, "result": resume_result}
                    )
                    resumed = bool(resume_result["success"])
                actions = executable_actions(plan, self.c.agent.min_state_confidence)
                for action in self.safety.filter(actions):
                    result = self.executor.execute(action)
                    results.append(result.model_dump(mode="json"))
                    self.history.append(
                        {
                            "action": action.model_dump(mode="json"),
                            "result": result.model_dump(mode="json"),
                        }
                    )
            self.telemetry.write(
                state.model_dump(mode="json"),
                {} if plan is None else plan.model_dump(mode="json"),
                results,
                {
                    **benchmark.metrics(),
                    **self.usage.model_dump(),
                    "planning_latency_ms": planning_latency_ms,
                    "cycle_latency_ms": (time.monotonic() - cycle_started) * 1000,
                },
            )
            if once:
                return
            time.sleep(
                0.5
                if resumed
                else (plan.recheck_after_seconds if plan else self.c.agent.default_recheck_seconds)
            )
