from __future__ import annotations

from PIL import Image, ImageChops

# Both frames are reduced to this width before they are compared. A walking
# villager or a ticking resource counter still moves whole pixels at this size;
# the mouse cursor and single-pixel UI edges do not.
COMPARISON_WIDTH = 96
# Grey levels a downscaled pixel must move before it counts as changed, so JPEG
# noise and the game's subtle lighting drift are not mistaken for a live world.
PIXEL_TOLERANCE = 12


def _thumbnail(image: Image.Image) -> Image.Image:
    height = max(1, round(COMPARISON_WIDTH * image.height / max(1, image.width)))
    return image.convert("L").resize((COMPARISON_WIDTH, height), Image.BILINEAR)


def moved_fraction(before: Image.Image, after: Image.Image) -> float:
    """Share of the frame that visibly changed between two captures, 0.0 to 1.0.

    An in-game pause or menu overlay freezes the world behind it, so two frames
    seconds apart are all but identical and this stays near zero. Live gameplay
    never is: villagers, counters and the idle-villager indicator all move. The
    loop uses that to tell a real overlay from a stale or misread classification
    before it sends the Escape that would toggle a pause menu *open*.
    """
    first = _thumbnail(before)
    second = _thumbnail(after)
    if first.size != second.size:
        # A resized window mid-cycle is a change in itself, but compare what can
        # be compared rather than reporting a meaningless number.
        second = second.resize(first.size, Image.BILINEAR)
    difference = ImageChops.difference(first, second)
    changed = sum(1 for value in difference.getdata() if value > PIXEL_TOLERANCE)
    return changed / max(1, first.width * first.height)
