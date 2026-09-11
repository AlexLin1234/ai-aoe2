from types import SimpleNamespace

from PIL import Image

from aoe2bot.agent.client import Usage
from aoe2bot.agent.schemas import Action, ActionType, Plan, VisualState
from aoe2bot.capture.window import TargetWindow
from aoe2bot.config import EndGameConfig, load_config
from aoe2bot.endgame import EndGameAnalyzer, EndGameReviewService, GameReview, MemoryBank
from aoe2bot.perception.state import GameState
from aoe2bot.runtime.loop import BotLoop
from aoe2bot.runtime.safety import SafetyController


def sample_review() -> GameReview:
    return GameReview(
        result="loss",
        map_name="Arabia",
        player_civilization="Franks",
        opponent_civilizations=["Britons"],
        game_duration="31:04",
        summary="Feudal pressure was late after a weak food transition.",
        metrics=[],
        strengths=["Kept villager production active"],
        weaknesses=["Late military production"],
        priority_improvements=["Place the first military building by 10:30"],
        next_game_plan=["Scout the opponent before choosing the Feudal follow-up"],
        long_term_trends=["Military production starts late"],
    )


def test_memory_bank_records_jsonl_and_readable_overview(tmp_path):
    memory_path = tmp_path / "games.jsonl"
    overview_path = tmp_path / "overview.md"
    bank = MemoryBank(memory_path, overview_path)

    bank.record(sample_review())

    assert bank.load()[0]["review"]["result"] == "loss"
    overview = overview_path.read_text(encoding="utf-8")
    assert "Games reviewed: 1" in overview
    assert "Place the first military building by 10:30" in overview
    assert "Scout the opponent" in overview
    assert bank.load(0) == []


def test_analyzer_sends_all_labeled_frames_and_prior_memory():
    calls = []
    responses = SimpleNamespace(
        parse=lambda **kwargs: (
            calls.append(kwargs)
            or SimpleNamespace(output_parsed=sample_review(), status="completed")
        )
    )
    analyzer = EndGameAnalyzer(
        EndGameConfig(max_image_width=320, max_previous_games=2),
        api=SimpleNamespace(responses=responses),
    )

    review = analyzer.analyze(
        {
            "current": Image.new("RGB", (640, 360), "white"),
            "economy": Image.new("RGB", (640, 360), "gray"),
        },
        [{"summary": "older"}, {"summary": "previous"}],
    )

    assert review.result == "loss"
    assert calls[0]["store"] is False
    user_content = calls[0]["input"][1]["content"]
    assert sum(item["type"] == "input_image" for item in user_content) == 2
    assert "previous" in user_content[0]["text"]


def test_review_service_clicks_configured_normalized_graph_tabs(tmp_path):
    target = TargetWindow(1, "AoE2", 2, (100, 200, 1100, 800))

    class Windows:
        def require(self):
            return target

        def is_foreground(self, _target):
            return True

        def focus(self, _target):
            raise AssertionError("already foreground")

    class Capture:
        def capture(self, _target):
            return Image.new("RGB", (1000, 600), "black")

    class Driver:
        live = True

        def __init__(self):
            self.bounds = None
            self.clicks = []

        def set_allowed_bounds(self, bounds):
            self.bounds = bounds

        def click(self, x, y):
            self.clicks.append((x, y))

    driver = Driver()
    config = EndGameConfig(
        graph_tabs={"economy": (0.25, 0.5), "military": (0.75, 0.5)},
        memory_path=str(tmp_path / "games.jsonl"),
        overview_path=str(tmp_path / "overview.md"),
    )
    service = EndGameReviewService(
        config,
        Windows(),
        Capture(),
        driver,
        analyzer=SimpleNamespace(),
        sleeper=lambda _seconds: None,
    )

    frames = service.collect(Image.new("RGB", (1000, 600), "white"))

    assert list(frames) == ["current", "economy", "military"]
    assert driver.bounds == target.rect
    assert driver.clicks == [(350, 500), (850, 500)]


def test_bot_loop_triggers_review_and_stops_on_postgame(tmp_path):
    config = load_config("config/default.yaml")
    config.telemetry.path = str(tmp_path / "telemetry.jsonl")
    frame = Image.new("RGB", (320, 200), "black")
    plan = Plan(
        goal="review game",
        observed_state=VisualState(screen="postgame", confidence=1),
        actions=[Action(type=ActionType.WAIT)],
        recheck_after_seconds=0.5,
    )
    reviews = []

    windows = SimpleNamespace(require=lambda: object())
    capture = SimpleNamespace(capture=lambda _target: frame)
    reader = SimpleNamespace(read_state=lambda _frame: GameState())
    planner = SimpleNamespace(create_plan=lambda *_args: (plan, Usage()))
    executor = SimpleNamespace(
        driver=SimpleNamespace(live=False),
        execute=lambda _action: (_ for _ in ()).throw(AssertionError()),
    )

    class Telemetry:
        def __init__(self):
            self.rows = []

        def write(self, *args):
            self.rows.append(args)

    telemetry = Telemetry()
    BotLoop(
        config,
        windows,
        capture,
        reader,
        planner,
        executor,
        SafetyController(4, 0),
        telemetry,
        end_game_review=reviews.append,
    ).run()

    assert reviews == [frame]
    assert len(telemetry.rows) == 1
    assert "end_game_review_latency_ms" in telemetry.rows[0][3]
