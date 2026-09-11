from aoe2bot.agent.schemas import Action
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
