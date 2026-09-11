"""Regenerate config/hotkeys.yaml from the hotkey table AoE2 DE ships.

The game stores every hotkey and its per-preset defaults in
``resources/_common/dat/hotkeys.json``; the labels shown in the options screen
live in the localized key-value string files. Generating from those keeps the
config honest across patches instead of transcribing the options screen by hand.

    python scripts/generate_hotkeys.py --preset definitive
"""

from __future__ import annotations

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path

DEFAULT_GAME_DIRS = (
    Path(r"C:/Program Files (x86)/Steam/steamapps/common/AoE2DE"),
    Path(r"C:/Program Files/Steam/steamapps/common/AoE2DE"),
)

# Names the executor asks for, mapped to the game's own hotkey identifier. A
# villager opens its build pages with "Economic Buildings", not the BUILD_MENU
# entry, which belongs to military units that can build.
ALIASES = OrderedDict(
    (
        ("select_town_center", "GOTO_TOWN_CENTER"),
        ("select_idle_villager", "NEXT_IDLE_VILLAGER"),
        ("train_villager", "TOWN_CENTER_CREATE_VILLAGER"),
        ("build_menu", "BUILD_ECONOMIC"),
        ("house", "VILLAGER_BUILD_HOUSE"),
        ("lumber_camp", "VILLAGER_BUILD_LUMBER_CAMP"),
        ("research_feudal", "TOWN_CENTER_AGE_ADVANCE"),
    )
)

# Escape is not in the game's hotkey table because it cannot be rebound, but the
# loop needs it by name to dismiss a pause or menu overlay.
FIXED_ALIASES = OrderedDict((("pause_menu_toggle", "esc"),))

KEY_NAMES = {
    "VK_BACK": "backspace",
    "VK_TAB": "tab",
    "VK_RETURN": "enter",
    "VK_PAUSE": "pause",
    "VK_CAPITAL": "capslock",
    "VK_ESCAPE": "esc",
    "VK_SPACE": "space",
    "VK_PRIOR": "pageup",
    "VK_NEXT": "pagedown",
    "VK_END": "end",
    "VK_HOME": "home",
    "VK_LEFT": "left",
    "VK_UP": "up",
    "VK_RIGHT": "right",
    "VK_DOWN": "down",
    "VK_SNAPSHOT": "printscreen",
    "VK_INSERT": "insert",
    "VK_DELETE": "delete",
    "VK_MULTIPLY": "numpad_multiply",
    "VK_ADD": "numpad_add",
    "VK_SUBTRACT": "numpad_subtract",
    "VK_DECIMAL": "numpad_decimal",
    "VK_DIVIDE": "numpad_divide",
    "VK_NUMLOCK": "numlock",
    "VK_SCROLL": "scrolllock",
    "VK_OEM_1": ";",
    "VK_OEM_PLUS": "=",
    "VK_OEM_COMMA": ",",
    "VK_OEM_MINUS": "-",
    "VK_OEM_PERIOD": ".",
    "VK_OEM_2": "/",
    "VK_OEM_3": "`",
    "VK_OEM_4": "[",
    "VK_OEM_5": "\\",
    "VK_OEM_6": "]",
    "VK_OEM_7": "'",
    # Mouse bindings are listed for completeness; the input driver cannot send
    # them, so an action that needs one fails loudly instead of misfiring.
    "FE_VK_LBUTTON": "mouse_left",
    "FE_VK_RBUTTON": "mouse_right",
    "FE_VK_MBUTTON": "mouse_middle",
    "FE_VK_XBUTTON1": "mouse_x1",
    "FE_VK_XBUTTON2": "mouse_x2",
    "FE_VK_MWHEEL_UP": "mousewheel_up",
    "FE_VK_MWHEEL_DOWN": "mousewheel_down",
}
KEY_NAMES.update({f"VK_F{n}": f"f{n}" for n in range(1, 25)})
KEY_NAMES.update({f"VK_NUMPAD{n}": f"numpad_{n}" for n in range(10)})


def find_game_dir(explicit: str | None) -> Path:
    candidates = [Path(explicit)] if explicit else list(DEFAULT_GAME_DIRS)
    for candidate in candidates:
        if (candidate / "resources/_common/dat/hotkeys.json").is_file():
            return candidate
    raise SystemExit(
        "could not find AoE2 DE; pass --game-dir pointing at the install folder"
    )


def load_strings(game_dir: Path, language: str) -> dict[int, str]:
    strings: dict[int, str] = {}
    root = game_dir / "resources" / language / "strings" / "key-value"
    for path in sorted(root.glob("*.txt")):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                match = re.match(r'\s*(\d+)\s+"(.*)"\s*$', line)
                if match:
                    strings.setdefault(int(match.group(1)), match.group(2))
    return strings


