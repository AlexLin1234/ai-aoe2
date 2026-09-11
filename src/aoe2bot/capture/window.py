from __future__ import annotations

import platform
import time
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
        import win32api
        import win32con
        import win32gui
        import win32process

        if win32gui.IsIconic(target.handle):
            win32gui.ShowWindow(target.handle, win32con.SW_RESTORE)
        last_error: Exception | None = None
        for _ in range(3):
            if self.is_foreground(target):
                return
            try:
                # A brief Alt event lets a background automation process request
                # foreground activation under Windows' focus-stealing rules.
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                win32gui.BringWindowToTop(target.handle)
                win32gui.SetForegroundWindow(target.handle)
            except Exception as exc:  # noqa: BLE001 - pywin32 errors vary by call
                last_error = exc
            time.sleep(0.1)

        if self.is_foreground(target):
            return

        attached_threads: list[int] = []
        current_thread = win32api.GetCurrentThreadId()
        foreground = win32gui.GetForegroundWindow()
        thread_ids = {
            win32process.GetWindowThreadProcessId(target.handle)[0],
            win32process.GetWindowThreadProcessId(foreground)[0],
        }
        try:
            for thread_id in thread_ids:
                if thread_id != current_thread:
                    win32process.AttachThreadInput(current_thread, thread_id, True)
                    attached_threads.append(thread_id)
            win32gui.BringWindowToTop(target.handle)
            win32gui.SetForegroundWindow(target.handle)
            win32gui.SetFocus(target.handle)
        except Exception as exc:  # noqa: BLE001 - pywin32 errors vary by call
            last_error = exc
        finally:
            for thread_id in reversed(attached_threads):
                win32process.AttachThreadInput(current_thread, thread_id, False)

        time.sleep(0.1)
        if not self.is_foreground(target):
            detail = f": {last_error}" if last_error else ""
            raise RuntimeError(f"could not focus positively identified AoE2 window{detail}")
