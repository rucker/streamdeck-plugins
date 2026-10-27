#!/usr/bin/env python3
"""
Claude Code status line command that records your plan's usage limits for the
Usage meter on the deck.

Claude Code pipes a JSON payload to the status line on every update. For
Claude.ai subscribers it includes `rate_limits` (5-hour and weekly windows,
each with `used_percentage` and `resets_at`), which are the real numbers the
API reports, not an estimate. This writes them to USAGE_FILE atomically.

Prints nothing, so no status line is shown; it never fails, so a broken write
can't disturb Claude Code.
"""

import json
import os
import sys
import tempfile
import time

# Outside ~/.cache/agent-deck/ on purpose: every .json file there is read as a
# session state file.
USAGE_FILE = os.path.expanduser("~/.cache/agent-deck-usage.json")

WINDOWS = ("five_hour", "seven_day")


def main() -> None:
    payload = json.load(sys.stdin)
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

    directory = os.path.dirname(USAGE_FILE)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".agent-deck-usage.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(record, f)
    os.replace(tmp, USAGE_FILE)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
