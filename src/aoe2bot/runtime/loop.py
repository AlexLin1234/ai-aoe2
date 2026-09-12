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
from aoe2bot.perception.motion import moved_fraction

from .safety import SafetyController
from .telemetry import TelemetryWriter, UsageTracker

log = logging.getLogger(__name__)

# The in-match pause overlay is titled "Main Menu", so the model labels it menu
# about as often as paused. Both mean "an overlay Escape would clear".
OVERLAY_SCREENS = frozenset({"paused", "menu"})


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
        # Screen-reading history. A single frame is never enough to act on: the
        # planner sees a screenshot that is a whole planning round old by the
        # time its verdict arrives, and Escape and the end-game review are both
        # one-way doors.
        self.seen_gameplay = False
        self.last_screen: str | None = None
        self.screen_streak = 0
        self.non_gameplay_streak = 0
        self.overlay_streak = 0
        self.resume_attempts = 0
        self.last_resume_at: float | None = None
        self.stood_down = False

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

    def _note_screen(self, screen: str) -> None:
        self.screen_streak = self.screen_streak + 1 if screen == self.last_screen else 1
        self.last_screen = screen
        if screen == "gameplay":
            self.seen_gameplay = True
            self.non_gameplay_streak = 0
            self.overlay_streak = 0
            # Gameplay is back, so whatever the last Escape did, it worked.
            self.resume_attempts = 0
            self.stood_down = False
            return
        self.non_gameplay_streak += 1
        self.overlay_streak = self.overlay_streak + 1 if screen in OVERLAY_SCREENS else 0

    def _confirmed_screen(self) -> bool:
        """The same screen twice running, so it is not one odd frame."""
        return self.screen_streak >= self.c.agent.screen_confirm_cycles

    def _flickering(self) -> bool:
        """A short non-gameplay blip in an otherwise running game.

        A pause overlay that comes and goes - the user tapping Escape, a frame
        caught mid-transition, or the planner misreading one screenshot - must
        not park the agent for seconds or end its run. It looks again straight
        away instead, and only a reading that persists is believed.
        """
        return (
            self.seen_gameplay
            and 0 < self.non_gameplay_streak <= self.c.agent.flicker_tolerance_cycles
        )

    @staticmethod
    def _resume_record(sent: bool, message: str, started: float) -> dict[str, object]:
        return {
            "action": "AUTO_RESUME",
            "sent": sent,
            "success": sent,
            "duration_ms": (time.monotonic() - started) * 1000,
            "message": message,
        }

    def _auto_resume(
        self, plan: Plan, target: TargetWindow, planned_frame: Image.Image
    ) -> dict[str, object] | None:
        """Clear a pause/menu overlay with Escape, but only once it is proven.

        Escape is a toggle, not an idempotent "resume": pressed while the game
        is actually running it *opens* the pause menu. Acting on a single
        classification of a frame that is one planning round (seconds) old is
        therefore how the bot pops up the menu it is trying to dismiss, and how
        it then ping-pongs the overlay open and shut. Three gates prevent that:
        the same overlay has to be read on consecutive cycles, a frame taken
        right now has to show the world still frozen behind it, and one toggle
        at a time is sent, with a stand-down when it clearly is not helping.
        """
        screen = plan.observed_state.screen
        if (
            not self.executor.driver.live
            or not self.c.input.auto_resume
            or self.safety.paused
            or screen not in OVERLAY_SCREENS
        ):
            return None
        started = time.monotonic()
        if self.overlay_streak < self.c.agent.screen_confirm_cycles:
            return self._resume_record(
                False,
                f"{screen} read once; confirming on the next frame before toggling",
                started,
            )
        if self.stood_down:
            return self._resume_record(
                False, "auto-resume stood down; press Escape yourself", started
            )
        if (
            self.last_resume_at is not None
            and started - self.last_resume_at < self.c.input.auto_resume_cooldown_seconds
        ):
            return self._resume_record(
                False, "within the auto-resume cooldown; letting the last Escape land", started
            )
        if self.resume_attempts >= self.c.input.auto_resume_max_attempts:
            self.stood_down = True
            log.warning(
                "%d Escapes did not restore gameplay; auto-resume is standing down so it "
                "cannot keep toggling the pause menu. Clear the overlay yourself.",
                self.resume_attempts,
            )
            return self._resume_record(
                False, "auto-resume stood down after repeated attempts", started
            )
        try:
            # The planner's frame is seconds old. Escape is only safe if the
            # world is *still* frozen right now, so re-read it first.
            current_frame = self.capture.capture(self.windows.refresh(target))
        except Exception as exc:  # noqa: BLE001 - never toggle on a failed check
            return self._resume_record(False, f"could not confirm the overlay: {exc}", started)
        motion = moved_fraction(planned_frame, current_frame)
        if motion > self.c.input.auto_resume_motion_threshold:
            return self._resume_record(
                False,
                f"the world moved ({motion:.4f}) since the frame read as {screen}; "
                "not sending Escape into a running game",
                started,
            )
        try:
            self.executor.preflight()
            # Escape, not the unit Stop command: this dismisses a pause or menu
            # overlay. The two were the same config entry until the hotkeys came
            # from the game's own table, where "stop" is a unit order.
            self.executor.driver.key(self.executor.hotkeys.get_required("pause_menu_toggle"))
        except Exception as exc:  # noqa: BLE001 - live input must fail closed
            return self._resume_record(False, str(exc), started)
        self.last_resume_at = time.monotonic()
        self.resume_attempts += 1
        # Earn the confirmation again before the next toggle.
        self.overlay_streak = 0
        return self._resume_record(True, "sent configured pause/menu toggle", started)

    def _recheck_delay(self, plan: Plan | None, resumed: bool) -> float:
        if resumed:
            return 0.5
        if plan is None:
            return self.c.agent.default_recheck_seconds
        if self._flickering():
            return self.c.agent.flicker_recheck_seconds
        return plan.recheck_after_seconds

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
                self._note_screen(plan.observed_state.screen)
                # One postgame frame ends the run and burns an end-game review,
                # so it has to be the screen twice running, not a flicker.
                if (
                    plan.observed_state.screen == "postgame"
                    and self.end_game_review
                    and self._confirmed_screen()
                ):
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
                resume_result = self._auto_resume(plan, target, shot)
                if resume_result:
                    results.append(resume_result)
                    resumed = bool(resume_result["sent"])
                    if resumed:
                        # Only a delivered toggle is history the planner needs;
                        # the gates that withheld one are telemetry, not action.
                        self.history.append(
                            {"action": {"type": "AUTO_RESUME"}, "result": resume_result}
                        )
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
            time.sleep(self._recheck_delay(plan, resumed))
