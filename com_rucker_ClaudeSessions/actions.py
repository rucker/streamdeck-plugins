"""
Claude Sessions actions:

- SessionSlot:  shows the Nth active Claude session; press to jump to it.
- NextWaiting:  shows how many sessions need you; press to jump to the one
                that has waited longest (permission prompts first).
- SessionDial:  Stream Deck+ dial; turn to pick a session, press/tap to jump.
"""

import time

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionBase import ActionBase

from .sessions import DONE, IDLE, PERMISSION, WORKING, humanize_age

COLORS = {
    WORKING: (37, 84, 160),
    IDLE: (55, 55, 55),
    DONE: (217, 119, 87),
    PERMISSION: (190, 35, 35),
}
EMPTY = [0, 0, 0, 0]

STATE_TEXT = {
    WORKING: "working",
    IDLE: "ready",
    DONE: "your turn",
    PERMISSION: "APPROVE",
}

OUTLINE = {"outline_width": 2, "outline_color": [0, 0, 0, 200]}

PRESS_EVENTS = (
    Input.Key.Events.DOWN,
    Input.Dial.Events.DOWN,
    Input.Dial.Events.SHORT_TOUCH_PRESS,
)


def state_color(state: str, blink: bool = True) -> list[int]:
    rgb = COLORS.get(state, COLORS[IDLE])
    # Only a blocked permission prompt pulses; a finished turn can wait.
    if blink and state == PERMISSION and int(time.time()) % 2:
        rgb = tuple(c // 2 for c in rgb)
    return [*rgb, 255]


def truncate(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


class ClaudeAction(ActionBase):
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

    def show(self, top: str, center: str, bottom: str, color: list[int], center_size: int = 14):
        frame = (top, center, bottom, tuple(color), center_size)
        if frame == self._shown or not self.get_is_present():
            return
        self._shown = frame
        self.set_top_label(top, font_size=12, update=False, **OUTLINE)
        self.set_center_label(center, font_size=center_size, update=False, **OUTLINE)
        self.set_bottom_label(bottom, font_size=11, update=False, **OUTLINE)
        self.set_background_color(color, update=False)
        self.get_input().update()

    def show_session(self, session: dict | None, top_prefix: str = ""):
        if session is None:
            self.show(top_prefix, "", "", EMPTY)
            return
        state = session.get("state", IDLE)
        self.show(
            top=top_prefix + truncate(session.get("project", "?"), 10),
            center=STATE_TEXT.get(state, state),
            bottom=humanize_age(time.time() - session.get("since", time.time())),
            # No pulsing for the session you're already looking at.
            color=state_color(state, blink=not self.store.is_watched(session)),
        )


class SessionSlot(ClaudeAction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

    def slot(self) -> int:
        return int(self.get_settings().get("slot", 1))

    def session(self) -> dict | None:
        sessions = self.store.sessions()
        index = self.slot() - 1
        return sessions[index] if 0 <= index < len(sessions) else None

    def refresh(self):
        self.show_session(self.session())

    def event_callback(self, event, data=None):
        if event in PRESS_EVENTS and (session := self.session()):
            self.store.jump_to(session)

    def get_config_rows(self) -> list:
        row = Adw.SpinRow.new_with_range(1, 32, 1)
        row.set_title("Session slot")
        row.set_subtitle("Sessions are numbered in the order they started")
        row.set_value(self.slot())
        row.connect("notify::value", self._on_slot_changed)
        return [row]

    def _on_slot_changed(self, row, _):
        settings = self.get_settings()
        settings["slot"] = int(row.get_value())
        self.set_settings(settings)
        self._shown = None
        self.refresh()


class NextWaiting(ClaudeAction):
    def refresh(self):
        sessions = self.store.sessions()
        waiting = [s for s in sessions if self.store.needs_attention(s)]
        target = self.store.next_needing_attention()

        if not sessions:
            self.show("Claude", "–", "no sessions", EMPTY)
        elif not waiting:
            self.show("Claude", "0", "none waiting", [*COLORS[IDLE], 255], center_size=22)
        else:
            self.show(
                "Claude",
                str(len(waiting)),
                "→ " + truncate(target.get("project", "?"), 8),
                state_color(target.get("state")),
                center_size=22,
            )

    def event_callback(self, event, data=None):
        if event in PRESS_EVENTS and (target := self.store.next_needing_attention()):
            self.store.jump_to(target)


class SessionDial(ClaudeAction):
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
            self.show("Claude", "–", "no sessions", EMPTY)
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
