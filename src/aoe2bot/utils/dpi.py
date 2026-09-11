from __future__ import annotations

import logging
import platform

log = logging.getLogger(__name__)

_state: str | None = None


def enable_per_monitor_dpi_awareness() -> str:
    """Put this process in the monitor's physical pixel space.

    Without it Win32 reports virtualized window rects (for example 1536x864 on a
    1920x1080 display scaled to 125%) while ``mss`` captures and the desktop
    cursor use physical pixels, so every screenshot is cropped and every click
    lands roughly a quarter of the screen away from its target. Must run before
    the first window query, capture, or cursor move.
    """
    global _state
    if _state is not None:
        return _state
    if platform.system() != "Windows":
        _state = "not-windows"
        return _state

    import ctypes

    # PER_MONITOR_AWARE_V2; the only mode that also scales non-client areas.
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            _state = "per-monitor-v2"
            return _state
    except (AttributeError, OSError):  # pre-1703 Windows
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        _state = "per-monitor"
        return _state
    except (AttributeError, OSError):  # already set, or pre-8.1 Windows
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        _state = "system"
        return _state
    except (AttributeError, OSError):
        _state = "unavailable"
        log.warning("could not enable DPI awareness; coordinates may be scaled incorrectly")
        return _state
