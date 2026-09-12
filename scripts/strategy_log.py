"""Render the strategy-log dashboard from a telemetry JSONL.

Shows every high-level call the strategist made, what it saw at the time, and
whether the controller landed the resulting input.

    python scripts/strategy_log.py
    python scripts/strategy_log.py --input logs/session.jsonl --output logs/strategy_log.html
"""

from __future__ import annotations

import argparse

from aoe2bot.config import load_config
from aoe2bot.runtime.strategy_log import write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--input", default=None, help="defaults to the configured telemetry path")
    parser.add_argument("--output", default="logs/strategy_log.html")
    args = parser.parse_args()

    telemetry = args.input or load_config(args.config).telemetry.path
    destination, payload = write_report(telemetry, args.output)

    runs = payload["runs"]
    cycles = sum(len(run["cycles"]) for run in runs)
    actions = sum(len(cycle["done"]) for run in runs for cycle in run["cycles"])
    failed = sum(
        1 for run in runs for cycle in run["cycles"] for done in cycle["done"] if not done["ok"]
    )
    print(f"Read {cycles} cycles across {runs and len(runs)} runs from {telemetry}")
    print(f"{actions} actions executed, {failed} failed")
    print(f"Wrote {destination}; open it in a browser.")


if __name__ == "__main__":
    main()
