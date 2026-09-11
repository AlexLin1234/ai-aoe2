from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from aoe2bot.agent.client import StructuredAgentClient, _PlanOutput
from aoe2bot.config import AgentConfig


def test_fast_model_output_budget_is_compact():
    config = AgentConfig(model="gpt-4o-mini")

    assert config.max_output_tokens == 768


def test_incomplete_response_reports_api_reason():
    response = SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        error=None,
        output_parsed=None,
    )
    api = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kwargs: response))
    client = StructuredAgentClient.__new__(StructuredAgentClient)
    client.model = "gpt-5-mini"
    client.max_output_tokens = 300
    client.client = api

    with pytest.raises(
        ValueError,
        match=r"status=incomplete, reason=max_output_tokens, max_output_tokens=300",
    ):
        client.request("system", "state", None)


def test_api_schema_rejects_parameters_for_wait_action():
    with pytest.raises(ValidationError):
        _PlanOutput.model_validate(
            {
                "goal": "wait for reliable state",
                "observed_state": {"screen": "gameplay", "confidence": 1},
                "actions": [{"type": "WAIT", "count": 5, "direction": None}],
                "recheck_after_seconds": 5,
            }
        )
