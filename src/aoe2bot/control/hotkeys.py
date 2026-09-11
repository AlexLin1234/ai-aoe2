from pathlib import Path
import yaml
from pydantic import RootModel


class Hotkeys(RootModel[dict[str, str]]):
    def get_required(self, name: str) -> str:
        value = self.root.get(name)
        if not value:
            raise KeyError(f"hotkey not configured: {name}")
        return value


def load_hotkeys(path: str | Path) -> Hotkeys:
    with Path(path).open(encoding="utf-8") as stream:
        return Hotkeys.model_validate(yaml.safe_load(stream))
