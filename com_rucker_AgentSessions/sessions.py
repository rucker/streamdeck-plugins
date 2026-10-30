"""
Session store and window/tmux plumbing shared by all Agent Sessions actions.

The hook (hooks/agent_deck_hook.py at the repo root) writes one JSON file per
agent session (Claude Code, Copilot or Grok) into STATE_DIR. Every action ticks
once a second, so reads are cached and shared through the plugin's single
SessionStore instance.
"""

import json
import os
import re
import subprocess
import threading
import time
from urllib.parse import urlparse

from gi.repository import Gio, GLib
from loguru import logger as log

STATE_DIR = os.path.expanduser("~/.cache/agent-deck")
# Per-session stats from hooks/agent_deck_statusline.py, kept apart from the hook's files.
STATS_DIR = os.path.expanduser("~/.cache/agent-deck-stats")

WORKING = "working"
IDLE = "idle"
DONE = "done"
PERMISSION = "permission"
UNKNOWN = "unknown"  # an agent seen in tmux, but no hook has reported yet
ATTENTION = (PERMISSION, DONE)

TERMINAL_WM_CLASS = "org.gnome.Terminal"

READ_CACHE_SECONDS = 0.5
# Checks in a row without the approval dialog on screen before a pending permission counts as answered.
ANSWERED_AFTER_MISSES = 2
TMUX_INTERVAL_SECONDS = 1
PRUNE_INTERVAL_SECONDS = 10
# Sessions outside tmux can't be checked for liveness; drop them once they've
# been silent this long in case SessionEnd never fired (crash, kill -9).
UNTRACKED_MAX_AGE_SECONDS = 12 * 3600

SHELLS = {"bash", "zsh", "fish", "sh", "dash"}

CLAUDE = "claude"

# Started and stopped by hooks/agent_deck_demo.py, at the repo root next to this plugin.
DEMO_SESSION = "zz-demo"
DEMO_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "hooks", "agent_deck_demo.py")
DEMO_TIMEOUT_SECONDS = 60

# Each agent's tool permission dialog with its one-time "Yes" highlighted; the
# captured digit answers it. Copilot's sits in a box, and its folder-trust
# question ("Do you trust the files…") must not match. Grok's "Yes" moves (3 for
# an edit, a fetch or an MCP tool, 2 for a shell command, where 3 is "No"), and
# its option 1 is always-approve mode, so only a highlighted one-time "Yes",
# "Yes, proceed" or "Yes, allow once" counts.
APPROVE_DIALOGS = {
    "claude": re.compile(r"^\s*❯\s*(1)\.\s*Yes\s*$(?=.*Esc to cancel)", re.MULTILINE | re.DOTALL),
    "copilot": re.compile(
        r"Do you want to [^\n]*\?[\s│]*❯ (1)\. Yes[ │]*$(?=.*↑/↓ to navigate · enter to select · esc to cancel)",
        re.MULTILINE | re.DOTALL,
    ),
    "grok": re.compile(
        r"^\s*┃\s+(\d) \(●\) Yes(?:, proceed|, allow once)?\s*$(?=.*\d/\d:select\s+│\s+Tab:next option)",
        re.MULTILINE | re.DOTALL,
    ),
}


def grok_request(screen: str) -> str | None:
    """
    What Grok's dialog asks, in the hook's style ("$ <command>", "Edit <file>",
    "Fetch <host>", "<server>: <tool>"): its notification only says "Tool
    permission requested".
    """
    heading = re.search(r"^\s*┃\s+›\s+(.+?)\s*$", screen, re.MULTILINE)
    if not heading:
        return None
    text = heading.group(1)
    if fetch := re.fullmatch(r"Allow Fetch: (\S+)\?", text):
        return "Fetch " + (urlparse(fetch.group(1)).netloc or fetch.group(1))
    if mcp := re.fullmatch(r"Allow \((.+?)\) (.+)\?", text):
        return f"{mcp.group(1)}: {mcp.group(2)}"
    if edit := re.fullmatch(r"Allow (\S+) to (.+)\?", text):
        return f"{edit.group(1)} {os.path.basename(edit.group(2))}"
    # A shell command's heading describes it; the command follows.
    command = re.search(r"^\s*┃\s+│ (.+?)\s*$", screen[heading.end():], re.MULTILINE)
    return f"$ {command.group(1)}" if command else text


