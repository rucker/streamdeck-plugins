#!/usr/bin/env python3
"""
Demo Mode for the Agent Sessions deck plugins, shared by both front ends.

`start` opens a tmux session (DEMO_SESSION) with at least three agent sessions,
using whichever of Claude Code, Copilot and Grok are installed, and gives each
a small, harmless task in its own folder under DEMO_DIR. Claude Code and
Copilot stop to ask for approval along the way; Grok doesn't, since the deck
can't approve it yet. `stop` kills the tmux session and removes the demo's
session files and its output.

Exits 0 on success, 1 (with a message on stderr) on failure.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from itertools import cycle

DEMO_SESSION = "zz-demo"  # sorts after your own tmux sessions, so their keys don't move
DEMO_DIR = "/tmp/agent-deck-demo"
STATE_DIR = os.path.expanduser("~/.cache/agent-deck")
STATS_DIR = os.path.expanduser("~/.cache/agent-deck-stats")

AGENTS_FILE = os.path.join(DEMO_DIR, ".agents")
DETECT_TIMEOUT_SECONDS = 10
TRUST_TIMEOUT_SECONDS = 30

# Command, and what to add to the task. Claude Code asks once, to write the file;
# Copilot asks for the file and again for the shell command. Grok may only
# write files, without asking.
AGENTS = {
    "claude": (["claude", "--permission-mode", "default"], ""),
    "copilot": (["copilot", "-i"], " Then run `ls -la` in the shell."),
    "grok": (["grok", "--allow", "Edit", "--allow", "Write"], ""),
}

# One session per task, so at least three; agents repeat when fewer are
# installed. The folder is the session's label on the deck.
TASKS = [
    ("haiku", "Write a haiku about Stream Decks to haiku.txt."),
    ("octopus", "Create notes.md with three fun facts about octopuses."),
    ("limerick", "Write a short limerick about robots to limerick.txt."),
]

# Each agent asks to trust a new folder before it starts, with a different
# dialog and answer. Only answered when the dialog is on screen.
TRUST_DIALOGS = {
    "claude": (re.compile(r"❯\s*No, exit\s*\n\s*Yes, I trust this folder"), ["Down", "Enter"]),
    "copilot": (re.compile(r"Do you trust the files in this folder\?[\s│]*❯ 1\. Yes"), ["1"]),
    "grok": (re.compile(r"Do you trust the contents of this directory\?[\s\S]*Yes, proceed\s+y"), ["y"]),
}


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=5)


def demo_running() -> bool:
    return tmux("has-session", "-t", f"={DEMO_SESSION}").returncode == 0


def available_agents(pane: str) -> list[str] | None:
    """
    Asks the pane's own shell, which has your PATH (the plugin's is minimal,
    and tmux's lacks what your shell startup files add). None if it never answers.
    """
    try:
        os.remove(AGENTS_FILE)
    except OSError:
        pass
    partial = AGENTS_FILE + ".tmp"
    tmux("send-keys", "-t", pane,
         f"command -v {' '.join(AGENTS)} > {partial}; mv {partial} {AGENTS_FILE}; clear", "Enter")
    deadline = time.time() + DETECT_TIMEOUT_SECONDS
    while not os.path.exists(AGENTS_FILE):
        if time.time() > deadline:
            return None
        time.sleep(0.2)
    with open(AGENTS_FILE) as f:
        found = {os.path.basename(line.strip()) for line in f}
    return [agent for agent in AGENTS if agent in found]


def empty(directory: str):
    os.makedirs(directory, exist_ok=True)
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)


def start() -> int:
    if demo_running():
        return 0
    for name, _ in TASKS:
        empty(os.path.join(DEMO_DIR, name))

    first = new_pane(["new-session", "-d", "-s", DEMO_SESSION], TASKS[0][0])
    if not first:
        return 1
    agents = available_agents(first)
    if not agents:
        print("No agents found (claude, copilot or grok)" if agents == [] else "The shell in tmux didn't answer",
              file=sys.stderr)
        tmux("kill-session", "-t", f"={DEMO_SESSION}")
        return 1

    panes = {}
    for index, (agent, (name, task)) in enumerate(zip(cycle(agents), TASKS)):
        pane = first if index == 0 else new_pane(["new-window", "-t", f"{DEMO_SESSION}:"], name)
        if not pane:
            continue
        command, approval = AGENTS[agent]
        # Typed into the pane's shell, which has your PATH, and stays visible.
        tmux("send-keys", "-t", pane, shlex.join([*command, task + approval]), "Enter")
        panes[pane] = agent

    answer_trust_dialogs(panes)
    return 0


def new_pane(where: list[str], name: str) -> str | None:
    result = tmux(*where, "-n", name, "-c", os.path.join(DEMO_DIR, name), "-P", "-F", "#{pane_id}")
    if result.returncode != 0:
        print(f"tmux failed: {result.stderr.strip()}", file=sys.stderr)
        return None
    return result.stdout.strip()


def answer_trust_dialogs(panes: dict[str, str]):
    deadline = time.time() + TRUST_TIMEOUT_SECONDS
    while panes and time.time() < deadline and demo_running():
        for pane, agent in list(panes.items()):
            screen = tmux("capture-pane", "-p", "-t", pane)
            dialog, keys = TRUST_DIALOGS[agent]
            if screen.returncode == 0 and dialog.search(screen.stdout):
                tmux("send-keys", "-t", pane, *keys)
                del panes[pane]
        time.sleep(0.5)


def stop() -> int:
    result = tmux("list-panes", "-s", "-t", f"={DEMO_SESSION}", "-F", "#{pane_id}")
    panes = set(result.stdout.split()) if result.returncode == 0 else set()
    tmux("kill-session", "-t", f"={DEMO_SESSION}")

    for name in os.listdir(STATE_DIR) if os.path.isdir(STATE_DIR) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(STATE_DIR, name)) as f:
                session = json.load(f)
        except (OSError, ValueError):
            continue
        if session.get("tmux_pane") not in panes:
            continue
        for directory in (STATE_DIR, STATS_DIR):
            try:
                os.remove(os.path.join(directory, f"{session.get('session_id')}.json"))
            except OSError:
                pass

    # Keep the folders themselves: agents remember which folders you've trusted.
    for name, _ in TASKS:
        directory = os.path.join(DEMO_DIR, name)
        if os.path.isdir(directory):
            empty(directory)
    return 0


def main() -> int:
    commands = {"start": start, "stop": stop}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(f"usage: {os.path.basename(sys.argv[0])} start|stop", file=sys.stderr)
        return 1
    return commands[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
