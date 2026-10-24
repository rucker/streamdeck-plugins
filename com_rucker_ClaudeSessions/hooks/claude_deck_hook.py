#!/usr/bin/env python3
"""
Claude Code hook that records each session's state for the Claude Sessions
StreamController plugin.

Registered for several hook events (see install.sh). Reads the hook payload
from stdin and writes ~/.cache/claude-deck/<session_id>.json atomically. It
must never print to stdout (SessionStart/UserPromptSubmit stdout is injected
into Claude's context) and must never fail the hook, so every error is
swallowed and it always exits 0.
"""

import json
import os
import sys
import tempfile
import time

# Deliberately not $XDG_CACHE_HOME: inside the StreamController Flatpak that
# points into the sandbox, and both sides must agree on this path.
STATE_DIR = os.path.expanduser("~/.cache/claude-deck")

WORKING = "working"
IDLE = "idle"  # fresh session, nothing asked yet
DONE = "done"  # Claude finished its turn; your move
PERMISSION = "permission"  # blocked on an approval / question


def state_for(payload: dict) -> str | None:
    event = payload.get("hook_event_name")

    if event == "SessionStart":
        return IDLE
    if event in ("UserPromptSubmit", "PostToolUse"):
        return WORKING
    if event == "Stop":
        return DONE
    if event == "Notification":
        kind = payload.get("notification_type")
        message = str(payload.get("message", "")).lower()
        if kind in ("permission_prompt", "elicitation_dialog") or (
            kind is None and "permission" in message
        ):
            return PERMISSION
        if kind == "idle_prompt" or (kind is None and "waiting for your input" in message):
            return DONE
    return None


def project_name(cwd: str) -> str:
    if not cwd:
        return "?"
    if os.path.normpath(cwd) == os.path.expanduser("~"):
        return "~"
    return os.path.basename(os.path.normpath(cwd))


def write_atomic(path: str, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def main() -> None:
    payload = json.load(sys.stdin)
    session_id = payload.get("session_id")
    if not session_id:
        return

    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{session_id}.json")

    if payload.get("hook_event_name") == "SessionEnd":
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return

    try:
        with open(path) as f:
            record = json.load(f)
    except (OSError, ValueError):
        record = {}

    new_state = state_for(payload)
    # An idle_prompt can arrive after a permission prompt was already shown;
    # don't let it downgrade the more urgent state.
    if new_state == DONE and record.get("state") == PERMISSION and payload.get(
        "hook_event_name"
    ) == "Notification":
        new_state = PERMISSION
    if new_state is None and record:
        return

    now = time.time()
    cwd = payload.get("cwd") or record.get("cwd") or ""
    state = new_state or record.get("state") or IDLE

    record.update(
        {
            "session_id": session_id,
            "cwd": cwd,
            "project": project_name(cwd),
            "tmux_pane": os.environ.get("TMUX_PANE") or record.get("tmux_pane"),
            "started": record.get("started", now),
            "updated": now,
        }
    )
    if record.get("state") != state:
        record["state"] = state
        record["since"] = now
    if state == PERMISSION:
        record["message"] = payload.get("message", "")

    write_atomic(path, record)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a hook must never break Claude Code
        pass
    sys.exit(0)
