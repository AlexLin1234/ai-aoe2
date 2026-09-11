from __future__ import annotations

import platform
import time
from collections import deque
from collections.abc import Callable


class FocusLostError(RuntimeError):
    """The target window stopped being foreground between preflight and input."""


class InputDriver:
    def __init__(
        self,
        live: bool,
        max_events_per_second: int,
        key_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        click_delay: float = 0.05,
        focus_check: Callable[[], bool] | None = None,
    ):
        self.live = live
        self.limit = max_events_per_second
        self.interval = key_interval
        self.clock = clock
        self.sleep = sleeper
        self.click_delay = click_delay
        # Checked immediately before every injected event so a user alt-tabbing
        # mid-batch cannot have the remaining keystrokes typed into their app.
        self.focus_check = focus_check
        self.events: deque[float] = deque()
        self.allowed_bounds: tuple[int, int, int, int] | None = None

    def _guard_rate(self) -> None:
        while True:
            now = self.clock()
            while self.events and now - self.events[0] >= 1:
                self.events.popleft()
            if len(self.events) < self.limit:
                self.events.append(now)
                return
            self.sleep(max(0, 1 - (now - self.events[0])))

    def _guard_focus(self) -> None:
        if self.focus_check is not None and not self.focus_check():
            raise FocusLostError("AoE2 lost foreground focus; input withheld")

    def set_allowed_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        self.allowed_bounds = bounds

    def key(self, key: str) -> None:
        if not self.live:
            return
        if platform.system() != "Windows":
            raise RuntimeError("live input requires Windows")
        self._guard_rate()
        self._guard_focus()
        import win32api
        import win32con

        code = self.virtual_key_code(key, win32con)
        if code is None:
            raise ValueError(f"unsupported configured key {key!r}")
        win32api.keybd_event(code, 0, 0, 0)
        self.sleep(self.interval)
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)

    @staticmethod
    def virtual_key_code(key: str, win32con: object) -> int | None:
        if len(key) == 1 and key.isalpha():
            return ord(key.upper())
        if len(key) == 1 and key.isdigit():
            return ord(key)
        names = {
            ".": ("VK_OEM_PERIOD", 0xBE),
            ",": ("VK_OEM_COMMA", 0xBC),
            "decimal": ("VK_DECIMAL", 0x6E),
            "esc": ("VK_ESCAPE", 0x1B),
            "escape": ("VK_ESCAPE", 0x1B),
            "space": ("VK_SPACE", 0x20),
            "enter": ("VK_RETURN", 0x0D),
            "tab": ("VK_TAB", 0x09),
        }.get(key.lower())
        return None if names is None else getattr(win32con, names[0], names[1])

    def _click(self, x: int, y: int, down_flag: int, up_flag: int) -> None:
        if not self.live:
            return
        if platform.system() != "Windows":
            raise RuntimeError("live input requires Windows")
        self._guard_rate()
        if self.allowed_bounds is None or not (
            self.allowed_bounds[0] <= x < self.allowed_bounds[2]
            and self.allowed_bounds[1] <= y < self.allowed_bounds[3]
        ):
            raise RuntimeError("refusing click outside target window")
        self._guard_focus()
        import win32api

        win32api.SetCursorPos((x, y))
        # AoE2 samples the cursor on its own frame; clicking in the same tick as
        # the move makes it register the press at the previous position.
        self.sleep(self.click_delay)
        win32api.mouse_event(down_flag, 0, 0)
        self.sleep(self.interval)
        win32api.mouse_event(up_flag, 0, 0)

    def click(self, x: int, y: int) -> None:
        if not self.live:
            return
        import win32con

        self._click(x, y, win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP)

    def right_click(self, x: int, y: int) -> None:
        if not self.live:
            return
        import win32con

        self._click(x, y, win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP)
