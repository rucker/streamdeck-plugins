"""
The plugin's mark, a robot head drawn with Pillow, and the per-agent badges on
session keys: each agent's logo (assets/<agent>.png, rendered from the SVGs by
tools/render_agent_logos.py) on a white disc.
"""

import os
from functools import lru_cache

from PIL import Image, ImageDraw

ASSETS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets")

ROBOT_STEEL = (196, 204, 216)
ROBOT_DARK = (24, 24, 24)

CANVAS = 1024  # drawn large and downsampled, since Pillow doesn't anti-alias
OUTPUT = 256


def _draw_robot(color: tuple[int, int, int]) -> Image.Image:
    """
    A robot head with an antenna and ears, in a 100×100 grid scaled to the
    canvas. The eyes and mouth are holes. Same geometry as render.ts.
    """
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    k = CANVAS / 100
    fill, hole = (*color, 255), (0, 0, 0, 0)

    def box(x, y, w, h):
        return [x * k, y * k, (x + w) * k, (y + h) * k]

    draw.rounded_rectangle(box(14, 24, 72, 60), radius=14 * k, fill=fill)
    draw.ellipse(box(44, 3, 12, 12), fill=fill)
    draw.rectangle(box(47, 12, 6, 13), fill=fill)
    draw.rounded_rectangle(box(5, 44, 10, 22), radius=3 * k, fill=fill)
    draw.rounded_rectangle(box(85, 44, 10, 22), radius=3 * k, fill=fill)
    draw.ellipse(box(28, 42, 16, 16), fill=hole)
    draw.ellipse(box(56, 42, 16, 16), fill=hole)
    draw.rounded_rectangle(box(33, 66, 34, 8), radius=4 * k, fill=hole)
    return img.resize((OUTPUT, OUTPUT), Image.LANCZOS)


@lru_cache(maxsize=None)
def _base_logo() -> Image.Image:
    return _draw_robot(ROBOT_STEEL)


@lru_cache(maxsize=None)
def logo(opacity: float = 1.0, tint: tuple[int, int, int] | None = None) -> Image.Image:
    """
    The logo as an RGBA image. `tint` recolors it as a solid silhouette (dark on
    light keys); `opacity` fades it (empty keys).
    """
    image = _base_logo().copy()
    alpha = image.getchannel("A")
    if tint is not None:
        image = Image.new("RGBA", image.size, (*tint, 255))
    if opacity < 1.0:
        alpha = alpha.point(lambda a: int(a * opacity))
    image.putalpha(alpha)
    return image


@lru_cache(maxsize=None)
def agent_badge(agent: str, ringed: bool = False) -> Image.Image | None:
    """
    The agent's logo on a white disc, which keeps every logo legible, unaltered,
    on any key color; `ringed` outlines the disc for light keys. None for an
    agent without a logo.
    """
    try:
        with Image.open(os.path.join(ASSETS, f"{agent}.png")) as agent_logo:
            mark = agent_logo.convert("RGBA")
    except OSError:
        return None
    badge = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ring = dict(outline=(24, 24, 24, 255), width=round(CANVAS / 18)) if ringed else {}
    ImageDraw.Draw(badge).ellipse([0, 0, CANVAS - 1, CANVAS - 1], fill=(255, 255, 255, 255), **ring)
    size = round(CANVAS * 0.64)
    offset = (CANVAS - size) // 2
    badge.alpha_composite(mark.resize((size, size), Image.LANCZOS), (offset, offset))
    return badge.resize((OUTPUT, OUTPUT), Image.LANCZOS)
