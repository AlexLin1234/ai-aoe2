from __future__ import annotations
import base64
import io
from PIL import Image
from mss import mss
from .window import TargetWindow


class ScreenshotCapture:
    def capture(self, target: TargetWindow) -> Image.Image:
        # capture_rect excludes borders/title bar so the frame the model sees is
        # exactly the coordinate space clicks are resolved against.
        left, top, right, bottom = target.capture_rect
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            raise RuntimeError(f"AoE2 window has no drawable area ({width}x{height})")
        with mss() as grabber:
            raw = grabber.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", raw.size, raw.rgb)


def agent_jpeg_data_url(image: Image.Image, max_width: int, quality: int) -> str:
    copy = image.copy()
    if copy.width > max_width:
        copy.thumbnail((max_width, 9999))
    stream = io.BytesIO()
    copy.save(stream, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode()
