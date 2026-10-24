"""
Session store and window/tmux plumbing shared by all Claude Sessions actions.

The hook (hooks/claude_deck_hook.py) writes one JSON file per Claude Code
session into STATE_DIR. Every action ticks once a second, so reads are cached
and shared through the plugin's single SessionStore instance.
"""

import json
import os
import re
import subprocess
import threading
import time

from gi.repository import Gio, GLib
from loguru import logger as log

STATE_DIR = os.path.expanduser("~/.cache/claude-deck")

WORKING = "working"
IDLE = "idle"
DONE = "done"
PERMISSION = "permission"
ATTENTION = (PERMISSION, DONE)

TERMINAL_WM_CLASS = "org.gnome.Terminal"

READ_CACHE_SECONDS = 0.5
FOCUS_INTERVAL_SECONDS = 1
PRUNE_INTERVAL_SECONDS = 10
# Sessions outside tmux can't be checked for liveness; drop them once they've
# been silent this long in case SessionEnd never fired (crash, kill -9).
UNTRACKED_MAX_AGE_SECONDS = 12 * 3600

SHELLS = {"bash", "zsh", "fish", "sh", "dash"}

# Claude Code's tool permission dialog: highlighted "1. Yes" plus the footer.
APPROVE_DIALOG = re.compile(r"^\s*❯\s*1\.\s*Yes\s*$(?=.*Esc to cancel)", re.MULTILINE | re.DOTALL)


def is_in_flatpak() -> bool:
    return os.path.isfile("/.flatpak-info")


