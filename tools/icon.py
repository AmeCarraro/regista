"""Draws the icon of Regista.exe, tools\\regista.ico, as the page's logo is drawn (web\\public\\favicon.svg):
a square with round corners in a slanting gradient, and a white star of four points.

    .venv\\Scripts\\python.exe tools\\icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

# the logo is drawn on 32 units; this many pixels each, then made smaller, which smooths its edges
UNIT = 32
SIDE = 32 * UNIT
STOPS = [(0.0, (0xFF, 0x8A, 0x5B)), (0.55, (0xE0, 0x52, 0xA0)), (1.0, (0x7A, 0x5C, 0xFF))]
STAR = [(16, 7.5), (18.3, 13.7), (24.5, 16), (18.3, 18.3), (16, 24.5), (13.7, 18.3), (7.5, 16), (13.7, 13.7)]


def colour(at: float) -> tuple[int, int, int]:
    for (start, first), (end, last) in zip(STOPS, STOPS[1:]):
        if at <= end:
            share = (at - start) / (end - start)
            return tuple(round(a + (b - a) * share) for a, b in zip(first, last))
    return STOPS[-1][1]


def drawn() -> Image.Image:
    # the gradient runs from the top left corner of the square to the bottom right one
    low, high = 2 * UNIT, 30 * UNIT
    gradient = Image.new("RGB", (SIDE, SIDE))
    pixels = gradient.load()
    for y in range(SIDE):
        for x in range(SIDE):
            at = min(max(((x - low) + (y - low)) / (2 * (high - low)), 0.0), 1.0)
            pixels[x, y] = colour(at)
    shape = Image.new("L", (SIDE, SIDE), 0)
    ImageDraw.Draw(shape).rounded_rectangle((low, low, high, high), radius=9 * UNIT, fill=255)
    logo = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
    logo.paste(gradient, mask=shape)
    ImageDraw.Draw(logo).polygon([(x * UNIT, y * UNIT) for x, y in STAR], fill=(255, 255, 255, 255))
    return logo


if __name__ == "__main__":
    target = Path(__file__).with_name("regista.ico")
    drawn().resize((256, 256), Image.LANCZOS).save(target, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"{target}: {target.stat().st_size // 1024} KB")
