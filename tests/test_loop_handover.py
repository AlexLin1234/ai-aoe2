from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from aoe2bot.agent.client import Usage
from aoe2bot.agent.schemas import Action, ActionType, Plan, VisualState
from aoe2bot.capture.window import TargetWindow, WindowNotForegroundError
from aoe2bot.config import load_config
from aoe2bot.perception.state import GameState
from aoe2bot.runtime.loop import BotLoop
from aoe2bot.runtime.safety import SafetyController

TARGET = TargetWindow(10, "AoE2", 99, (0, 0, 1920, 1080), (0, 0, 1920, 1080))


class Windows:
    """Scriptable foreground state; any activation attempt is a test failure."""

    def __init__(self, foreground: list[bool]):
        self.foreground = list(foreground)
        self.checks = 0

    def require(self) -> TargetWindow:
        return TARGET

    def refresh(self, target) -> TargetWindow:
        return target

    def is_foreground(self, target) -> bool:
        self.checks += 1
        return self.foreground.pop(0) if self.foreground else True


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
    config.window.foreground_poll_seconds = 0.01
    config.window.startup_wait_seconds = 0

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


def test_control_is_handed_over_when_the_user_has_the_game_in_front():
    executed: list = []
    loop = build_loop(Windows(foreground=[True]), executed, stop_after_cycles=1)

    loop.run()

    assert not loop.waiting_for_user
    assert [action.type for action in executed] == [ActionType.TRAIN_VILLAGER]


def test_control_is_handed_back_the_moment_the_user_clicks_away_and_resumes_after():
    windows = Windows(foreground=[True, False, True])
    loop = build_loop(windows, [])

    assert loop._acquire_target() is TARGET

    # The user clicks into another window: skip the cycle, take nothing back.
    assert loop._acquire_target() is None
    assert loop.waiting_for_user

    # The user clicks back into the game: control resumes on its own.
    assert loop._acquire_target() is TARGET
    assert not loop.waiting_for_user


def test_no_capture_planning_or_input_happens_while_the_user_is_elsewhere():
    executed: list = []
    windows = Windows(foreground=[True, False])
    loop = build_loop(windows, executed, stop_after_cycles=1)
    loop.run()  # one real cycle, then the user switches away

    planner_calls = loop.planner.calls
    loop.safety.emergency_stopped = False
    polls = [0]

    def is_foreground(target) -> bool:
        polls[0] += 1
        if polls[0] > 3:
            loop.safety.emergency_stopped = True
        return False

    loop.windows.is_foreground = is_foreground
    loop.run()

    assert loop.waiting_for_user
    assert loop.planner.calls == planner_calls, "no LLM spend while the user is working"
    assert [action.type for action in executed] == [ActionType.TRAIN_VILLAGER]


def test_single_cycle_run_explains_the_handover_instead_of_hanging():
    loop = build_loop(Windows(foreground=[False]), [])

    with pytest.raises(WindowNotForegroundError, match="click into the game"):
        loop.run(once=True)
    assert loop.planner.calls == 0


def _plan(screen: str, recheck: float = 5) -> Plan:
    return Plan(
        goal="resume",
        observed_state=VisualState(screen=screen, confidence=1),
        actions=[Action(type=ActionType.WAIT)],
        recheck_after_seconds=recheck,
    )


FROZEN = Image.new("RGB", (320, 180), "grey")


def _moved() -> Image.Image:
    """A frame with a visibly different world, well past the motion threshold."""
    frame = FROZEN.copy()
    ImageDraw.Draw(frame).rectangle((0, 0, 200, 120), fill="white")
    return frame


def build_pause_loop(keys: list[str], confirming: list[Image.Image]) -> BotLoop:
    loop = build_loop(Windows(foreground=[True] * 20), [])
    loop.executor = SimpleNamespace(
        driver=SimpleNamespace(live=True),
        hotkeys=SimpleNamespace(get_required=lambda name: {"pause_menu_toggle": "esc"}[name]),
        preflight=lambda: None,
    )
    loop.executor.driver.key = keys.append
    # The frame taken to confirm the overlay is still up, just before Escape.
    loop.capture = SimpleNamespace(capture=lambda target: confirming.pop(0))
    return loop


