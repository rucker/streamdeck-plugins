#!/usr/bin/env python3
"""
Agent hook that records each session's state for the Agent Sessions deck
plugins. Claude Code and Grok run it from ~/.claude/settings.json (Grok reads
Claude's hooks), and GitHub Copilot from ~/.copilot/settings.json with
`--agent copilot`.

Registered for several hook events (see install.sh). Reads the hook payload
from stdin and writes ~/.cache/claude-deck/<session_id>.json atomically. It
must never print to stdout (SessionStart/UserPromptSubmit stdout is injected
into the agent's context) and must never fail the hook, so every error is
swallowed and it always exits 0.
"""

import json
import os
import sys
import tempfile
import time
from urllib.parse import urlparse

# Deliberately not $XDG_CACHE_HOME: inside the StreamController Flatpak that
# points into the sandbox, and both sides must agree on this path.
STATE_DIR = os.path.expanduser("~/.cache/claude-deck")

WORKING = "working"
IDLE = "idle"  # fresh session, nothing asked yet
DONE = "done"  # the agent finished its turn; your move
PERMISSION = "permission"  # blocked on an approval / question

CLAUDE = "claude"
# Agents whose approval dialog the deck recognizes (see APPROVE_DIALOGS in the front ends).
APPROVABLE = (CLAUDE, "copilot")

# Events that only update a session the hook already knows about. Grok sends a
# Stop after SessionEnd, which would otherwise bring the session back.
UPDATE_ONLY = ("Stop", "Notification")


def agent_name() -> str:
    if "--agent" in sys.argv[1:-1]:
        return sys.argv[sys.argv.index("--agent") + 1]
    # Grok runs the same registration as Claude Code, from Claude's settings.
    if os.environ.get("GROK_HOOK_EVENT"):
        return "grok"
    return CLAUDE


def normalize(payload: dict) -> dict:
    """Copilot's PermissionRequest payload is camelCase with no hook_event_name."""
    if payload.get("hookName") == "permissionRequest":
        payload.setdefault("hook_event_name", "PermissionRequest")
    for snake, camel in (("session_id", "sessionId"), ("tool_name", "toolName"), ("tool_input", "toolInput")):
        if snake not in payload and camel in payload:
            payload[snake] = payload[camel]
    return payload


def state_for(payload: dict) -> str | None:
    event = payload.get("hook_event_name")

    if event == "SessionStart":
        return IDLE
    if event in ("UserPromptSubmit", "PostToolUse", "PostToolUseFailure"):
        return WORKING
    if event == "Stop":
        return DONE
    if event == "PermissionRequest":
        return PERMISSION
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


def summarize_request(tool: str, tool_input: dict) -> str:
    """One short line describing what the agent wants to do, for the deck."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool.lower() in ("bash", "run_terminal_command"):
        command = str(tool_input.get("command", "")).strip().splitlines()
        return "$ " + (command[0] if command else "")
    if "file_path" in tool_input or "notebook_path" in tool_input:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return f"{tool} {os.path.basename(str(path))}"
    if tool == "WebFetch":
        return "Fetch " + urlparse(str(tool_input.get("url", ""))).netloc
    if tool == "WebSearch":
        return "Search: " + str(tool_input.get("query", ""))
    if tool.startswith("mcp__"):
        # mcp__<server>__<tool>
        _, server, name = (tool.split("__", 2) + ["", ""])[:3]
        return f"{server}: {name}"
    return tool


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
    payload = normalize(json.load(sys.stdin))
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
    if not record and payload.get("hook_event_name") in UPDATE_ONLY:
        return
    if new_state is None and record:
        return

    now = time.time()
    cwd = payload.get("cwd") or record.get("cwd") or ""
    state = new_state or record.get("state") or IDLE
    agent = record.get("agent") or agent_name()

    record.update(
        {
            "session_id": session_id,
            "agent": agent,
            "cwd": cwd,
            # cwd follows the agent around (cd in a shell); keep the label stable.
            "project": record.get("project") or project_name(cwd),
            "tmux_pane": os.environ.get("TMUX_PANE") or record.get("tmux_pane"),
            "started": record.get("started", now),
            "updated": now,
        }
    )
    if record.get("state") != state:
        record["state"] = state
        record["since"] = now
    if state != PERMISSION:
        record.pop("request", None)
        record.pop("request_kind", None)
    elif payload.get("hook_event_name") == "PermissionRequest":
        record["request"] = summarize_request(
            str(payload.get("tool_name", "")), payload.get("tool_input")
        )[:120]
        # Only tool approvals may be approved from the deck, and only for agents
        # whose dialog the deck can recognize before answering it.
        record["request_kind"] = "tool" if agent in APPROVABLE else "other"
    elif "request" not in record:
        # Notification-only fallback (e.g. a question rather than a tool call).
        record["request"] = str(payload.get("message", ""))[:120]
        record["request_kind"] = "other"

    write_atomic(path, record)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a hook must never break the agent
        pass
    sys.exit(0)
