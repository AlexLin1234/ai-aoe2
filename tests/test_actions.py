from types import SimpleNamespace

from aoe2bot.agent.schemas import Action, ActionType
from aoe2bot.config import CalibrationConfig
from aoe2bot.control.executor import ActionExecutor
from aoe2bot.runtime.safety import SafetyController
from aoe2bot.runtime.telemetry import UsageTracker


def test_max_actions_and_duplicate_cooldown():
    now = [10.0]
    safety = SafetyController(2, 5, lambda: now[0])
    actions = [
        Action(type="TRAIN_VILLAGER"),
        Action(type="BUILD_HOUSE"),
        Action(type="BUILD_LUMBER_CAMP"),
    ]
    assert len(safety.filter(actions)) == 2
    assert safety.filter(actions) == []
    now[0] = 16
    assert len(safety.filter(actions)) == 2


def test_pause_and_emergency_stop():
    safety = SafetyController(4, 1)
    safety.toggle_pause()
    assert safety.filter([Action(type="WAIT")]) == []
    safety.toggle_pause()
    safety.emergency_stop()
    safety.toggle_pause()
    assert safety.paused and safety.emergency_stopped


def test_budget_and_call_stop_behavior():
    usage = UsageTracker()
    assert usage.can_call(2, 3)
    usage.record(1_000_000, 500_000, 1, 2)
    assert usage.estimated_cost_usd == 2
    usage.record(1, 1, 0, 0)
    assert not usage.can_call(2, 3)


def test_executor_resolves_normalized_positions_inside_current_window():
    driver = SimpleNamespace(allowed_bounds=(100, 200, 1100, 800))
    executor = ActionExecutor(
        driver,
        SimpleNamespace(),
        CalibrationConfig(
            house_position=(0.3, 0.7),
            lumber_camp_position=(0.2, 0.2),
            food_position=(0.4, 0.4),
            wood_position=(0.5, 0.5),
            gold_position=(0.6, 0.6),
        ),
        lambda: None,
    )

    assert executor._resolve_position((0.3, 0.7)) == (400, 620)


def test_resource_assignment_right_clicks_target():
    class Driver:
        live = True
        allowed_bounds = (100, 200, 1100, 800)

        def __init__(self):
            self.keys = []
            self.left_clicks = []
            self.right_clicks = []

        def key(self, key):
            self.keys.append(key)

        def click(self, x, y):
            self.left_clicks.append((x, y))

        def right_click(self, x, y):
            self.right_clicks.append((x, y))

    driver = Driver()
    executor = ActionExecutor(
        driver,
        SimpleNamespace(get_required=lambda name: {"select_idle_villager": "."}[name]),
        CalibrationConfig(
            house_position=(0.3, 0.7),
            lumber_camp_position=(0.2, 0.2),
            food_position=(0.4, 0.4),
            wood_position=(0.35, 0.48),
            gold_position=(0.6, 0.6),
        ),
        lambda: None,
    )

    executor._execute(Action(type=ActionType.ASSIGN_TO_WOOD))

    assert driver.keys == ["."]
    assert driver.left_clicks == []
    assert driver.right_clicks == [(450, 488)]
