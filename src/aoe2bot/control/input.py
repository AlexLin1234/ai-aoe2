from __future__ import annotations
import platform
import time
from collections import deque


class InputDriver:
    def __init__(self, live: bool, max_events_per_second: int, key_interval: float):
        self.live = live
        self.limit = max_events_per_second
        self.interval = key_interval
        self.events: deque[float] = deque()
        self.allowed_bounds: tuple[int, int, int, int] | None = None

    def _guard_rate(self) -> None:
        now = time.monotonic()
        while self.events and now - self.events[0] >= 1:
            self.events.popleft()
        if len(self.events) >= self.limit:
            raise RuntimeError("input event rate limit exceeded")
        self.events.append(now)

    def set_allowed_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        self.allowed_bounds = bounds

    def key(self, key: str) -> None:
        if not self.live:
            return
        if platform.system() != "Windows":
            raise RuntimeError("live input requires Windows")
        self._guard_rate()
        import win32api
        import win32con

        code = (
            ord(key.upper())
            if len(key) == 1 and key.isalpha()
            else {".": win32con.VK_DECIMAL, "esc": win32con.VK_ESCAPE}.get(key.lower())
        )
        if code is None:
            raise ValueError(f"unsupported configured key {key!r}")
        win32api.keybd_event(code, 0, 0, 0)
        time.sleep(self.interval)
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)

    def click(self, x: int, y: int) -> None:
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
        import win32api
        import win32con

        win32api.SetCursorPos((x, y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
