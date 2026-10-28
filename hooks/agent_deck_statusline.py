#!/usr/bin/env python3
"""
Status line command for Claude Code, Copilot and Grok that records session
stats for the deck.

Each agent pipes a JSON payload to its status line on every update. From all
three this records how full the session's context window is, and from Copilot
the AI Credits the session has used, into STATS_DIR/<session_id>.json (shown
on session keys). For Claude.ai subscribers,
Claude Code's payload also includes `rate_limits` (5-hour and weekly windows,
each with `used_percentage` and `resets_at`), the real numbers the API reports;
those go to USAGE_FILE for the Usage meter.

Prints nothing, so no status line is shown; it never fails, so a broken write
can't disturb the agent.
"""

import json
import os
import sys
import tempfile
import time

# Outside ~/.cache/agent-deck/ on purpose: every .json file there is read as a
# session state file.
USAGE_FILE = os.path.expanduser("~/.cache/agent-deck-usage.json")

# Per-session stats, apart from the hook's state files: the two run
# independently, and sharing a file would let one undo the other's write.
STATS_DIR = os.path.expanduser("~/.cache/agent-deck-stats")

WINDOWS = ("five_hour", "seven_day")


def write_atomic(path: str, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def record_stats(payload: dict) -> None:
    session_id = payload.get("session_id")
    if not session_id:
        return
    record = {}
    context = payload.get("context_window")
    if isinstance(context, dict):
        # Copilot leaves used_percentage null and reports current_context_used_percentage.
        used = context.get("used_percentage")
        if not isinstance(used, (int, float)):
            used = context.get("current_context_used_percentage")
        if isinstance(used, (int, float)):
            record["context_used_percentage"] = round(used)
    # Copilot's AI Credits for the session, in billionths.
    ai_used = payload.get("ai_used")
    if isinstance(ai_used, dict) and isinstance(ai_used.get("total_nano_aiu"), (int, float)):
        record["ai_credits"] = round(ai_used["total_nano_aiu"] / 1e9, 2)
    if not record:
        return
    path = os.path.join(STATS_DIR, f"{os.path.basename(str(session_id))}.json")
    try:
        with open(path) as f:
            previous = json.load(f)
        previous.pop("updated", None)
        if previous == record:
            return
    except (OSError, ValueError, AttributeError):
        pass
    os.makedirs(STATS_DIR, exist_ok=True)
    write_atomic(path, {**record, "updated": int(time.time())})


def record_limits(payload: dict) -> None:
    limits = payload.get("rate_limits")
    # Absent before the session's first API response, or when not a subscriber.
    # Keep the last known numbers rather than erasing them.
    if not isinstance(limits, dict):
        return

    record = {"updated": int(time.time())}
    for name in WINDOWS:
        window = limits.get(name)
        # A window is left out once its resets_at has passed; leave it out too.
        if isinstance(window, dict) and "used_percentage" in window:
            record[name] = {
                "used_percentage": window.get("used_percentage"),
                "resets_at": window.get("resets_at"),
            }

    try:
        with open(USAGE_FILE) as f:
            previous = json.load(f)
        previous.pop("updated", None)
        if previous == {k: v for k, v in record.items() if k != "updated"}:
            # Unchanged; skip the write, but refresh `updated` at most once a minute.
            if time.time() - os.path.getmtime(USAGE_FILE) < 60:
                return
    except (OSError, ValueError, AttributeError):
        pass

    write_atomic(USAGE_FILE, record)


def main() -> None:
    payload = json.load(sys.stdin)
    for record in (record_stats, record_limits):
        try:
            record(payload)
        except Exception:  # noqa: BLE001 - one failing must not stop the other
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
