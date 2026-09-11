import pytest
from pydantic import ValidationError

from aoe2bot.agent.planner import Planner, PlannerError
from aoe2bot.agent.schemas import Action, ActionType


def test_action_validation():
    assert Action(type="ASSIGN_TO_WOOD", count=2).type is ActionType.ASSIGN_TO_WOOD


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "RUN_SHELL"},
        {"type": "SCOUT_DIRECTION"},
        {"type": "BUILD_HOUSE", "count": 2},
        {"type": "WAIT", "direction": "north"},
    ],
)
def test_invalid_action_rejected(payload):
    with pytest.raises(ValidationError):
        Action.model_validate(payload)


def test_planner_parses_valid_result():
    plan = Planner.parse(
        '{"goal":"stay safe","actions":[{"type":"WAIT"}],"recheck_after_seconds":2}'
    )
    assert plan.actions[0].type is ActionType.WAIT


def test_planner_rejects_non_schema_result():
    with pytest.raises(PlannerError):
        Planner.parse('{"actions":[{"type":"click","x":1}]}')
