from PIL import Image
from .state import GameState


class StateReader:
    """Conservative v1 parser; unknown data stays unknown instead of being guessed."""

    def read_state(self, screenshot: Image.Image) -> GameState:
        return GameState(
            notes=[f"Captured {screenshot.width}x{screenshot.height}; OCR/templates not configured"]
        )
