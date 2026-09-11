from __future__ import annotations
import logging
import time
from aoe2bot.agent.planner import Planner, PlannerError
from aoe2bot.capture.screenshot import ScreenshotCapture
from aoe2bot.capture.window import WindowManager
from aoe2bot.config import AppConfig
from aoe2bot.control.executor import ActionExecutor
from aoe2bot.perception.heuristics import StateReader
from aoe2bot.benchmarks.reach_feudal import ReachFeudalBenchmark
from .safety import SafetyController
from .telemetry import TelemetryWriter, UsageTracker

log = logging.getLogger(__name__)


class BotLoop:
    def __init__(
        self,
        config: AppConfig,
        windows: WindowManager,
        capture: ScreenshotCapture,
        reader: StateReader,
        planner: Planner,
        executor: ActionExecutor,
        safety: SafetyController,
        telemetry: TelemetryWriter,
    ):
        self.c = config
        self.windows = windows
        self.capture = capture
        self.reader = reader
        self.planner = planner
        self.executor = executor
        self.safety = safety
        self.telemetry = telemetry
        self.usage = UsageTracker()
        self.history: list[dict] = []

    def run(self, once: bool = False) -> None:
        benchmark = ReachFeudalBenchmark(time.time())
        while not self.safety.emergency_stopped:
            target = self.windows.require()  # disappearing window is a hard kill switch
            shot = self.capture.capture(target)
            state = self.reader.read_state(shot)
            benchmark.observe(state)
            if benchmark.complete(state):
                log.info("benchmark complete: %s", benchmark.metrics())
                return
            if not self.usage.can_call(
                self.c.agent.max_calls_per_game, self.c.budget.max_usd_per_game
            ):
                self.safety.paused = True
                log.error("LLM budget/call limit reached; bot paused")
                return
            try:
                plan, usage = self.planner.create_plan(
                    state, shot, self.history, benchmark.objective
                )
            except PlannerError:
                log.exception("invalid plan rejected; no fallback actions executed")
                plan = None
            results = []
            if plan:
                self.usage.record(
                    usage.input_tokens,
                    usage.output_tokens,
                    self.c.agent.input_usd_per_million_tokens,
                    self.c.agent.output_usd_per_million_tokens,
                )
                for action in self.safety.filter(plan.actions):
                    result = self.executor.execute(action)
                    results.append(result.model_dump(mode="json"))
                    self.history.append(
                        {
                            "action": action.model_dump(mode="json"),
                            "result": result.model_dump(mode="json"),
                        }
                    )
            self.telemetry.write(
                state.model_dump(mode="json"),
                {} if plan is None else plan.model_dump(mode="json"),
                results,
                {**benchmark.metrics(), **self.usage.model_dump()},
            )
            if once:
                return
            time.sleep(plan.recheck_after_seconds if plan else self.c.agent.default_recheck_seconds)
