from pathlib import Path
from types import SimpleNamespace

import pytest

from aoe2bot.control.hotkeys import load_hotkeys
from aoe2bot.control.input import InputDriver

CONFIG = Path(__file__).resolve().parents[1] / "config" / "hotkeys.yaml"

# Every name the executor and loop look up by hand.
REQUIRED = (
    "select_town_center",
    "select_idle_villager",
    "train_villager",
    "build_menu",
    "house",
    "lumber_camp",
    "research_feudal",
    "stop",
)


def test_shipped_config_covers_every_name_the_bot_asks_for():
    hotkeys = load_hotkeys(CONFIG)

    for name in REQUIRED:
        assert hotkeys.get_required(name)


def test_shipped_config_only_contains_keys_the_driver_can_send():
    hotkeys = load_hotkeys(CONFIG)
    constants = SimpleNamespace()

    for name, spec in hotkeys.root.items():
        if not spec or "mouse" in spec:
            # Unbound commands and the game's mouse defaults are recorded for
            # completeness; both fail loudly rather than sending a wrong key.
            continue
        modifiers, base = InputDriver.split_hotkey(spec)
        assert all(InputDriver.virtual_key_code(m, constants) for m in modifiers), name
        assert InputDriver.virtual_key_code(base, constants) is not None, f"{name}: {spec}"


def test_split_hotkey_separates_modifiers_from_the_key():
    assert InputDriver.split_hotkey("ctrl+shift+h") == (["ctrl", "shift"], "h")
    assert InputDriver.split_hotkey("alt+.") == (["alt"], ".")
    assert InputDriver.split_hotkey("h") == ([], "h")
    assert InputDriver.split_hotkey("ctrl+=") == (["ctrl"], "=")


def test_mouse_bindings_are_refused_before_any_key_is_sent():
    driver = InputDriver(True, 8, 0, focus_check=lambda: True)

    with pytest.raises(ValueError, match="mouse binding"):
        driver.key("mousewheel_up")
