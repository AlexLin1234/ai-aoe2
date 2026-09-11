from __future__ import annotations

import logging
import platform
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


class WindowNotForegroundError(RuntimeError):
    """AoE2 is not the window the user is currently in."""


class WindowManager:
    """Finds and inspects the game window. It deliberately cannot activate it.

    The bot only ever acts on a window the user themselves brought to the front,
    so there is no focus-stealing code here to misfire: no SetForegroundWindow,
    no AttachThreadInput, and no synthetic Alt tap into whatever app is focused.
    """

    def __init__(self, title_contains: str, process_names: list[str]):
        self.title_contains = title_contains.lower()
        self.process_names = {n.lower() for n in process_names}

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

    def require_foreground(self) -> TargetWindow:
        """The game window, only if the user currently has it in front."""
        target = self.require()
        if not self.is_foreground(target):
            raise WindowNotForegroundError("AoE2 is not the foreground window")
        # Geometry is read now rather than cached: the window may have been
        # moved, resized or restored since it was last in front.
        return self.refresh(target)
