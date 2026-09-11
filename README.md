# Astra AoE2 Controller

A Windows prototype in which an LLM makes **strategic, semantic decisions** and a guarded local controller performs deterministic Age of Empires II: Definitive Edition input. The initial `reach_feudal` benchmark starts in Dark Age and targets reliable villager production, houses, food/wood gathering, a lumber camp, and Feudal research. Combat is deliberately out of scope for v0.1.

> **Warning:** live UI automation can misclick when resolution, window placement, hotkeys, or calibration are wrong. Start with dry-run, inspect telemetry, calibrate at the exact fixed resolution, and keep **F12** ready. Live mode is double opt-in and refuses unidentified/non-foreground windows and out-of-window clicks.

## Architecture

```text
AoE2 DE window
  -> Win32-identified window + MSS screenshot
  -> modular StateReader -> compact extensible GameState
  -> fast vision model -> compact observed state + batched semantic plan
  -> validated Plan[semantic Action]
  -> cooldown / cycle / budget / emergency safety gates
  -> deterministic ActionExecutor -> rate-limited Win32 input -> AoE2
                         |
                         +-> JSONL telemetry and benchmark metrics
```

The boundary is intentional: the model cannot supply coordinates, keys, Python, or shell commands. It can only produce Pydantic-validated allowlisted actions. Coordinates and hotkeys are local configuration. Invalid model output results in no fallback execution.

Core interfaces do not terminate at Feudal: `GameState` already has extension points for entities, map/resource knowledge, groups, enemy observations, upgrades, queues, hypotheses, objectives, and threats. Benchmark completion exists only in `benchmarks/reach_feudal.py`. Future economy, construction, production, scouting, military micro, camera, and control-group managers can consume goals such as `maintain_army(...)` or `raid(...)` without turning the strategist into a mouse driver.

## Requirements and installation

- Windows 10/11, Python 3.12+, AoE2 DE in windowed/borderless mode
- A fixed resolution and stable UI scale
- Visual C++ compatible wheels for the listed Python packages

```powershell
cd C:\path\to\ai-aoe2
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Choose an OpenAI model available to your account in `config/default.yaml`. Set per-million-token pricing there if cost estimates are desired; zero means cost is tracked as unknown/zero rather than guessed.

## Configuration and calibration

1. `config/hotkeys.yaml` ships the full Definitive Edition default set, generated from the game's own `resources/_common/dat/hotkeys.json`. If you play on those defaults there is nothing to do; otherwise edit the entries you rebound, or regenerate from another preset with `python scripts/generate_hotkeys.py --preset "left handed"`.
2. Start a standard game at the intended resolution and keep the window visible.
3. Run `python scripts/calibrate.py`. It positively identifies the configured title **and process**, writes `calibration.png`, records resolution/regions/positions in `config/calibration.local.yaml`, and sends no input.
4. Inspect the screenshot. Update `config/default.yaml` with safe **window-relative coordinates** for a house, nearby woodline, food, wood, and gold. Each axis ranges from `0.0` at the left/top to `1.0` at the right/bottom. The prototype does not yet merge the local calibration file automatically.
5. Re-run calibration whenever window placement, resolution, UI scale, map, or hotkeys change. Placement points are map-dependent in v0.1.

The configurable normalized screenshot regions are the resource bar, command panel, and minimap. `crop_regions` also returns the full current frame. The local v1 parser deliberately leaves values unknown until dependable OCR/templates are configured. The vision response separately records a compact reading of the visible screen, resources, population, age, selection, and command availability. Live actions are suppressed unless it identifies active gameplay with sufficient confidence.

## Run

Dry-run is the default and captures/plans/logs without keyboard or mouse input:

```powershell
python -m aoe2bot.main --dry-run
# One planner/capture cycle for validation:
python -m aoe2bot.main --dry-run --once --verbose
```

For live input, first set `input.live_enabled: true` in a reviewed config, then explicitly pass `--live`:

```powershell
python -m aoe2bot.main --live
```

F12 is the global emergency stop; F11 toggles pause/resume. Closing the target window activates the runtime kill path. The bot never brings AoE2 to the front itself and has no code that can: click into the game to hand it control, and click away to take control back — it stops capturing, planning, and sending input within `window.foreground_poll_seconds` and resumes when the game is in front again. Live actions re-identify AoE2 and re-verify it is foreground before each semantic action, and again immediately before each individual keystroke or click, so switching windows mid-batch drops the rest of the batch instead of typing it into your window. With `input.auto_resume: true`, a detected pause/menu overlay is closed using the configured `stop` key before the next capture. Clicks outside its current rectangle are rejected. `--live` without the config opt-in is rejected.

## End-game memory bank

When the planner recognizes an AoE2 post-game or statistics screen, the loop stops issuing gameplay actions, analyzes the visible statistics, and appends a structured review to `memory_bank/games.jsonl`. It also rewrites `memory_bank/overview.md` with the current priorities, recurring trends, and a concrete plan for the next game. Prior reviews are included in the next analysis so the advice can track repeated problems. These generated files are ignored by Git.

If automatic detection misses the screen, leave the post-game statistics visible and run:

```powershell
python -m aoe2bot.main --analyze-end-game
```

The current page is always captured. To collect several graph pages automatically, add their window-relative tab positions to `end_game.graph_tabs` in `config/default.yaml`. Coordinates range from `0.0` at the window's left/top edge to `1.0` at its right/bottom edge:

```yaml
end_game:
  graph_tabs:
    economy: [0.42, 0.18]
    military: [0.52, 0.18]
