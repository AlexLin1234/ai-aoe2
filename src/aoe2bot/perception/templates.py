from pathlib import Path


class TemplateRegistry:
    def __init__(self, root: Path):
        self.root = root

    def path(self, name: str) -> Path:
        return self.root / f"{name}.png"
