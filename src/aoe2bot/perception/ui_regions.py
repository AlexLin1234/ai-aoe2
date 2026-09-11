from PIL import Image


def crop_regions(
    image: Image.Image, regions: dict[str, dict[str, float]]
) -> dict[str, Image.Image]:
    out = {"full": image}
    for name, r in regions.items():
        x, y, w, h = r["x"], r["y"], r["width"], r["height"]
        out[name] = image.crop(
            (
                int(x * image.width),
                int(y * image.height),
                int((x + w) * image.width),
                int((y + h) * image.height),
            )
        )
    return out
