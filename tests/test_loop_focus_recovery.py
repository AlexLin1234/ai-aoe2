from types import SimpleNamespace

import pytest
from PIL import Image

from aoe2bot.agent.client import Usage
from aoe2bot.agent.schemas import Action, ActionType, Plan, VisualState
from aoe2bot.capture.window import TargetWindow, WindowFocusError
from aoe2bot.config import load_config
from aoe2bot.perception.state import GameState
from aoe2bot.runtime.loop import BotLoop
from aoe2bot.runtime.safety import SafetyController

TARGET = TargetWindow(10, "AoE2", 99, (0, 0, 1920, 1080), (0, 0, 1920, 1080))


class Windows:
    """Scriptable foreground state plus a focus() that can refuse activation."""

    def __init__(self, foreground: list[bool], focus_failures: int = 0):
        self.foreground = list(foreground)
        self.focus_failures = focus_failures
        self.focus_calls = 0
        self.checks = 0

    def require(self) -> TargetWindow:
        return TARGET

    def is_foreground(self, target) -> bool:
        self.checks += 1
        return self.foreground.pop(0) if self.foreground else True

    def focus(self, target) -> TargetWindow:
        self.focus_calls += 1
        if self.focus_calls <= self.focus_failures:
            raise WindowFocusError("foreground denied")
        return target

    def focus_if_needed(self, target) -> TargetWindow:
        return target if self.is_foreground(target) else self.focus(target)


class Planner:
    def __init__(self):
        self.calls = 0

    def create_plan(self, state, shot, history, objective):
        self.calls += 1
        return (
            Plan(
                goal="train",
                observed_state=VisualState(screen="gameplay", confidence=1),
                actions=[Action(type=ActionType.TRAIN_VILLAGER)],
                recheck_after_seconds=0.5,
            ),
            Usage(),
        )


def build_loop(windows: Windows, executed: list, stop_after_cycles: int = 0) -> BotLoop:
    config = load_config("config/default.yaml")
    config.window.focus_retry_seconds = 0.01
    config.window.yield_poll_seconds = 0.01

    class Executor:
        driver = SimpleNamespace(live=True)

        def execute(self, action):
            executed.append(action)
            return SimpleNamespace(model_dump=lambda mode: {"action": action.type, "success": True})

    loop = BotLoop(
        config,
        windows,
        SimpleNamespace(capture=lambda target: Image.new("RGB", (64, 64))),
        SimpleNamespace(read_state=lambda shot: GameState()),
        Planner(),
        Executor(),
        SafetyController(4, 0),
        SimpleNamespace(write=lambda *args: None),
    )
    if stop_after_cycles:
        cycles = [0]
        write = loop.telemetry.write

        def counting_write(*args):
            write(*args)
            cycles[0] += 1
            if cycles[0] >= stop_after_cycles:
                loop.safety.emergency_stopped = True

        loop.telemetry = SimpleNamespace(write=counting_write)
    return loop


def test_focus_is_taken_once_at_startup_so_a_launched_run_can_begin():
    executed: list = []
    windows = Windows(foreground=[False, True], focus_failures=0)
    loop = build_loop(windows, executed, stop_after_cycles=1)

    loop.run()

    assert windows.focus_calls == 1
    assert loop.acquired_once and not loop.yielded
    assert [action.type for action in executed] == [ActionType.TRAIN_VILLAGER]


def test_bot_yields_the_desktop_once_the_user_takes_focus_and_resumes_after():
    windows = Windows(foreground=[True, False, True])
    loop = build_loop(windows, [])

    # The game is in front, so the bot is in control.
    assert loop._acquire_target() is TARGET
    assert loop.acquired_once

    # The user switches to another window: skip the cycle, never grab it back.
    assert loop._acquire_target() is None
    assert loop.yielded
    assert windows.focus_calls == 0, "focus must never be taken back from the user"
    assert loop.focus_failures == 0, "yielding is cooperative, not a failure"

    # The user clicks back into the game: control resumes on its own.
    assert loop._acquire_target() is TARGET
    assert not loop.yielded


def test_no_capture_planning_or_input_happens_while_yielding():
    executed: list = []
    windows = Windows(foreground=[True, False, False])
    loop = build_loop(windows, executed, stop_after_cycles=1)
    loop.run()  # one real cycle, then the user takes over

    planner_calls = loop.planner.calls
    loop.safety.emergency_stopped = False
    yields = [0]

    def is_foreground(target) -> bool:
        yields[0] += 1
        if yields[0] > 3:
            loop.safety.emergency_stopped = True
        return False

    loop.windows.is_foreground = is_foreground
    loop.run()

    assert loop.yielded
    assert windows.focus_calls == 0
    assert loop.planner.calls == planner_calls, "no LLM spend while the user is working"
    assert [action.type for action in executed] == [ActionType.TRAIN_VILLAGER]


def test_yield_poll_is_used_instead_of_the_failure_backoff():
    loop = build_loop(Windows(foreground=[True]), [])
    loop.yielded = True
    assert loop._skip_backoff_seconds() == loop.c.window.yield_poll_seconds

    loop.yielded = False
    loop.focus_failures = 3
    assert loop._skip_backoff_seconds() == loop.c.window.focus_retry_seconds * 3


def test_refused_activation_at_startup_retries_without_crashing():
    executed: list = []
    windows = Windows(foreground=[False, False, False], focus_failures=99)
    loop = build_loop(windows, executed)

    original = loop._note_focus_failure

    def stop_after_three(detail: str) -> None:
        original(detail)
        if loop.focus_failures >= 3:
            loop.safety.emergency_stopped = True

    loop._note_focus_failure = stop_after_three
    loop.run()

    assert windows.focus_calls == 3
    assert loop.planner.calls == 0, "no LLM spend while the game cannot be focused"
    assert executed == [], "no input sent to whatever window holds focus"


def test_single_cycle_run_reports_the_focus_failure_instead_of_hanging():
    loop = build_loop(Windows(foreground=[False], focus_failures=99), [])

    with pytest.raises(WindowFocusError):
        loop.run(once=True)
    assert loop.planner.calls == 0
