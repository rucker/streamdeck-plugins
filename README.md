# streamdeck-plugins

Custom [StreamController](https://github.com/StreamController/StreamController) plugins for my Stream Deck+.

## Claude Sessions (`com_rucker_ClaudeSessions`)

Shows every running Claude Code session on the deck and jumps to it on press.

| Color | State | Meaning |
|---|---|---|
| Grey | ready | New session, nothing asked yet |
| Blue | working | Claude is busy |
| Orange (pulsing) | your turn | Claude finished and is waiting for you |
| Red (pulsing) | APPROVE | Blocked on a permission prompt or question |

**Actions**

- **Session Slot** (key or dial): the Nth session, numbered by start order. Press to jump.
- **Next Waiting Session** (key or dial): how many sessions need you. Press to jump to the one that has waited longest; permission prompts come first.
- **Session Picker** (dial): turn to pick a session, press or tap the strip to jump.

**How it works**

1. `hooks/claude_deck_hook.py` runs on Claude Code's `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Notification`, `Stop` and `SessionEnd` hooks, and writes `~/.cache/claude-deck/<session_id>.json` with the state, project and `$TMUX_PANE`.
2. The plugin reads those files every tick. Jumping runs `tmux switch-client`/`select-pane` on the host (via `flatpak-spawn --host`) and raises the terminal through the [Window Calls](https://github.com/ickyicky/window-calls) GNOME extension.
3. Every 10s, sessions whose tmux pane is gone, or has dropped back to a shell, are pruned.

**Requirements:** Claude Code running inside tmux, gnome-terminal, and the Window Calls GNOME extension.

**Install:** `com_rucker_ClaudeSessions/install.sh`, then restart StreamController and any running Claude sessions.
