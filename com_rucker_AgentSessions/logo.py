"""
The plugin's spark-style starburst, drawn with Pillow, and the per-agent
badges on session keys: each agent's logo (assets/<agent>.png, rendered from
the SVGs by tools/render_agent_logos.py) on a white disc.
"""

import math
import os
from functools import lru_cache

from PIL import Image, ImageDraw

ASSETS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets")

SPARK_ORANGE = (217, 119, 87)
SPARK_CREAM = (250, 249, 245)

# Ray lengths (fraction of the radius), deliberately uneven so it reads as a
# hand-drawn spark rather than a mechanical asterisk.
RAYS = [1.00, 0.78, 0.92, 0.70, 0.96, 0.82, 0.88, 0.72, 0.98, 0.76, 0.90, 0.80]

CANVAS = 1024  # drawn large and downsampled, since Pillow doesn't anti-alias
OUTPUT = 256


def _draw_spark(color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = CANVAS / 2
    radius = CANVAS * 0.44
    root_half_width = CANVAS * 0.05
    tip_half_width = CANVAS * 0.032
    fill = (*color, 255)

    for i, length in enumerate(RAYS):
        angle = 2 * math.pi * i / len(RAYS) - math.pi / 2
        tip = radius * length - tip_half_width
        # Each ray is a blunt, slightly tapered bar with a round cap.
        dx, dy = math.cos(angle), math.sin(angle)
        px, py = -dy, dx
        tx, ty = center + dx * tip, center + dy * tip
        draw.polygon([
            (center + px * root_half_width, center + py * root_half_width),
            (tx + px * tip_half_width, ty + py * tip_half_width),
            (tx - px * tip_half_width, ty - py * tip_half_width),
            (center - px * root_half_width, center - py * root_half_width),
        ], fill=fill)
        r = tip_half_width
        draw.ellipse([tx - r, ty - r, tx + r, ty + r], fill=fill)

    core = CANVAS * 0.1
    draw.ellipse([center - core, center - core, center + core, center + core], fill=fill)
    return img.resize((OUTPUT, OUTPUT), Image.LANCZOS)


@lru_cache(maxsize=None)
def _base_logo() -> Image.Image:
    return _draw_spark(SPARK_ORANGE)


@lru_cache(maxsize=None)
def logo(opacity: float = 1.0, tint: tuple[int, int, int] | None = None) -> Image.Image:
    """
    The logo as an RGBA image. `tint` recolors it as a solid silhouette (so it
    stays visible on an orange or red key); `opacity` fades it (empty keys).
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
