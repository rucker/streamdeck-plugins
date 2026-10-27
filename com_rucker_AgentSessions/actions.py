"""
Agent Sessions actions:

- SessionSlot:  shows the Nth active agent session; press to jump to it.
- NextWaiting:  shows how many sessions need you; press to jump to the one
                that has waited longest (permission prompts first).
- SessionDial:  Stream Deck+ dial; turn to pick a session, press/tap to jump.
- UsageMeter:   your plan's 5-hour and weekly usage, with time until each resets.
"""

import textwrap
import time
from typing import NamedTuple

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionBase import ActionBase

from .logo import SPARK_CREAM, agent_badge, logo
from .sessions import CLAUDE, DONE, IDLE, PERMISSION, UNKNOWN, WORKING
from .usage import humanize_until, meter_image, read_usage

# Each agent's own color for "your turn", and a dimmed one for "working".
AGENT_COLORS = {
    "claude": {DONE: (217, 119, 87), WORKING: (112, 56, 38)},
    "copilot": {DONE: (37, 84, 160), WORKING: (22, 46, 92)},
    "grok": {DONE: (232, 231, 226), WORKING: (92, 92, 92)},
}
READY = (30, 30, 32)
APPROVE = (247, 211, 74)
APPROVE_DIM = (121, 98, 18)
EMPTY = [0, 0, 0, 0]

STATE_TEXT = {
    WORKING: "Working",
    IDLE: "Ready",
    UNKNOWN: "No status",
    DONE: "Your turn",
    PERMISSION: "APPROVE",
}

OUTLINE = {"outline_width": 2, "outline_color": [0, 0, 0, 200]}
# Light backgrounds (Grok's "your turn", approve) take dark text and a ringed badge.
DARK_TEXT = {"color": [24, 24, 24, 255], "outline_width": 2, "outline_color": [255, 255, 255, 150]}
LIGHT_TEXT = {"color": [255, 255, 255, 255], **OUTLINE}


def is_light(color) -> bool:
    r, g, b = color[:3]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.7


class Logo(NamedTuple):
    size: float  # fraction of the key
    valign: float  # -1 top, 0 middle, 1 bottom
    halign: float = 0.0  # -1 left, 0 center, 1 right
    opacity: float = 1.0
    tint: tuple[int, int, int] | None = None


# Faded and centered on keys with nothing to show, so they look intentional.
LOGO_EMPTY = Logo(size=0.55, valign=0.0, opacity=0.25)


def logo_header(on_color: bool) -> Logo:
    """Small logo at the top; cream on orange/red keys, where orange would vanish."""
    return Logo(size=0.4, valign=-0.9, tint=SPARK_CREAM if on_color else None)

# Short press jumps; a long press (hold-time, 0.5s by default) approves. Jumping
# fires on a short release so that a long press doesn't also jump.
PRESS_EVENTS = (
    Input.Key.Events.SHORT_UP,
    Input.Dial.Events.SHORT_UP,
    Input.Dial.Events.SHORT_TOUCH_PRESS,
)
APPROVE_EVENTS = (
    Input.Key.Events.HOLD_START,
    Input.Dial.Events.HOLD_START,
    Input.Dial.Events.LONG_TOUCH_PRESS,
)


def state_color(state: str, agent: str = CLAUDE, blink: bool = True) -> list[int]:
    if state == PERMISSION:
        # Only a blocked permission prompt pulses; a finished turn can wait.
        return [*(APPROVE_DIM if blink and int(time.time()) % 2 else APPROVE), 255]
    colors = AGENT_COLORS.get(agent, AGENT_COLORS[CLAUDE])
    return [*colors.get(state, READY), 255]


