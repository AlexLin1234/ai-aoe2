"""Build the strategy-log dashboard from the telemetry JSONL.

The dashboard is a single self-contained HTML file: the shaped telemetry is
inlined into the template, so the report can be opened or shared without the
repository, a server, or the original log.

    python scripts/strategy_log.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATE = Path(__file__).with_name("strategy_log.html")
PLACEHOLDER = "__PAYLOAD__"

# Telemetry is appended across runs. The planner's call counter resets with each
# BotLoop, so a counter that fails to advance -- or a long silence -- starts a
# new run rather than a new cycle of the old one.
NEW_RUN_GAP_SECONDS = 300


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """Parse telemetry, skipping partial lines from an interrupted run."""
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def compact_cycle(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only what the dashboard renders, with short keys to stay small."""
    plan = record.get("plan") or {}
    observed = plan.get("observed_state") or {}
    metrics = record.get("metrics") or {}
    return {
        "t": record.get("timestamp"),
        "goal": plan.get("goal"),
        "screen": observed.get("screen"),
        "conf": observed.get("confidence"),
        "age": observed.get("age"),
        "pop": observed.get("population_current"),
        "cap": observed.get("population_cap"),
        "food": observed.get("food"),
        "wood": observed.get("wood"),
        "gold": observed.get("gold"),
        "stone": observed.get("stone"),
        "notes": (observed.get("notes") or [])[:2],
        "planned": [a.get("type") for a in (plan.get("actions") or [])],
        "done": [
            {
                "type": result.get("action"),
                "ok": bool(result.get("success")),
                "ms": round(result.get("duration_ms") or 0, 1),
                "msg": result.get("message") or "",
            }
            for result in (record.get("execution") or [])
        ],
        "plan_ms": round(metrics.get("planning_latency_ms") or 0),
        "cycle_ms": round(metrics.get("cycle_latency_ms") or 0),
        "calls": metrics.get("calls"),
        "cost": metrics.get("estimated_cost_usd"),
        "recheck": plan.get("recheck_after_seconds"),
    }


def split_runs(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for cycle in cycles:
        starts_run = True
        if runs:
            previous = runs[-1]["cycles"][-1]
            gap = (cycle.get("t") or 0) - (previous.get("t") or 0)
            starts_run = (cycle.get("calls") or 0) <= (previous.get("calls") or 0) or (
                gap > NEW_RUN_GAP_SECONDS
            )
        if starts_run:
            runs.append({"cycles": []})
        runs[-1]["cycles"].append(cycle)

    for index, run in enumerate(runs, start=1):
        first, last = run["cycles"][0], run["cycles"][-1]
        run["id"] = index
        run["start"] = first.get("t")
        run["end"] = last.get("t")
        run["cost"] = last.get("cost") or 0
        run["calls"] = last.get("calls") or len(run["cycles"])
    return runs


def build_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    cycles = [compact_cycle(record) for record in records]
    generated = max((c.get("t") or 0 for c in cycles), default=0)
    return {"generated": generated, "runs": split_runs(cycles)}


def render(payload: dict[str, Any], template: str | Path = TEMPLATE) -> str:
    data = json.dumps(payload, separators=(",", ":"), default=str)
    # The payload is inlined into a <script> element, so nothing in it may be
    # able to close that element. "<" only ever occurs inside a JSON string, so
    # escaping it keeps the document valid and the JSON unchanged.
    data = data.replace("<", "\\u003c").replace("\u2028", "").replace("\u2029", "")
    body = Path(template).read_text(encoding="utf-8")
    if PLACEHOLDER not in body:
        raise ValueError(f"template {template} has no {PLACEHOLDER} placeholder")
    return body.replace(PLACEHOLDER, data)


def write_report(
    telemetry: str | Path = "logs/session.jsonl",
    output: str | Path = "logs/strategy_log.html",
    template: str | Path = TEMPLATE,
) -> tuple[Path, dict[str, Any]]:
    payload = build_payload(load_records(telemetry))
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(payload, template), encoding="utf-8")
    return destination, payload
