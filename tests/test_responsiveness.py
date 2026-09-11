import base64
import io
from types import SimpleNamespace

from PIL import Image

from aoe2bot.agent.client import Usage
from aoe2bot.agent.planner import Planner
from aoe2bot.agent.schemas import Action, ActionType, Plan, VisualState
from aoe2bot.config import AgentConfig
from aoe2bot.control.input import InputDriver
from aoe2bot.perception.state import GameState
from aoe2bot.runtime.loop import executable_actions


class RecordingClient:
    image_url: str | None = None

    def request(self, system: str, text: str, image_url: str | None):
        self.image_url = image_url
        return (
            Plan(
                goal="wait",
                observed_state=VisualState(screen="gameplay", confidence=1),
                actions=[Action(type=ActionType.WAIT)],
                recheck_after_seconds=0.5,
            ),
            Usage(),
        )


def test_planner_honors_capture_width():
    client = RecordingClient()
    planner = Planner(
        AgentConfig(model="gpt-4o-mini"),
        client=client,
        max_image_width=640,
        image_quality=60,
    )

    planner.create_plan(GameState(), Image.new("RGB", (1920, 1080)), [], "test")

    assert client.image_url is not None
    encoded = client.image_url.split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.width == 640


def test_uncertain_or_paused_state_cannot_emit_live_actions():
    plan = Plan(
        goal="train",
        observed_state=VisualState(screen="paused", confidence=1),
        actions=[Action(type=ActionType.TRAIN_VILLAGER)],
        recheck_after_seconds=0.5,
    )

    assert executable_actions(plan, 0.55) == [Action(type=ActionType.WAIT)]


def test_input_rate_limit_waits_instead_of_dropping_batch():
    now = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    driver = InputDriver(False, 2, 0, clock=lambda: now[0], sleeper=sleep)
    driver._guard_rate()
    driver._guard_rate()
    driver._guard_rate()

    assert waits == [1.0]


def test_period_hotkey_uses_keyboard_period_not_numpad_decimal():
    constants = SimpleNamespace(VK_OEM_PERIOD=190, VK_DECIMAL=110, VK_ESCAPE=27)

    assert InputDriver.virtual_key_code(".", constants) == 190
    assert InputDriver.virtual_key_code("decimal", constants) == 110