def approve_key(agent: str | None, screen: str) -> str | None:
    """The key that answers the agent's approval dialog on this screen, or None if it isn't showing."""
    dialog = APPROVE_DIALOGS.get(agent or CLAUDE)
    match = dialog.search(screen) if dialog else None
    return match.group(1) if match else None


def request_key(session: dict) -> tuple:
    """One pending permission: a session as of a hook update, which a new request or answer changes."""
    return session.get("session_id"), session.get("updated")


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


def project_name(cwd: str) -> str:
    # Same naming as the hook's, so a placeholder keeps its label when replaced.
    if not cwd:
        return "?"
    if os.path.normpath(cwd) == os.path.expanduser("~"):
        return "~"
    return os.path.basename(os.path.normpath(cwd))


def pane_agent(command: str) -> str | None:
    """The agent running in a tmux pane, from #{pane_current_command}."""
    # Claude Code can show up as its version (its process title), e.g. "2.1.311".
    if command == CLAUDE or re.fullmatch(r"\d+\.\d+\.\d+", command):
        return CLAUDE
    # Grok's binary is named per platform, e.g. "grok-macos-aarch64" (tmux cuts it short).
    if command == "grok" or command.startswith("grok-"):
        return "grok"
    return "copilot" if command == "copilot" else None


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: list[dict] = []
        self._last_read = 0.0
        self._suspects: set[str] = set()
        # The tmux pane you're looking at: active pane AND terminal focused.
        self.focused_pane: str | None = None
        # pane_id -> sort key from its tmux position (session, window, pane).
        self.pane_order: dict[str, tuple] = {}
        # pane_id -> (agent, cwd) for every tmux pane running an agent, hooked or not.
        self.agent_panes: dict[str, tuple[str, str]] = {}
        self.tmux_sessions: set[str] = set()
        # request_key -> [seen: its approval dialog has been on screen, checks since it last was, what it asks]
        self._dialog_checks: dict[tuple, list] = {}
        self.demo_starting = False
        self.demo_stopping = False
        self._stop = threading.Event()
        threading.Thread(target=self._prune_loop, daemon=True, name="AgentSessions-prune").start()
        threading.Thread(target=self._tmux_loop, daemon=True, name="AgentSessions-tmux").start()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #

    def sessions(self) -> list[dict]:
        """
        All known sessions in tmux window order, so keys renumber the way tmux
        windows do. Sessions outside tmux (or not yet seen there) go last, by
        start time.
        """
        with self._lock:
            if time.time() - self._last_read > READ_CACHE_SECONDS:
                self._sessions = self._read_all()
                self._last_read = time.time()
            order = self.pane_order
            return sorted(
                [self._with_screen(s) for s in self._sessions] + self._unhooked_sessions(self._sessions),
                key=lambda s: (0, order[s["tmux_pane"]]) if s.get("tmux_pane") in order
                else (1, (s.get("started", 0), s.get("session_id", ""))),
            )

    def _unhooked_sessions(self, hooked: list[dict]) -> list[dict]:
        """
        Placeholders for agent panes with no state file yet, e.g. sessions
        started before the hooks were installed that haven't fired one since.
        Replaced by the real record as soon as that session triggers a hook.
        """
        known = {s.get("tmux_pane") for s in hooked}
        return [
            {"session_id": f"tmux:{pane}", "agent": agent, "tmux_pane": pane,
             "project": project_name(path), "state": UNKNOWN, "started": 0}
            for pane, (agent, path) in self.agent_panes.items() if pane not in known
        ]

    def _with_screen(self, session: dict) -> dict:
        """
        No hook fires when a permission is granted, only when the tool finishes,
        which for a long command can be minutes. Once its dialog has left the
        screen, show the session as working until the hook catches up. Until then,
        the dialog may say more about the request than the hook could.
        """
        check = self._dialog_checks.get(request_key(session)) if session.get("state") == PERMISSION else None
        if not check:
            return session
        if check[1] < ANSWERED_AFTER_MISSES:
            return {**session, "request": check[2]} if check[2] else session
        answered = {k: v for k, v in session.items() if k not in ("request", "request_kind")}
        answered["state"] = WORKING
        return answered

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
        for record in records:
            try:
                with open(os.path.join(STATS_DIR, f"{record.get('session_id')}.json")) as f:
                    stats = json.load(f)
                for field in ("context_used_percentage", "ai_credits"):
                    if isinstance(stats.get(field), (int, float)):
                        record[field] = stats[field]
            except (OSError, ValueError, AttributeError):
                pass  # no stats yet
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
    # Tracking tmux layout and which pane you're looking at
    # ------------------------------------------------------------------ #

    def _tmux_loop(self):
        while not self._stop.wait(TMUX_INTERVAL_SECONDS):
            try:
                self.pane_order, self.agent_panes, self.tmux_sessions = self._read_tmux_panes()
            except Exception:  # noqa: BLE001 - keep the last known layout
                pass
            try:
                self._check_dialogs()
            except Exception:  # noqa: BLE001 - keep the last results
                pass
            try:
                self.focused_pane = self._read_focused_pane()
            except Exception:  # noqa: BLE001 - treat as "not looking at anything"
                self.focused_pane = None

    @staticmethod
    def _read_tmux_panes() -> tuple[dict[str, tuple], dict[str, tuple[str, str]], set[str]]:
        """Returns (pane_id -> sort key, pane_id -> (agent, cwd) for panes running an agent, session names)."""
        result = run_host(["tmux", "list-panes", "-a", "-F", "\t".join([
            "#{pane_id}", "#{session_name}", "#{window_index}", "#{pane_index}",
            "#{pane_current_command}", "#{pane_current_path}",
        ])])
        if result.returncode != 0:
            return {}, {}, set()

        def natural(name: str) -> tuple:
            # Session "10" sorts after "2", like tmux's own ordering.
            return (0, int(name), "") if name.isdigit() else (1, 0, name)

        order, agent_panes, sessions = {}, {}, set()
        for line in result.stdout.splitlines():
            pane_id, session, window, pane, command, path = line.split("\t", 5)
            sessions.add(session)
            order[pane_id] = (natural(session), int(window), int(pane))
            if agent := pane_agent(command):
                agent_panes[pane_id] = (agent, path)
        return order, agent_panes, sessions

    def _check_dialogs(self):
        with self._lock:
            pending = [s for s in self._sessions if s.get("state") == PERMISSION and s.get("tmux_pane")]
        checks = {}
        for session in pending:
            if session.get("agent", CLAUDE) not in APPROVE_DIALOGS:
                continue
            key = request_key(session)
            check = list(self._dialog_checks.get(key, [False, 0, None]))
            screen = run_host(["tmux", "capture-pane", "-p", "-t", session["tmux_pane"]])
            if screen.returncode == 0 and approve_key(session.get("agent"), screen.stdout):
                check[:2] = [True, 0]
            elif screen.returncode == 0 and check[0]:
                # Only a dialog seen on screen can disappear: one the pattern never
                # matches must not hide a pending request.
                check[1] += 1
            if screen.returncode == 0 and session.get("agent") == "grok":
                check[2] = grok_request(screen.stdout) or check[2]
            checks[key] = check
        self._dialog_checks = checks

    def _read_focused_pane(self) -> str | None:
        if not any(w.get("focus") for w in self._terminal_windows()):
            return None
        # Run outside tmux, display-message reports the most recently used client.
        result = run_host(["tmux", "display-message", "-p", "#{pane_id}"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    # ------------------------------------------------------------------ #
    # Pruning sessions whose agent process is gone
    # ------------------------------------------------------------------ #

    def _prune_loop(self):
        while not self._stop.wait(PRUNE_INTERVAL_SECONDS):
            try:
                self._prune_once()
            except Exception as e:  # noqa: BLE001
                log.warning(f"[AgentSessions] prune failed: {e}")

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
                # Pane closed, or the agent exited back to the shell without SessionEnd.
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
        for directory in (STATE_DIR, STATS_DIR):
            try:
                os.remove(os.path.join(directory, f"{session['session_id']}.json"))
            except (OSError, KeyError):
                pass
        self.invalidate()

    # ------------------------------------------------------------------ #
    # Jumping to a session
    # ------------------------------------------------------------------ #

    def jump_to(self, session: dict):
        self.jump_to_target(session.get("tmux_pane"))

    def jump_to_target(self, pane: str | None):
        """Any tmux target: a pane, or a whole session ("name:")."""
        threading.Thread(target=self._jump, args=(pane,), daemon=True).start()

    def _jump(self, pane: str | None):
        if pane:
            # switch-client handles panes in another tmux session; the other two
            # make the pane current within its window/session.
            result = run_host(
                ["tmux", "switch-client", "-t", pane, ";",
                 "select-window", "-t", pane, ";",
                 "select-pane", "-t", pane]
            )
            if result.returncode != 0:
                log.warning(f"[AgentSessions] tmux jump to {pane} failed: {result.stderr.strip()}")
        try:
            self._activate_terminal()
        except Exception as e:  # noqa: BLE001
            log.warning(f"[AgentSessions] could not raise terminal (is Window Calls enabled?): {e}")

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
        """Answers "Yes" once (never "don't ask again" or always-approve); on_done(ok) runs on the GTK thread."""
        def work():
            ok = False
            try:
                ok = self._approve(session)
            except Exception as e:  # noqa: BLE001
                log.warning(f"[AgentSessions] approve failed: {e}")
            if on_done:
                GLib.idle_add(on_done, ok)

        threading.Thread(target=work, daemon=True).start()

    def _approve(self, session: dict) -> bool:
        if not self.can_approve(session):
            return False
        pane = session["tmux_pane"]
        # Check the dialog is really on screen: it may have been answered in the
        # terminal already, and a stray digit would land in the prompt instead.
        screen = run_host(["tmux", "capture-pane", "-p", "-t", pane])
        key = approve_key(session.get("agent"), screen.stdout) if screen.returncode == 0 else None
        if not key:
            log.info(f"[AgentSessions] no approval dialog visible in {pane}; not sending")
            return False
        return run_host(["tmux", "send-keys", "-t", pane, key]).returncode == 0

    # ------------------------------------------------------------------ #
    # Demo Mode
    # ------------------------------------------------------------------ #

    def demo_running(self) -> bool:
        return DEMO_SESSION in self.tmux_sessions

    def run_demo(self, command: str, on_done=None):
        """Runs the demo script's start or stop; on_done(ok) runs on the GTK thread."""
        def work():
            ok = False
            try:
                result = run_host(["python3", "-I", DEMO_SCRIPT, command], timeout=DEMO_TIMEOUT_SECONDS)
                ok = result.returncode == 0
                if not ok:
                    log.warning(f"[AgentSessions] demo {command} failed: {result.stderr.strip()}")
                # So the key doesn't show the old state until the next tmux poll.
                self.pane_order, self.agent_panes, self.tmux_sessions = self._read_tmux_panes()
            except Exception as e:  # noqa: BLE001
                log.warning(f"[AgentSessions] demo {command} failed: {e}")
            self.invalidate()
            if on_done:
                GLib.idle_add(on_done, ok)

        threading.Thread(target=work, daemon=True).start()

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
