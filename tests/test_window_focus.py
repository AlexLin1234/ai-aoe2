import platform
import sys
from types import SimpleNamespace

import pytest

from aoe2bot.capture.window import TargetWindow, WindowFocusError, WindowManager
from aoe2bot.control.input import FocusLostError, InputDriver
from aoe2bot.runtime.hotkey_monitor import EmergencyHotkeyMonitor


def window(**overrides) -> TargetWindow:
    fields = {
        "handle": 10,
        "title": "Age of Empires II: Definitive Edition",
        "process_id": 99,
        "rect": (0, 0, 1920, 1080),
        "client_rect": (8, 31, 1912, 1072),
    }
    fields.update(overrides)
    return TargetWindow(**fields)


@pytest.fixture
def on_windows(monkeypatch):
    """Pretend to be Windows and stub the pywin32 modules the code imports."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(SW_RESTORE=9, SW_SHOW=5, SPI_GETFOREGROUNDLOCKTIMEOUT=0x2000),
    )
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(IsIconic=lambda hwnd: False))
    return monkeypatch


def test_capture_rect_prefers_client_area_and_ignores_degenerate_values():
    assert window().capture_rect == (8, 31, 1912, 1072)
    assert window(client_rect=None).capture_rect == (0, 0, 1920, 1080)
    # A minimized or not-yet-restored window reports an empty client area.
    assert window(client_rect=(0, 0, 0, 0)).capture_rect == (0, 0, 1920, 1080)


@pytest.mark.parametrize(
    ("foreground", "ancestor", "pid", "expected"),
    [
        (10, 10, 99, True),  # the game window itself
        (77, 10, 99, True),  # an owned popup or modal dialog
        (78, 78, 99, True),  # a second top-level window of the same game
        (78, 78, 1234, False),  # another application
        (0, 0, 99, False),  # nothing is focused at all
    ],
)
def test_foreground_check_accepts_any_window_owning_the_games_keyboard(
    monkeypatch, foreground, ancestor, pid, expected
):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            GetForegroundWindow=lambda: foreground,
            GetAncestor=lambda hwnd, flag: ancestor,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, pid)),
    )

    manager = WindowManager("age of empires", ["aoe2de_s.exe"])

    assert manager.is_foreground(window()) is expected


def test_focus_waits_for_activation_and_returns_geometry_read_afterwards(on_windows):
    manager = WindowManager("age of empires", [], focus_timeout_seconds=1)
    moved = window(rect=(100, 100, 2020, 1180), client_rect=(108, 131, 2012, 1172))
    # Activation is asynchronous: the game is only foreground on a later poll.
    states = iter([False, False, False, True])
    on_windows.setattr(manager, "is_foreground", lambda target: next(states, True))
    on_windows.setattr(manager, "refresh", lambda target: moved)
    on_windows.setattr(manager, "_activate", lambda target, use_alt: None)
    on_windows.setattr(manager, "_foreground_lock_timeout", lambda value: None)

    assert manager.focus(window()) is moved


def test_focus_gives_up_with_a_focus_error_callers_can_recover_from(on_windows):
    manager = WindowManager("age of empires", [], focus_timeout_seconds=0.2)
    attempts: list[bool] = []

    def activate(target, use_alt):
        attempts.append(use_alt)
        return RuntimeError("denied")

    on_windows.setattr(manager, "is_foreground", lambda target: False)
    on_windows.setattr(manager, "_activate", activate)
    on_windows.setattr(manager, "_foreground_lock_timeout", lambda value: None)

    with pytest.raises(WindowFocusError):
        manager.focus(window())
    # The synthetic Alt tap is a fallback only, never the first thing injected.
    assert attempts[0] is False
    assert len(attempts) > 1


def test_input_is_withheld_when_focus_is_lost_between_preflight_and_event():
    focused = [True]
    driver = InputDriver(True, 8, 0, sleeper=lambda seconds: None, focus_check=lambda: focused[0])
    driver.set_allowed_bounds((0, 0, 100, 100))
    focused[0] = False

    with pytest.raises(FocusLostError):
        driver.click(50, 50)
    with pytest.raises(FocusLostError):
        driver.key("h")


def test_click_outside_window_is_refused():
    driver = InputDriver(True, 8, 0, sleeper=lambda seconds: None, focus_check=lambda: True)
    driver.set_allowed_bounds((0, 0, 100, 100))

    with pytest.raises(RuntimeError, match="outside target window"):
        driver.click(500, 500)


def test_unsupported_safety_hotkey_fails_at_startup_not_inside_the_watchdog():
    with pytest.raises(ValueError, match="emergency stop"):
        EmergencyHotkeyMonitor("ctrl+q", "f11", lambda: None, lambda: None)
    EmergencyHotkeyMonitor("f12", "f11", lambda: None, lambda: None)
