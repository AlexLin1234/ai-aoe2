from PIL import Image, ImageDraw

from aoe2bot.config import load_config
from aoe2bot.perception.motion import moved_fraction


def _frame(color: str = "grey") -> Image.Image:
    return Image.new("RGB", (1920, 1080), color)


def test_a_frozen_world_reads_as_no_motion():
    assert moved_fraction(_frame(), _frame()) == 0


def test_the_mouse_cursor_alone_is_not_motion():
    threshold = load_config("config/default.yaml").input.auto_resume_motion_threshold
    after = _frame()
    ImageDraw.Draw(after).polygon([(600, 400), (600, 430), (620, 420)], fill="white")

    # A pause overlay freezes everything but the cursor, and the cursor must not
    # be mistaken for a live game, or a real overlay would never be cleared.
    assert moved_fraction(_frame(), after) < threshold


def test_units_moving_in_the_world_read_as_a_running_game():
    threshold = load_config("config/default.yaml").input.auto_resume_motion_threshold
    after = _frame()
    draw = ImageDraw.Draw(after)
    for index in range(8):
        draw.ellipse((200 + index * 140, 500, 230 + index * 140, 545), fill="white")

    assert moved_fraction(_frame(), after) > threshold


def test_a_resized_window_is_still_comparable():
    assert moved_fraction(_frame(), Image.new("RGB", (1280, 720), "grey")) == 0
