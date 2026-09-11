from __future__ import annotations
import platform
import threading
import time
from collections.abc import Callable


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

    def start(self) -> None:
        if platform.system() != "Windows":
            return
        threading.Thread(target=self._run, daemon=True, name="safety-hotkeys").start()

    def _run(self) -> None:
        import win32api
        import win32con

        keys = {"f12": win32con.VK_F12, "f11": win32con.VK_F11}
        previous = {self.stop_key: False, self.pause_key: False}
        while True:
            for name, callback in ((self.stop_key, self.on_stop), (self.pause_key, self.on_pause)):
                down = bool(win32api.GetAsyncKeyState(keys[name.lower()]) & 0x8000)
                if down and not previous[name]:
                    callback()
                previous[name] = down
            time.sleep(0.05)
