from __future__ import annotations

import logging
import platform
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

# Virtual-key codes are resolved locally so an unusual configured hotkey fails
# at startup instead of killing the watchdog thread on its first poll and
# silently disarming the emergency stop.
VIRTUAL_KEYS: dict[str, int] = {f"f{n}": 0x6F + n for n in range(1, 13)}
VIRTUAL_KEYS.update({"pause": 0x13, "scrolllock": 0x91, "end": 0x23, "home": 0x24})


class EmergencyHotkeyMonitor:
    """Polls global Win32 key state; F12 stops and F11 toggles pause by default."""

    def __init__(
        self,
        stop_key: str,
        pause_key: str,
        on_stop: Callable[[], None],
        on_pause: Callable[[], None],
    ):
        self.stop_key = stop_key
        self.pause_key = pause_key
        self.on_stop = on_stop
        self.on_pause = on_pause
        for role, name in (("emergency stop", stop_key), ("pause/resume", pause_key)):
            if name.lower() not in VIRTUAL_KEYS:
                raise ValueError(
                    f"unsupported {role} hotkey {name!r}; choose one of "
                    + ", ".join(sorted(VIRTUAL_KEYS))
                )

    def start(self) -> None:
        if platform.system() != "Windows":
            return
        threading.Thread(target=self._run, daemon=True, name="safety-hotkeys").start()

    def _run(self) -> None:
        import win32api

        previous = {self.stop_key: False, self.pause_key: False}
        while True:
            try:
                for name, callback in (
                    (self.stop_key, self.on_stop),
                    (self.pause_key, self.on_pause),
                ):
                    down = bool(win32api.GetAsyncKeyState(VIRTUAL_KEYS[name.lower()]) & 0x8000)
                    if down and not previous[name]:
                        callback()
                    previous[name] = down
            except Exception:  # the watchdog must outlive any single failed poll
                log.exception("safety hotkey poll failed")
            time.sleep(0.05)
