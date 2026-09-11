from __future__ import annotations
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetWindow:
    handle: int
    title: str
    process_id: int
    rect: tuple[int, int, int, int]


class WindowNotFoundError(RuntimeError):
    pass


class WindowManager:
    def __init__(self, title_contains: str, process_names: list[str]):
        self.title_contains = title_contains.lower()
        self.process_names = {n.lower() for n in process_names}

    def find(self) -> TargetWindow | None:
        if platform.system() != "Windows":
            return None
        import win32api
        import win32con
        import win32gui
        import win32process

        matches: list[TargetWindow] = []

        def visit(hwnd: int, _: object) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if self.title_contains not in title.lower():
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid
            )
            try:
                process_name = (
                    win32process.GetModuleFileNameEx(handle, 0)
                    .replace("\\", "/")
                    .rsplit("/", 1)[-1]
                    .lower()
                )
            finally:
                win32api.CloseHandle(handle)
            if self.process_names and process_name not in self.process_names:
                return
            matches.append(TargetWindow(hwnd, title, pid, win32gui.GetWindowRect(hwnd)))

        win32gui.EnumWindows(visit, None)
        return matches[0] if matches else None

    def require(self) -> TargetWindow:
        target = self.find()
        if target is None:
            raise WindowNotFoundError("positively identified AoE2 window not found")
        return target

    def is_foreground(self, target: TargetWindow) -> bool:
        if platform.system() != "Windows":
            return False
        import win32gui

        return win32gui.GetForegroundWindow() == target.handle

    def focus(self, target: TargetWindow) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("live control requires Windows")
        import win32con
        import win32gui

        win32gui.ShowWindow(target.handle, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(target.handle)
