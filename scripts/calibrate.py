from __future__ import annotations
import argparse
from pathlib import Path
import yaml
from aoe2bot.capture.screenshot import ScreenshotCapture
from aoe2bot.capture.window import WindowManager
from aoe2bot.config import load_config
from aoe2bot.utils.dpi import enable_per_monitor_dpi_awareness


def main() -> None:
    enable_per_monitor_dpi_awareness()
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--output", default="config/calibration.local.yaml")
    p.add_argument("--screenshot", default="calibration.png")
    args = p.parse_args()
    config = load_config(args.config)
    target = WindowManager(config.window.title_contains, config.window.process_names).require()
    image = ScreenshotCapture().capture(target)
    image.save(args.screenshot)
    payload = {
        "resolution": [image.width, image.height],
        "window_rect": list(target.rect),
        "client_rect": list(target.capture_rect),
        "regions": config.capture.regions,
        "house_position": list(config.calibration.house_position),
        "lumber_camp_position": list(config.calibration.lumber_camp_position),
        "food_position": list(config.calibration.food_position),
        "wood_position": list(config.calibration.wood_position),
        "gold_position": list(config.calibration.gold_position),
    }
    Path(args.output).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    print(
        f"Captured {target.title!r} at {image.size}; inspect {args.screenshot} and edit {args.output}. No input was sent."
    )


if __name__ == "__main__":
    main()
