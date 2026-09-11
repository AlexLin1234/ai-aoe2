from __future__ import annotations

import time
from collections.abc import Callable

from aoe2bot.agent.schemas import Action, ActionResult, ActionType
from aoe2bot.config import CalibrationConfig

from .hotkeys import Hotkeys
from .input import InputDriver


class ActionExecutor:
    def __init__(
        self,
        driver: InputDriver,
        hotkeys: Hotkeys,
        calibration: CalibrationConfig,
        preflight: Callable[[], None],
        action_timeout_seconds: float = 3.0,
    ):
        self.driver = driver
        self.hotkeys = hotkeys
        self.calibration = calibration
        self.preflight = preflight
        self.action_timeout_seconds = action_timeout_seconds

    def execute(self, action: Action) -> ActionResult:
        start = time.monotonic()
        try:
            if self.driver.live and action.type not in {ActionType.WAIT, ActionType.NO_OP}:
                self.preflight()
            self._execute(action)
            elapsed = time.monotonic() - start
            if elapsed > self.action_timeout_seconds:
                raise TimeoutError(f"action exceeded {self.action_timeout_seconds}s timeout")
            return ActionResult(
                action=action.type,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                message="dry-run" if not self.driver.live else "executed",
            )
        except Exception as exc:  # noqa: BLE001 - action failures must fail closed
            return ActionResult(
                action=action.type,
                success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                message=str(exc),
            )

    def _key(self, name: str) -> None:
        self.driver.key(self.hotkeys.get_required(name))

    def _resolve_position(self, position: tuple[float, float]) -> tuple[int, int]:
        x, y = position
        if 0 <= x <= 1 and 0 <= y <= 1:
            if self.driver.allowed_bounds is None:
                raise RuntimeError("target window bounds are unavailable")
            left, top, right, bottom = self.driver.allowed_bounds
            return (
                left + round((right - left) * x),
                top + round((bottom - top) * y),
            )
        return round(x), round(y)

    def _build(self, item: str, position: tuple[float, float]) -> None:
        self._key("select_idle_villager")
        self._key("build_menu")
        self._key(item)
        self.driver.click(*self._resolve_position(position))

    def _execute(self, a: Action) -> None:
        t = a.type
        if t in {ActionType.WAIT, ActionType.NO_OP}:
            return
        if t == ActionType.SELECT_TOWN_CENTER:
            self._key("select_town_center")
        elif t == ActionType.SELECT_IDLE_VILLAGER:
            self._key("select_idle_villager")
        elif t == ActionType.TRAIN_VILLAGER:
            self._key("select_town_center")
            self._key("train_villager")
        elif t == ActionType.BUILD_HOUSE:
            self._build("house", self.calibration.house_position)
        elif t == ActionType.BUILD_LUMBER_CAMP:
            self._build("lumber_camp", self.calibration.lumber_camp_position)
        elif t == ActionType.RESEARCH_FEUDAL:
            self._key("select_town_center")
            self._key("research_feudal")
        elif t in {ActionType.ASSIGN_TO_FOOD, ActionType.ASSIGN_TO_WOOD, ActionType.ASSIGN_TO_GOLD}:
            pos = {
                ActionType.ASSIGN_TO_FOOD: self.calibration.food_position,
                ActionType.ASSIGN_TO_WOOD: self.calibration.wood_position,
                ActionType.ASSIGN_TO_GOLD: self.calibration.gold_position,
            }[t]
            for _ in range(a.count or 1):
                self._key("select_idle_villager")
                self.driver.click(*self._resolve_position(pos))
        else:
            raise NotImplementedError(f"{t} has no safe deterministic executor yet")