def truncate(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def input_position(ident) -> tuple:
    """Reading order on the deck: keys row by row, then dials left to right."""
    if isinstance(ident, Input.Key):
        x, y = ident.coords
        return (0, y, x)
    if isinstance(ident, Input.Dial):
        return (1, 0, ident.index)
    return (2, 0, 0)


def wrap(text: str, width: int, lines: int) -> str:
    wrapped = textwrap.wrap(text, width=width, break_long_words=True) or [""]
    if len(wrapped) > lines:
        wrapped = wrapped[: lines - 1] + [truncate(" ".join(wrapped[lines - 1 :]), width)]
    return "\n".join(wrapped)


class AgentAction(ActionBase):
    """Shared rendering: only pushes to the deck when what's shown changes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shown = None

    @property
    def store(self):
        return self.plugin_base.store

    def on_ready(self):
        self._shown = None
        self.refresh()

    def on_tick(self):
        self.refresh()

    def refresh(self):
        raise NotImplementedError

    def approve(self, session: dict | None):
        if session is None or not self.store.can_approve(session):
            self.show_error(duration=1)
            return

        def done(ok):
            if not ok:
                self.show_error(duration=1)
            self.store.invalidate()
            return False

        self.store.approve(session, on_done=done)

    def show(self, top: str, center: str, bottom: str, color: list[int], center_size: int = 14,
             logo_style: Logo | None = None, agent: str | None = None):
        frame = (top, center, bottom, tuple(color), center_size, logo_style, agent)
        if frame == self._shown or not self.get_is_present():
            return
        self._shown = frame
        light = is_light(color) and color[3] > 0
        text = DARK_TEXT if light else LIGHT_TEXT
        self.set_top_label(top, font_size=12, update=False, **text)
        self.set_center_label(center, font_size=center_size, update=False, **text)
        self.set_bottom_label(bottom, font_size=11, update=False, **text)
        self.set_background_color(color, update=False)
        # Session keys: the agent's logo in a corner badge.
        if agent and (badge := agent_badge(agent, ringed=light)):
            self.set_media(image=badge, size=0.26, valign=0.92, halign=0.92, update=False)
        elif logo_style:
            self.set_media(image=logo(logo_style.opacity, logo_style.tint), size=logo_style.size,
                           valign=logo_style.valign, halign=logo_style.halign, update=False)
        else:
            self.set_media(image=None, update=False)
        self.get_input().update()

    def show_session(self, session: dict | None, top_prefix: str = ""):
        if session is None:
            self.show(top_prefix, "", "", EMPTY, logo_style=LOGO_EMPTY)
            return
        state = session.get("state", IDLE)
        center, center_size = STATE_TEXT.get(state, state), 14
        # A dial's strip segment is wide enough to show what's being asked.
        if state == PERMISSION and session.get("request") and isinstance(self.input_ident, Input.Dial):
            center, center_size = wrap(session["request"], width=22, lines=2), 11
        self.show(
            top=top_prefix + truncate(session.get("project", "?"), 10),
            center=center,
            bottom="",
            # No pulsing for the session you're already looking at.
            color=state_color(state, session.get("agent", CLAUDE), blink=not self.store.is_watched(session)),
            center_size=center_size,
            agent=session.get("agent", CLAUDE),
        )


class SessionSlot(AgentAction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def slot(self) -> int:
        """Manual slot number, or 0 for automatic (numbered by position on the page)."""
        return int(self.get_settings().get("slot", 0))

    def session(self) -> dict | None:
        sessions = self.store.sessions()
        index = self.slot() - 1 if self.slot() else self._auto_index(len(sessions))
        return sessions[index] if index is not None and 0 <= index < len(sessions) else None

    def _auto_index(self, session_count: int) -> int | None:
        # Automatic slots number themselves left-to-right, top-to-bottom (keys,
        # then dials), skipping sessions that manually numbered slots claim.
        slots = {}
        for action in self.page.get_all_actions():
            if isinstance(action, SessionSlot):
                slots.setdefault(input_position(action.input_ident), action)  # one per input, any state
        manual = {a.slot() for a in slots.values() if a.slot()}
        auto_positions = sorted(pos for pos, a in slots.items() if not a.slot())
        free = [i for i in range(session_count) if i + 1 not in manual]

        mine = input_position(self.input_ident)
        if mine not in auto_positions:
            return None
        rank = auto_positions.index(mine)
        return free[rank] if rank < len(free) else None

    def refresh(self):
        self.show_session(self.session())

    def event_callback(self, event, data=None):
        session = self.session()
        if event in PRESS_EVENTS and session:
            self.store.jump_to(session)
        elif event in APPROVE_EVENTS:
            self.approve(session)

    def get_config_rows(self) -> list:
        row = Adw.SpinRow.new_with_range(0, 32, 1)
        row.set_title("Session slot")
        row.set_subtitle("0 = automatic, by position on the page. Sessions follow tmux window order")
        row.set_value(self.slot())
        row.connect("notify::value", self._on_slot_changed)
        return [row]

    def _on_slot_changed(self, row, _):
        settings = self.get_settings()
        settings["slot"] = int(row.get_value())
        self.set_settings(settings)
        self._shown = None
        self.refresh()


class NextWaiting(AgentAction):
    def refresh(self):
        sessions = self.store.sessions()
        waiting = [s for s in sessions if self.store.needs_attention(s)]
        target = self.store.next_needing_attention()

        if not sessions:
            self.show("", "", "No sessions", EMPTY, logo_style=logo_header(on_color=False))
        elif not waiting:
            self.show("", "0", "None waiting", [*READY, 255], center_size=22,
                      logo_style=logo_header(on_color=False))
        else:
            color = state_color(target.get("state"), target.get("agent", CLAUDE))
            self.show(
                "",
                str(len(waiting)),
                "→ " + truncate(target.get("project", "?"), 8),
                color,
                center_size=22,
                # Cream on dark keys; the plain orange spark shows on light ones.
                logo_style=logo_header(on_color=not is_light(color)),
            )

    def event_callback(self, event, data=None):
        if event in PRESS_EVENTS and (target := self.store.next_needing_attention()):
            self.store.jump_to(target)


class SessionDial(AgentAction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_id: str | None = None

    def selected(self) -> tuple[int, list[dict]]:
        sessions = self.store.sessions()
        ids = [s.get("session_id") for s in sessions]
        if self.selected_id not in ids:
            # Selection vanished (or none yet): default to whoever needs you.
            target = self.store.next_needing_attention()
            self.selected_id = target.get("session_id") if target else (ids[0] if ids else None)
        index = ids.index(self.selected_id) if self.selected_id in ids else -1
        return index, sessions

    def refresh(self):
        index, sessions = self.selected()
        if index < 0:
            self.show("", "", "No sessions", EMPTY, logo_style=logo_header(on_color=False))
            return
        self.show_session(sessions[index], top_prefix=f"{index + 1}/{len(sessions)} ")

    def event_callback(self, event, data=None):
        index, sessions = self.selected()
        if index < 0:
            return
        if event in (Input.Dial.Events.TURN_CW, Input.Dial.Events.TURN_CCW):
            step = 1 if event == Input.Dial.Events.TURN_CW else -1
            self.selected_id = sessions[(index + step) % len(sessions)].get("session_id")
            self.refresh()
        elif event in PRESS_EVENTS:
            self.store.jump_to(sessions[index])
        elif event in APPROVE_EVENTS:
            self.approve(sessions[index])


class UsageMeter(AgentAction):
    def image_size(self) -> tuple[int, int]:
        if isinstance(self.input_ident, Input.Dial):
            try:
                touchscreen = self.deck_controller.inputs[Input.Touchscreen][0]
                return touchscreen.get_dial_image_area_size()
            except (AttributeError, IndexError, KeyError):
                return 200, 100
        return tuple(self.deck_controller.get_key_image_size() or (72, 72))

    def refresh(self):
        windows = read_usage()
        if windows is None:
            self.show("", "No usage\nyet", "", EMPTY, center_size=11, logo_style=LOGO_EMPTY)
            return
        # Redraw only when what's visible changes (percentages, or a reset countdown ticking over).
        frame = ("meter", tuple((w.label, round(w.percent), humanize_until(w.resets_at)) for w in windows))
        if frame == self._shown or not self.get_is_present():
            return
        self._shown = frame
        for position in ("top", "center", "bottom"):
            getattr(self, f"set_{position}_label")("", update=False)
        self.set_background_color(EMPTY, update=False)
        self.set_media(image=meter_image(windows, *self.image_size()), size=1.0, update=False)
        self.get_input().update()
