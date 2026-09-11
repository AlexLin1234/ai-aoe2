from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TargetWindow:
    handle: int
    title: str
    process_id: int
    rect: tuple[int, int, int, int]
    # Screen coordinates of the drawable area. Borders and the title bar are not
    # part of the game frame, so capture and clicks must both use this rect or
    # normalized coordinates drift by the chrome height.
    client_rect: tuple[int, int, int, int] | None = field(default=None)

    @property
    def capture_rect(self) -> tuple[int, int, int, int]:
        if self.client_rect is None:
            return self.rect
        left, top, right, bottom = self.client_rect
        if right - left <= 0 or bottom - top <= 0:
            return self.rect
        return self.client_rect


class WindowNotFoundError(RuntimeError):
    pass


class WindowFocusError(RuntimeError):
    """Focus could not be taken right now; the caller may retry a later cycle."""


class WindowManager:
    def __init__(
        self,
        title_contains: str,
        process_names: list[str],
        focus_timeout_seconds: float = 2.0,
    ):
        self.title_contains = title_contains.lower()
        self.process_names = {n.lower() for n in process_names}
        self.focus_timeout_seconds = focus_timeout_seconds

    @staticmethod
    def _client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int] | None:
        import win32gui

        try:
            _, _, width, height = win32gui.GetClientRect(hwnd)
            if width <= 0 or height <= 0:
                return None
            left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        except Exception:  # noqa: BLE001 - a window closing mid-query is normal
            return None
        return (left, top, left + width, top + height)

    def _describe(self, hwnd: int) -> TargetWindow | None:
        import win32api
        import win32con
        import win32gui
        import win32process

        title = win32gui.GetWindowText(hwnd)
        if self.title_contains not in title.lower():
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if self.process_names:
            try:
                handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
                )
            except Exception:  # noqa: BLE001 - elevated/exiting processes deny access
                return None
            try:
                process_name = (
                    win32process.GetModuleFileNameEx(handle, 0)
                    .replace("\\", "/")
                    .rsplit("/", 1)[-1]
                    .lower()
                )
            except Exception:  # noqa: BLE001 - name lookup can fail transiently
                return None
            finally:
                win32api.CloseHandle(handle)
            if process_name not in self.process_names:
                return None
        return TargetWindow(
            hwnd, title, pid, win32gui.GetWindowRect(hwnd), self._client_rect_on_screen(hwnd)
        )

    def find(self) -> TargetWindow | None:
        if platform.system() != "Windows":
            return None
        import win32gui

        matches: list[TargetWindow] = []

        def visit(hwnd: int, _: object) -> None:
            # An exception raised here aborts EnumWindows entirely, which the
            # caller would read as "the game vanished". Skip bad windows instead.
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                described = self._describe(hwnd)
            except Exception:  # noqa: BLE001 - pywin32 errors vary by call
                return
            if described is not None:
                matches.append(described)

        win32gui.EnumWindows(visit, None)
        if not matches:
            return None
        foreground = win32gui.GetForegroundWindow()

        def rank(window: TargetWindow) -> tuple[int, int]:
            left, top, right, bottom = window.capture_rect
            area = max(0, right - left) * max(0, bottom - top)
            # Prefer the window the user is actually looking at, then the
            # largest one: AoE2 DE also owns small helper/overlay windows.
            return (1 if window.handle == foreground else 0, area)

        return max(matches, key=rank)

    def require(self) -> TargetWindow:
        target = self.find()
        if target is None:
            raise WindowNotFoundError("positively identified AoE2 window not found")
        return target

    def refresh(self, target: TargetWindow) -> TargetWindow:
        """Re-read geometry for a known handle; windows move, resize and restore."""
        if platform.system() != "Windows":
            return target
        import win32gui

        try:
            if not win32gui.IsWindow(target.handle):
                return self.require()
            rect = win32gui.GetWindowRect(target.handle)
        except Exception:  # noqa: BLE001 - handle may die between calls
            return self.require()
        return TargetWindow(
            target.handle,
            target.title,
            target.process_id,
            rect,
            self._client_rect_on_screen(target.handle),
        )

    def is_foreground(self, target: TargetWindow) -> bool:
        if platform.system() != "Windows":
            return False
        import win32gui
        import win32process

        foreground = win32gui.GetForegroundWindow()
        if not foreground:
            return False
        if foreground == target.handle:
            return True
        # A modal dialog, popup or second top-level window of the game still
        # means AoE2 owns the keyboard, so input is safe to send.
        try:
            if win32gui.GetAncestor(foreground, 2) == target.handle:  # GA_ROOT
                return True
            _, pid = win32process.GetWindowThreadProcessId(foreground)
        except Exception:  # noqa: BLE001 - foreground window can die mid-query
            return False
        return pid == target.process_id

    def _foreground_lock_timeout(self, value: int | None) -> int | None:
        """Read or clear the foreground lock timeout, which blocks activation."""
        import win32con
        import win32gui

        try:
            if value is None:
                return int(win32gui.SystemParametersInfo(win32con.SPI_GETFOREGROUNDLOCKTIMEOUT))
            win32gui.SystemParametersInfo(
                win32con.SPI_SETFOREGROUNDLOCKTIMEOUT, value, win32con.SPIF_SENDCHANGE
            )
        except Exception:  # noqa: BLE001 - unsupported on some systems
            return None
        return None

    def _activate(self, target: TargetWindow, use_alt: bool) -> Exception | None:
        import win32api
        import win32con
        import win32gui
        import win32process

        attached: list[int] = []
        current_thread = win32api.GetCurrentThreadId()
        try:
            foreground = win32gui.GetForegroundWindow()
            thread_ids = {win32process.GetWindowThreadProcessId(target.handle)[0]}
            if foreground:
                thread_ids.add(win32process.GetWindowThreadProcessId(foreground)[0])
            for thread_id in thread_ids:
                if thread_id and thread_id != current_thread:
                    try:
                        win32process.AttachThreadInput(current_thread, thread_id, True)
                        attached.append(thread_id)
                    except Exception as exc:  # noqa: BLE001 - hung threads refuse attachment
                        log.debug("thread %s refused input attachment: %s", thread_id, exc)
                        continue
            if use_alt:
                # Last resort: a synthetic Alt tap makes this process eligible to
                # set the foreground window. Only sent when the game is not yet
                # focused, so the keystroke cannot reach the game itself.
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            win32gui.ShowWindow(target.handle, win32con.SW_SHOW)
            win32gui.BringWindowToTop(target.handle)
            win32gui.SetForegroundWindow(target.handle)
            win32gui.SetActiveWindow(target.handle)
        except Exception as exc:  # noqa: BLE001 - pywin32 errors vary by call
            return exc
        finally:
            for thread_id in reversed(attached):
                try:
                    win32process.AttachThreadInput(current_thread, thread_id, False)
                except Exception as exc:  # noqa: BLE001 - detach is best effort
                    log.debug("detaching thread %s failed: %s", thread_id, exc)
        return None

    def focus(self, target: TargetWindow) -> TargetWindow:
        """Bring the game forward and return its refreshed geometry."""
        if platform.system() != "Windows":
            raise RuntimeError("live control requires Windows")
        import win32con
        import win32gui

        if self.is_foreground(target):
            return self.refresh(target)

        try:
            if win32gui.IsIconic(target.handle):
                # A minimized window reports a (-32000, -32000) rect, so geometry
                # read before the restore completes is unusable.
                win32gui.ShowWindow(target.handle, win32con.SW_RESTORE)
        except Exception as exc:  # noqa: BLE001 - pywin32 errors vary by call
            log.debug("restoring minimized window failed: %s", exc)

        previous_timeout = self._foreground_lock_timeout(None)
        if previous_timeout:
            self._foreground_lock_timeout(0)
        last_error: Exception | None = None
        deadline = time.monotonic() + max(0.2, self.focus_timeout_seconds)
        attempt = 0
        try:
            while True:
                if self.is_foreground(target):
                    return self.refresh(target)
                last_error = self._activate(target, use_alt=attempt > 0) or last_error
                attempt += 1
                # Fullscreen and borderless games need a moment to take activation.
                for _ in range(5):
                    time.sleep(0.04)
                    if self.is_foreground(target):
                        return self.refresh(target)
                # Always allow the second pass so the Alt fallback is reached
                # even when the configured timeout is very short.
                if attempt >= 2 and time.monotonic() >= deadline:
                    break
        finally:
            if previous_timeout:
                self._foreground_lock_timeout(previous_timeout)

        detail = f": {last_error}" if last_error else ""
        raise WindowFocusError(
            f"could not focus AoE2 within {self.focus_timeout_seconds:g}s "
            f"after {attempt} attempts{detail}"
        )

    def focus_if_needed(self, target: TargetWindow) -> TargetWindow:
        return target if self.is_foreground(target) else self.focus(target)
