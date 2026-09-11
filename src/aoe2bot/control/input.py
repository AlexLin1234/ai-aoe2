from __future__ import annotations

import platform
import time
from collections import deque
from collections.abc import Callable


class FocusLostError(RuntimeError):
    """The target window stopped being foreground between preflight and input."""


MODIFIERS = ("ctrl", "alt", "shift")

# Keys the keyboard driver reports with the extended-key flag. AoE2 reads the
# flag, so scroll and edit keys are ignored without it.
EXTENDED_KEYS = frozenset(
    {
        "left",
        "right",
        "up",
        "down",
        "insert",
        "delete",
        "home",
        "end",
        "pageup",
        "pagedown",
        "numpad_divide",
        "printscreen",
        "numlock",
    }
)


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
        # Fails closed: a live driver with no way to confirm the game is in
        # front must not inject anything, since keystrokes go to whatever
        # window the user is currently in.
        if self.focus_check is None:
            raise FocusLostError("no foreground check configured; live input withheld")
        if not self.focus_check():
            raise FocusLostError("AoE2 is not the foreground window; input withheld")

    def set_allowed_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        self.allowed_bounds = bounds

    def key(self, key: str) -> None:
        if not self.live:
            return
        modifiers, base = self.split_hotkey(key)
        if base.startswith("mouse"):
            raise ValueError(
                f"configured key {key!r} is a mouse binding, which keyboard input "
                "cannot send; rebind the command to a key in game"
            )
        if platform.system() != "Windows":
            raise RuntimeError("live input requires Windows")
        self._guard_rate()
        self._guard_focus()
        import win32api
        import win32con

        codes = [self.virtual_key_code(name, win32con) for name in (*modifiers, base)]
        if None in codes:
            raise ValueError(f"unsupported configured key {key!r}")
        *modifier_codes, code = codes
        extended = win32con.KEYEVENTF_EXTENDEDKEY if base in EXTENDED_KEYS else 0
        for modifier in modifier_codes:
            win32api.keybd_event(modifier, 0, 0, 0)
        try:
            win32api.keybd_event(code, 0, extended, 0)
            self.sleep(self.interval)
            win32api.keybd_event(code, 0, extended | win32con.KEYEVENTF_KEYUP, 0)
        finally:
            # Released in reverse, and even when the press failed, so a stuck
            # Ctrl or Alt cannot follow the user into their next window.
            for modifier in reversed(modifier_codes):
                win32api.keybd_event(modifier, 0, win32con.KEYEVENTF_KEYUP, 0)

    @staticmethod
    def split_hotkey(spec: str) -> tuple[list[str], str]:
        """Split "ctrl+shift+h" into its modifiers and the key they qualify."""
        tokens = spec.lower().split("+")
        modifiers: list[str] = []
        while len(tokens) > 1 and tokens[0] in MODIFIERS:
            modifiers.append(tokens.pop(0))
        # Rejoined so "ctrl++" still means Ctrl and the plus key.
        return modifiers, "+".join(tokens)

    @staticmethod
    def virtual_key_code(key: str, win32con: object) -> int | None:
        if len(key) == 1 and key.isalpha():
            return ord(key.upper())
        if len(key) == 1 and key.isdigit():
            return ord(key)
        name = key.lower()
        names = {
            "ctrl": ("VK_CONTROL", 0x11),
            "alt": ("VK_MENU", 0x12),
            "shift": ("VK_SHIFT", 0x10),
            ".": ("VK_OEM_PERIOD", 0xBE),
            ",": ("VK_OEM_COMMA", 0xBC),
            ";": ("VK_OEM_1", 0xBA),
            "/": ("VK_OEM_2", 0xBF),
            "`": ("VK_OEM_3", 0xC0),
            "[": ("VK_OEM_4", 0xDB),
            "\\": ("VK_OEM_5", 0xDC),
            "]": ("VK_OEM_6", 0xDD),
            "'": ("VK_OEM_7", 0xDE),
            "=": ("VK_OEM_PLUS", 0xBB),
            "-": ("VK_OEM_MINUS", 0xBD),
            "decimal": ("VK_DECIMAL", 0x6E),
            "numpad_decimal": ("VK_DECIMAL", 0x6E),
            "numpad_add": ("VK_ADD", 0x6B),
            "numpad_subtract": ("VK_SUBTRACT", 0x6D),
            "numpad_multiply": ("VK_MULTIPLY", 0x6A),
            "numpad_divide": ("VK_DIVIDE", 0x6F),
            "esc": ("VK_ESCAPE", 0x1B),
            "escape": ("VK_ESCAPE", 0x1B),
            "space": ("VK_SPACE", 0x20),
            "enter": ("VK_RETURN", 0x0D),
            "tab": ("VK_TAB", 0x09),
            "backspace": ("VK_BACK", 0x08),
            "insert": ("VK_INSERT", 0x2D),
            "delete": ("VK_DELETE", 0x2E),
            "home": ("VK_HOME", 0x24),
            "end": ("VK_END", 0x23),
            "pageup": ("VK_PRIOR", 0x21),
            "pagedown": ("VK_NEXT", 0x22),
            "left": ("VK_LEFT", 0x25),
            "up": ("VK_UP", 0x26),
            "right": ("VK_RIGHT", 0x27),
            "down": ("VK_DOWN", 0x28),
            "pause": ("VK_PAUSE", 0x13),
            "capslock": ("VK_CAPITAL", 0x14),
            "numlock": ("VK_NUMLOCK", 0x90),
            "scrolllock": ("VK_SCROLL", 0x91),
            "printscreen": ("VK_SNAPSHOT", 0x2C),
        }
        if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
            return getattr(win32con, f"VK_F{int(name[1:])}", 0x6F + int(name[1:]))
        if name.startswith("numpad_") and name[7:].isdigit():
            return getattr(win32con, f"VK_NUMPAD{name[7:]}", 0x60 + int(name[7:]))
        entry = names.get(name)
        return None if entry is None else getattr(win32con, entry[0], entry[1])

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