def test_auto_resume_clears_a_confirmed_pause_overlay_under_either_label():
    keys: list[str] = []
    loop = build_pause_loop(keys, [FROZEN, FROZEN])

    # The in-match pause overlay is titled "Main Menu", so the model labels it
    # menu about as often as paused; both have to clear it or the bot sits
    # forever in front of a game it could be playing.
    for screen in ("paused", "menu"):
        loop._note_screen(screen)
        loop._note_screen(screen)
        loop.last_resume_at = None
        assert loop._auto_resume(_plan(screen), TARGET, FROZEN)["sent"]

    assert keys == ["esc", "esc"]
    assert loop._auto_resume(_plan("gameplay"), TARGET, FROZEN) is None
    assert keys == ["esc", "esc"]


def test_one_overlay_frame_is_confirmed_before_escape_is_toggled():
    keys: list[str] = []
    loop = build_pause_loop(keys, [FROZEN])

    # Escape is a toggle: on a misread or stale frame it opens the very pause
    # menu it is meant to close, so a single reading never presses it.
    loop._note_screen("paused")
    first = loop._auto_resume(_plan("paused"), TARGET, FROZEN)
    assert not first["sent"] and "confirming" in str(first["message"])
    assert keys == []

    loop._note_screen("paused")
    assert loop._auto_resume(_plan("paused"), TARGET, FROZEN)["sent"]
    assert keys == ["esc"]


def test_escape_is_withheld_when_the_world_moved_since_the_classified_frame():
    keys: list[str] = []
    loop = build_pause_loop(keys, [_moved()])
    loop._note_screen("paused")
    loop._note_screen("paused")

    # The planner's verdict is a planning round old. A world that has moved on
    # since is a running game, whatever that stale frame was labelled.
    result = loop._auto_resume(_plan("paused"), TARGET, FROZEN)

    assert not result["sent"] and "moved" in str(result["message"])
    assert keys == []


def test_only_one_toggle_lands_per_cooldown():
    keys: list[str] = []
    loop = build_pause_loop(keys, [FROZEN, FROZEN])
    for _ in range(2):
        loop._note_screen("paused")
    assert loop._auto_resume(_plan("paused"), TARGET, FROZEN)["sent"]

    for _ in range(2):
        loop._note_screen("paused")
    result = loop._auto_resume(_plan("paused"), TARGET, FROZEN)

    assert not result["sent"] and "cooldown" in str(result["message"])
    assert keys == ["esc"]


def test_auto_resume_stands_down_instead_of_fighting_the_pause_menu():
    keys: list[str] = []
    loop = build_pause_loop(keys, [FROZEN] * 8)
    loop.c.input.auto_resume_cooldown_seconds = 0

    for _ in range(loop.c.input.auto_resume_max_attempts + 2):
        loop._note_screen("paused")
        loop._note_screen("paused")
        loop._auto_resume(_plan("paused"), TARGET, FROZEN)

    assert len(keys) == loop.c.input.auto_resume_max_attempts
    assert loop.stood_down

    # Gameplay coming back means the overlay is gone: the bot is free to clear
    # the next one it genuinely sees.
    loop._note_screen("gameplay")
    assert not loop.stood_down and loop.resume_attempts == 0


def test_a_brief_flicker_rechecks_at_once_and_a_real_overlay_backs_off():
    loop = build_loop(Windows(foreground=[True]), [])
    loop._note_screen("gameplay")

    loop._note_screen("menu")
    assert loop._recheck_delay(_plan("menu"), resumed=False) == pytest.approx(
        loop.c.agent.flicker_recheck_seconds
    )

    # An overlay that is still there several cycles later is not a flicker; go
    # back to the plan's own pace rather than burning calls on it.
    for _ in range(loop.c.agent.flicker_tolerance_cycles + 1):
        loop._note_screen("menu")
    assert loop._recheck_delay(_plan("menu"), resumed=False) == 5


def test_one_postgame_frame_does_not_end_the_run():
    screens = ["postgame", "gameplay", "gameplay"]
    reviewed: list = []
    loop = build_loop(Windows(foreground=[True] * 10), [], stop_after_cycles=2)
    loop.end_game_review = reviewed.append
    loop.planner.create_plan = lambda state, shot, history, objective: (
        _plan(screens.pop(0), recheck=0.5),
        Usage(),
    )

    loop.run()

    # A single postgame reading used to end the run and spend an end-game
    # review on what was really one odd frame mid-match.
    assert reviewed == []
    assert loop.seen_gameplay
