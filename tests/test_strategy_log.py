import json
import re

import pytest

from aoe2bot.runtime.strategy_log import (
    PLACEHOLDER,
    TEMPLATE,
    build_payload,
    compact_cycle,
    load_records,
    render,
    split_runs,
)


def record(timestamp: float, calls: int, **overrides):
    body = {
        "timestamp": timestamp,
        "state": {},
        "plan": {
            "goal": "Reach Feudal Age",
            "observed_state": {"screen": "gameplay", "confidence": 0.8, "food": 200},
            "actions": [{"type": "TRAIN_VILLAGER"}],
            "recheck_after_seconds": 1.0,
        },
        "execution": [
            {"action": "TRAIN_VILLAGER", "success": True, "duration_ms": 120.4, "message": "sent"}
        ],
        "metrics": {"calls": calls, "planning_latency_ms": 900.6, "cycle_latency_ms": 1400.2},
    }
    body.update(overrides)
    return body


def test_malformed_lines_from_an_interrupted_run_are_skipped(tmp_path):
    log = tmp_path / "session.jsonl"
    log.write_text(
        json.dumps(record(1.0, 1))
        + "\n\n"
        + '{"timestamp": 2.0, "plan":\n'  # truncated mid-write
        + json.dumps(record(3.0, 2))
        + "\n",
        encoding="utf-8",
    )

    assert [r["timestamp"] for r in load_records(log)] == [1.0, 3.0]


def test_a_reset_call_counter_starts_a_new_run():
    # Two live runs back to back: the second BotLoop restarts its usage counter.
    cycles = [compact_cycle(record(t, c)) for t, c in ((10, 1), (20, 2), (30, 1), (40, 2))]

    runs = split_runs(cycles)

    assert [len(run["cycles"]) for run in runs] == [2, 2]
    assert [run["id"] for run in runs] == [1, 2]
    assert runs[0]["start"] == 10 and runs[0]["end"] == 20
    assert runs[1]["start"] == 30


def test_a_long_silence_starts_a_new_run_even_when_calls_keep_climbing():
    cycles = [compact_cycle(record(t, c)) for t, c in ((10, 1), (20, 2), (5000, 3))]

    assert [len(run["cycles"]) for run in split_runs(cycles)] == [2, 1]


def test_consecutive_cycles_of_one_run_stay_together():
    cycles = [compact_cycle(record(t, c)) for t, c in ((10, 1), (14, 2), (19, 3))]

    runs = split_runs(cycles)

    assert len(runs) == 1
    assert runs[0]["calls"] == 3


def test_cycle_keeps_the_decision_the_reading_and_the_outcome():
    cycle = compact_cycle(record(10, 1))

    assert cycle["goal"] == "Reach Feudal Age"
    assert cycle["screen"] == "gameplay" and cycle["conf"] == 0.8
    assert cycle["food"] == 200
    assert cycle["planned"] == ["TRAIN_VILLAGER"]
    assert cycle["done"] == [{"type": "TRAIN_VILLAGER", "ok": True, "ms": 120.4, "msg": "sent"}]
    assert cycle["plan_ms"] == 901 and cycle["cycle_ms"] == 1400


def test_a_rejected_plan_still_produces_a_cycle_with_no_actions():
    # The loop writes telemetry with an empty plan when validation rejects it.
    cycle = compact_cycle({"timestamp": 5.0, "plan": {}, "execution": [], "metrics": {}})

    assert cycle["goal"] is None
    assert cycle["planned"] == [] and cycle["done"] == []


def test_rendered_report_is_self_contained_and_replaces_the_placeholder():
    payload = build_payload([record(10, 1), record(14, 2)])

    html = render(payload)

    assert PLACEHOLDER not in html
    embedded = re.search(
        r'<script type="application/json" id="payload">(.*?)</script>', html, re.DOTALL
    ).group(1)
    restored = json.loads(embedded)
    assert [len(run["cycles"]) for run in restored["runs"]] == [2]
    assert restored["runs"][0]["cycles"][0]["goal"] == "Reach Feudal Age"


def test_payload_can_never_close_the_script_element_that_carries_it():
    hostile = record(10, 1)
    hostile["plan"]["goal"] = "</script><script>alert(1)</script>"

    html = render(build_payload([hostile]))

    # The text survives as inert JSON data; what must not survive is any markup.
    # Exactly the page's own two script elements exist, opened and closed.
    assert len(re.findall(r"<script", html)) == 2
    assert len(re.findall(r"</script>", html)) == 2
    assert "<script>alert" not in html
    embedded = re.search(
        r'<script type="application/json" id="payload">(.*?)</script>', html, re.DOTALL
    ).group(1)
    assert json.loads(embedded)["runs"][0]["cycles"][0]["goal"] == hostile["plan"]["goal"]


def test_template_ships_with_the_package():
    assert TEMPLATE.exists()
    assert PLACEHOLDER in TEMPLATE.read_text(encoding="utf-8")


def test_render_refuses_a_template_without_the_placeholder(tmp_path):
    broken = tmp_path / "broken.html"
    broken.write_text("<title>no slot</title>", encoding="utf-8")

    with pytest.raises(ValueError, match=PLACEHOLDER):
        render(build_payload([record(10, 1)]), broken)