def run_host(args: list[str], timeout: float = 3) -> subprocess.CompletedProcess:
    # The Flatpak has its own /tmp, so it can't reach the host tmux socket
    # directly; flatpak-spawn --host runs the command outside the sandbox.
    # --directory is required: by default it uses our cwd (/app/bin/...),
    # which doesn't exist on the host, and the spawn fails.
    if is_in_flatpak():
        args = ["flatpak-spawn", "--host", f"--directory={os.path.expanduser('~')}", *args]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def humanize_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}"


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: list[dict] = []
        self._last_read = 0.0
        self._suspects: set[str] = set()
        # The tmux pane you're looking at: active pane AND terminal focused.
        self.focused_pane: str | None = None
        self._stop = threading.Event()
        threading.Thread(target=self._prune_loop, daemon=True, name="ClaudeSessions-prune").start()
        threading.Thread(target=self._focus_loop, daemon=True, name="ClaudeSessions-focus").start()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #

    def sessions(self) -> list[dict]:
        """All known sessions in stable order (oldest first), so keys don't shuffle."""
        with self._lock:
            if time.time() - self._last_read > READ_CACHE_SECONDS:
                self._sessions = self._read_all()
                self._last_read = time.time()
            return list(self._sessions)

    def _read_all(self) -> list[dict]:
        records = []
        try:
            names = os.listdir(STATE_DIR)
        except FileNotFoundError:
            return records
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(STATE_DIR, name)) as f:
                    records.append(json.load(f))
            except (OSError, ValueError):
                continue  # mid-write or removed; picked up next tick
        records.sort(key=lambda r: (r.get("started", 0), r.get("session_id", "")))
        return records

    def is_watched(self, session: dict) -> bool:
        pane = session.get("tmux_pane")
        return bool(pane) and pane == self.focused_pane

    def needs_attention(self, session: dict) -> bool:
        """Waiting on you, and you're not already looking at it."""
        return session.get("state") in ATTENTION and not self.is_watched(session)

    def next_needing_attention(self) -> dict | None:
        """Longest-waiting permission prompt first, then longest-waiting finished turn."""
        for state in ATTENTION:
            waiting = [
                s for s in self.sessions() if s.get("state") == state and self.needs_attention(s)
            ]
            if waiting:
                return min(waiting, key=lambda s: s.get("since", 0))
        return None

    def invalidate(self):
        with self._lock:
            self._last_read = 0.0

    # ------------------------------------------------------------------ #
    # Tracking which pane you're looking at
    # ------------------------------------------------------------------ #

    def _focus_loop(self):
        while not self._stop.wait(FOCUS_INTERVAL_SECONDS):
            try:
                self.focused_pane = self._read_focused_pane()
            except Exception:  # noqa: BLE001 - treat as "not looking at anything"
                self.focused_pane = None

    def _read_focused_pane(self) -> str | None:
        if not any(w.get("focus") for w in self._terminal_windows()):
            return None
        # Run outside tmux, display-message reports the most recently used client.
        result = run_host(["tmux", "display-message", "-p", "#{pane_id}"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    # ------------------------------------------------------------------ #
    # Pruning sessions whose Claude process is gone
    # ------------------------------------------------------------------ #

    def _prune_loop(self):
        while not self._stop.wait(PRUNE_INTERVAL_SECONDS):
            try:
                self._prune_once()
            except Exception as e:  # noqa: BLE001
                log.warning(f"[ClaudeSessions] prune failed: {e}")

    def _prune_once(self):
        result = run_host(["tmux", "list-panes", "-a", "-F", "#{pane_id} #{pane_current_command}"])
        tmux_ok = result.returncode == 0
        panes = {}
        if tmux_ok:
            for line in result.stdout.splitlines():
                pane_id, _, command = line.partition(" ")
                panes[pane_id] = command

        now = time.time()
        suspects = set()
        for session in self._read_all():
            pane = session.get("tmux_pane")
            if pane and tmux_ok:
                # Pane closed, or Claude exited back to the shell without SessionEnd.
                dead = pane not in panes or panes[pane] in SHELLS
            else:
                dead = now - session.get("updated", now) > UNTRACKED_MAX_AGE_SECONDS
            if not dead:
                continue
            # Require two consecutive dead sightings so a momentary blip
            # (e.g. a foreground shell command) doesn't drop a live session.
            if session.get("session_id") in self._suspects:
                self.remove(session)
            else:
                suspects.add(session.get("session_id"))
        self._suspects = suspects

    def remove(self, session: dict):
        try:
            os.remove(os.path.join(STATE_DIR, f"{session['session_id']}.json"))
        except (OSError, KeyError):
            pass
        self.invalidate()

    # ------------------------------------------------------------------ #
    # Jumping to a session
    # ------------------------------------------------------------------ #

    def jump_to(self, session: dict):
        threading.Thread(target=self._jump, args=(session,), daemon=True).start()

    def _jump(self, session: dict):
        pane = session.get("tmux_pane")
        if pane:
            # switch-client handles panes in another tmux session; the other two
            # make the pane current within its window/session.
            result = run_host(
                ["tmux", "switch-client", "-t", pane, ";",
                 "select-window", "-t", pane, ";",
                 "select-pane", "-t", pane]
            )
            if result.returncode != 0:
                log.warning(f"[ClaudeSessions] tmux jump to {pane} failed: {result.stderr.strip()}")
        try:
            self._activate_terminal()
        except Exception as e:  # noqa: BLE001
            log.warning(f"[ClaudeSessions] could not raise terminal (is Window Calls enabled?): {e}")

    # ------------------------------------------------------------------ #
    # Approving a permission prompt
    # ------------------------------------------------------------------ #

    @staticmethod
    def can_approve(session: dict) -> bool:
        return (
            session.get("state") == PERMISSION
            and session.get("request_kind") == "tool"
            and bool(session.get("tmux_pane"))
        )

    def approve(self, session: dict, on_done=None):
        """Answers "1. Yes" (never "don't ask again"); on_done(ok) runs on the GTK thread."""
        def work():
            ok = False
            try:
                ok = self._approve(session)
            except Exception as e:  # noqa: BLE001
                log.warning(f"[ClaudeSessions] approve failed: {e}")
            if on_done:
                GLib.idle_add(on_done, ok)

        threading.Thread(target=work, daemon=True).start()

    def _approve(self, session: dict) -> bool:
        if not self.can_approve(session):
            return False
        pane = session["tmux_pane"]
        # Check the dialog is really on screen: it may have been answered in the
        # terminal already, and a stray "1" would land in the prompt instead.
        screen = run_host(["tmux", "capture-pane", "-p", "-t", pane])
        if screen.returncode != 0 or not APPROVE_DIALOG.search(screen.stdout):
            log.info(f"[ClaudeSessions] no approval dialog visible in {pane}; not sending")
            return False
        return run_host(["tmux", "send-keys", "-t", pane, "1"]).returncode == 0

    # ------------------------------------------------------------------ #
    # Window Calls GNOME extension (window-calls@domandoman.xyz)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _window_call(method: str, params: GLib.Variant = None) -> GLib.Variant:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return bus.call_sync(
            "org.gnome.Shell", "/org/gnome/Shell/Extensions/Windows",
            "org.gnome.Shell.Extensions.Windows", method, params, None,
            Gio.DBusCallFlags.NONE, 2000, None,
        )

    def _terminal_windows(self) -> list[dict]:
        windows = json.loads(self._window_call("List").unpack()[0])
        return [w for w in windows if w.get("wm_class") == TERMINAL_WM_CLASS]

    def _activate_terminal(self):
        terminals = self._terminal_windows()
        if not terminals:
            return
        # Prefer a terminal already in focus or on the current workspace.
        terminals.sort(key=lambda w: (not w.get("focus"), not w.get("in_current_workspace")))
        self._window_call("Activate", GLib.Variant("(u)", (terminals[0]["id"],)))