def render_key(default: dict | None) -> str:
    if default is None:
        return ""
    raw = default["key"]
    if len(raw) == 1 and (raw.isalpha() or raw.isdigit()):
        name = raw.lower()
    elif raw in KEY_NAMES:
        name = KEY_NAMES[raw]
    else:
        raise SystemExit(f"unmapped key token {raw!r}; add it to KEY_NAMES")
    modifiers = [
        label
        for label, flag in (("ctrl", "control"), ("alt", "alternate"), ("shift", "shift"))
        if default.get(flag)
    ]
    return "+".join([*modifiers, name])


def collect(game_dir: Path, preset: str, language: str) -> tuple[list, dict[str, str]]:
    table = json.loads(
        (game_dir / "resources/_common/dat/hotkeys.json").read_text(encoding="utf-8-sig")
    )
    strings = load_strings(game_dir, language)
    groups: list[tuple[str, list[tuple[str, str, str]]]] = []
    by_data_name: dict[str, str] = {}
    taken = set(ALIASES) | set(FIXED_ALIASES)

    for section in table.values():
        for group in section:
            entries: list[tuple[str, str, str]] = []
            for hotkey in group["hotkey_list"]:
                data_name = hotkey["data_name"]
                default = next(
                    (
                        entry
                        for entry in hotkey.get("defaults_list") or []
                        if entry["name"] == preset
                    ),
                    None,
                )
                value = render_key(default)
                by_data_name[data_name] = value
                name = data_name.lower()
                if name in taken:
                    # Only BUILD_MENU collides today, with the alias a villager
                    # needs; keep the game's entry under its group's name.
                    name = f"{group['data_name'].lower().removesuffix('_hotkeys')}_{name}"
                taken.add(name)
                entries.append((name, value, strings.get(hotkey["name_string_id"], "")))
            string_id = group.get("name_string_id")
            label = strings.get(string_id) if string_id else None
            label = label or group["data_name"].replace("_", " ").title()
            groups.append((f"{label} - {group['data_name']}", entries))
    return groups, by_data_name


def render(groups: list, by_data_name: dict[str, str], preset: str) -> str:
    width = max(
        (len(name) for _, entries in groups for name, _, _ in entries),
        default=0,
    )
    # Cap the alignment so a handful of very long identifiers do not push every
    # value off to the right.
    width = min(max(width, max(len(name) for name in (*ALIASES, *FIXED_ALIASES))), 34)
    lines = [
        "# Age of Empires II: Definitive Edition hotkeys.",
        "#",
        f'# Generated by scripts/generate_hotkeys.py from the "{preset}" preset in the',
        "# game's own resources/_common/dat/hotkeys.json, so the values match what the",
        "# options screen calls Definitive Edition defaults. Re-run that script after a",
        "# patch, and edit here only if you have rebound keys in game.",
        "#",
        "# Values are lowercase key names with ctrl/alt/shift prefixes, for example",
        '# "ctrl+shift+h". An empty value means the preset leaves the command unbound;',
        "# asking for it raises instead of sending a stray keystroke. mouse_* and",
        "# mousewheel_* values are real defaults that keyboard injection cannot send.",
        "",
        "# Aliases the executor asks for by name. They repeat a binding below under the",
        "# name the bot's action vocabulary uses.",
    ]
    for alias, data_name in ALIASES.items():
        value = by_data_name[data_name]
        lines.append(f'{alias + ":":<{width + 1}} "{value}"  # {data_name}')
    for alias, value in FIXED_ALIASES.items():
        lines.append(f'{alias + ":":<{width + 1}} "{value}"  # not rebindable in game')

    for label, entries in groups:
        lines += ["", f"# --- {label} ---"]
        for name, value, description in entries:
            comment = f"  # {description}" if description else ""
            lines.append(f'{name + ":":<{width + 1}} "{value}"{comment}')
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", default=None)
    parser.add_argument(
        "--preset",
        default="definitive",
        choices=["definitive", "classic", "high definition", "left handed"],
    )
    parser.add_argument("--language", default="en")
    parser.add_argument("--out", default="config/hotkeys.yaml")
    args = parser.parse_args()

    game_dir = find_game_dir(args.game_dir)
    groups, by_data_name = collect(game_dir, args.preset, args.language)
    missing = [name for name in ALIASES.values() if name not in by_data_name]
    if missing:
        raise SystemExit(f"hotkeys.json no longer defines: {', '.join(missing)}")
    Path(args.out).write_text(render(groups, by_data_name, args.preset), encoding="utf-8")
    total = sum(len(entries) for _, entries in groups)
    print(f"wrote {args.out}: {total} hotkeys from {game_dir}")


if __name__ == "__main__":
    main()