```

The manual command clicks configured tabs only when `input.live_enabled` is true. During normal play, tab collection occurs only in `--live` mode. Screenshots are resized, sent for analysis, and kept in memory; they are not saved to disk. Set `end_game.player_name` when a team game or graph shows several players. The text-only memory paths, model, image quality, tab delay, and number of prior games are configurable under `end_game`.

To run the benchmark, set `benchmark.name: reach_feudal` (the default), calibrate, and invoke live mode. It records time-to-Feudal when perception reports the new age, planner calls, action results, population-cap transitions, token estimates, and estimated cost in `logs/session.jsonl`.

## Cost and safety controls

`agent.max_calls_per_game`, `agent.max_output_tokens`, `agent.max_actions_per_plan`, and `budget.max_usd_per_game` bound model use. Only the newest optionally-downscaled screenshot, compact state JSON, and eight recent action results are sent. There is no growing chat transcript. Reaching call or dollar limits pauses the loop and prevents another call.

Input safety additionally includes positive title/process identification, per-event foreground validation that fails closed, F12 stop, F11 pause, per-cycle action limits, duplicate cooldown, confidence and gameplay-screen gates, rate-limited batches, configurable action timeout, and out-of-window click rejection. When a batch reaches the event-rate limit, it waits for capacity instead of discarding the remaining commands. The timeout is currently configuration groundwork; individual Win32 calls are synchronous and short.

## Tests

Tests are platform-independent and do not need AoE2 or an API key:

```powershell
pytest
ruff check .
```

## Current limitations

- Local perception is a conservative scaffold with no bundled OCR/templates. The API vision reading supplies compact visible state for planning, but action verification, TC idle time, and win/loss detection still need local calibrated detectors.
- Fixed desktop placement points are map/window-position dependent; lumber/food targeting is not inferred from terrain yet.
- `SCOUT_DIRECTION` is schema-valid but intentionally fails closed because safe camera-relative execution is not implemented.
- Only one TC and basic Dark Age actions have deterministic recipes; hotkeys vary by user/profile and Feudal hotkey availability is not visually verified.
- Window identification supports Windows only. The loop needs a running visible AoE2 window even in dry-run.
- F11/F12 monitoring uses polling rather than registered system hotkeys; action timeout is not yet enforced around a worker.
- Benchmark quality metrics are extensible placeholders and depend on future perception signals.
- Automatic post-game detection depends on the planner's visual classification. Use `--analyze-end-game` when it misses a statistics screen, and calibrate `end_game.graph_tabs` for the current resolution and UI scale to collect more than the visible page.

## Next three highest-value improvements

1. **Reliable calibrated perception:** digit/template detection for resources, population, age, selection/queue state, buttons, and action verification with confidence and recorded fixture tests.
2. **Spatial world model and placement:** minimap/camera transforms, resource/woodline detection, building footprints, safe placement search, and entity tracking across frames.
3. **Goal-driven managers:** economy/construction/production/scouting managers with queue-aware feedback, then generalized macro goals, multi-TC/all-age build orders, opponents, combat groups, and win/loss state.

## Repository layout

```text
config/                 defaults and user-editable hotkeys
scripts/                safe calibration and dry-run entry points
src/aoe2bot/agent/      prompt, schemas, OpenAI client, planner
src/aoe2bot/capture/    Win32 target discovery and MSS capture
src/aoe2bot/perception/ extensible state, regions, heuristic/template seams
src/aoe2bot/control/    guarded input and deterministic action recipes
src/aoe2bot/runtime/    loop, hotkeys, safety, cost usage, telemetry
src/aoe2bot/endgame.py  multi-page post-game analysis and improvement memory
src/aoe2bot/benchmarks/ benchmark-owned completion and metrics
tests/                  platform-independent unit tests
```
