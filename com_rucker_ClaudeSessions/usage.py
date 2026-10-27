"""
Your plan's usage limits (5-hour and weekly), as recorded by the status line
command in ../hooks/claude_deck_statusline.py, and the meter image for them.

The numbers are what Claude Code last heard from the API, so they only move
while a Claude Code session is talking to it; usage elsewhere (claude.ai, the
apps) shows up with the next response.
"""

import json
import os
import time
from functools import lru_cache
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageFont

USAGE_FILE = os.path.expanduser("~/.cache/claude-deck-usage.json")

OK = (120, 140, 93)
WARN = (217, 119, 87)
CRIT = (190, 35, 35)
TRACK = (60, 60, 60)
TEXT = (250, 249, 245)
DIM = (160, 160, 155)

FONT_PATHS = (
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",  # in the StreamController Flatpak
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

SCALE = 2  # drawn at 2x and downsampled by StreamController, for smoother text


class Window(NamedTuple):
    label: str
    percent: float
    resets_at: float | None  # None once the window has reset (nothing used yet)


def read_usage() -> tuple[Window, Window] | None:
    """The 5-hour and weekly windows, or None if nothing has been recorded."""
    try:
        with open(USAGE_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return _window(data, "five_hour", "5h"), _window(data, "seven_day", "Week")


def _window(data: dict, name: str, label: str) -> Window:
    window = data.get(name)
    if not isinstance(window, dict):
        return Window(label, 0.0, None)
    resets_at = window.get("resets_at")
    if isinstance(resets_at, (int, float)) and resets_at <= time.time():
        return Window(label, 0.0, None)  # reset since it was recorded
    try:
        percent = float(window.get("used_percentage") or 0)
    except (TypeError, ValueError):
        percent = 0.0
    return Window(label, percent, resets_at if isinstance(resets_at, (int, float)) else None)


def color_for(percent: float) -> tuple[int, int, int]:
    if percent >= 90:
        return CRIT
    if percent >= 70:
        return WARN
    return OK


def humanize_until(epoch: float | None) -> str:
    if epoch is None:
        return ""
    seconds = max(0, int(epoch - time.time()))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def meter_image(windows: tuple[Window, Window], width: int, height: int) -> Image.Image:
    """
    Two rows, one per window: "5h 23%" with a bar underneath and the time until
    it resets (to the right of the label on a strip segment, under the bar on a
    key, which is too narrow for both). Sized in the deck's logical pixels and
    drawn at SCALE for smoother text.
    """
    w, h = width * SCALE, height * SCALE
    image = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)

    wide = width >= 1.5 * height
    pad = 8 * SCALE
    row_h = (h - pad) / 2
    text_size = int(row_h * 0.36) if wide else int(row_h * 0.3)
    small_size = int(text_size * 0.8) if wide else int(text_size * 0.75)
    bar_h = int(row_h * 0.2) if wide else int(row_h * 0.16)

    for i, window in enumerate(windows):
        top = pad / 2 + i * row_h
        baseline = top + row_h * (0.45 if wide else 0.34)
        draw.text((pad, baseline), f"{window.label} {window.percent:.0f}%", font=_font(text_size),
                  fill=TEXT, anchor="ls")

        bar_top = top + row_h * (0.62 if wide else 0.46)
        box = [pad, bar_top, w - pad, bar_top + bar_h]
        draw.rounded_rectangle(box, radius=bar_h // 2, fill=TRACK)
        filled = min(window.percent, 100) / 100 * (box[2] - box[0])
        if filled >= 1:
            draw.rounded_rectangle([box[0], box[1], box[0] + max(filled, bar_h), box[3]],
                                   radius=bar_h // 2, fill=color_for(window.percent))

        reset = humanize_until(window.resets_at)
        if reset and wide:
            draw.text((w - pad, baseline), reset, font=_font(small_size), fill=DIM, anchor="rs")
        elif reset:
            draw.text((pad, box[3] + bar_h * 0.6), reset, font=_font(small_size), fill=DIM, anchor="lt")
    return image
