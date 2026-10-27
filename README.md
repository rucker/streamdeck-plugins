# streamdeck-plugins

Custom [StreamController](https://github.com/StreamController/StreamController) plugins for my Stream Deck+.

## Claude Sessions (`com_rucker_ClaudeSessions`)

Shows every running Claude Code session on the deck and jumps to it on press.

| Color | State | Meaning |
|---|---|---|
| Grey | Ready | New session, nothing asked yet |
| Grey | No status | Claude is running in tmux but hasn't fired a hook yet (e.g. started before the hooks were installed) |
| Blue | Working | Claude is busy |
| Orange | Your turn | Claude finished and is waiting for you |
| Red (pulsing) | APPROVE | Blocked on a permission prompt or question |

**Actions**

- **Session Slot** (key or dial): one session per key. Press to jump; **long-press to approve** a pending tool permission. Slots are automatic by default: drop several on a page and they fill in reading order (keys row by row, then dials). Sessions follow tmux window order, so keys renumber the way tmux windows do (`renumber-windows`); sessions outside tmux come last. Set a slot number (1–32) to pin a key to the Nth session instead; automatic slots skip pinned ones.
- **Next Waiting Session** (key or dial): how many sessions need you. Press to jump to the one that has waited longest; permission prompts come first.
- **Session Picker** (dial): turn to pick a session, press or tap the strip to jump; long-press to approve.

A session you're already looking at (its tmux pane is active and the terminal has focus) doesn't count as waiting and doesn't pulse. On a dial, a red session's strip segment shows what Claude is asking for, e.g. `$ npm test` or `Edit main.py`.

**Approving from the deck** answers "1. Yes" (never "don't ask again"), and only when the request came from a `PermissionRequest` hook (not a question) and the dialog is verifiably on screen (`tmux capture-pane`). Otherwise the key shows an error and nothing is sent.

**Logo:** a Claude-style spark (drawn in code by `logo.py`) sits at the top of Next Waiting, in the corner of each session key, and faded on empty slots. To use the official Claude logo instead, save a PNG to `~/.local/share/claude-deck/logo.png` and restart StreamController. It's kept outside this repo on purpose, so the trademark isn't redistributed. On orange and red keys the logo is drawn as a cream silhouette.

**How it works**

1. `hooks/claude_deck_hook.py` runs on Claude Code's `SessionStart`, `UserPromptSubmit`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `Notification`, `Stop` and `SessionEnd` hooks, and writes `~/.cache/claude-deck/<session_id>.json` with the state, project, `$TMUX_PANE` and a one-line summary of any pending permission request.
2. The plugin reads those files every tick. Jumping runs `tmux switch-client`/`select-pane` on the host (via `flatpak-spawn --host`) and raises the terminal through the [Window Calls](https://github.com/ickyicky/window-calls) GNOME extension.
3. Every 10s, sessions whose tmux pane is gone, or has dropped back to a shell, are pruned.

**Requirements:** Claude Code running inside tmux, gnome-terminal, and the Window Calls GNOME extension.

**Install:** `com_rucker_ClaudeSessions/install.sh`, then restart StreamController and any running Claude sessions.

## Page Nav (`com_rucker_PageNav`)

Swipe the touch strip to change pages, on every page, with nothing to set up per page, like Elgato's own software:

- **Swipe left:** next page
- **Swipe right:** previous page

Pages follow the Page Manager's order and wrap around. Swipes never reach the page's own touch strip action (e.g. Better Volume Mixer Plus scrolls through apps on a swipe; that's lost); taps still work. A swipe while the screensaver is showing just wakes the deck.

StreamController has no global inputs, so this wraps `DeckController.touchscreen_event_callback`, an internal rather than plugin API. If an update breaks it, swiping just stops changing pages.

**Install:** `ln -s "$PWD/com_rucker_PageNav" ~/.var/app/com.core447.StreamController/data/plugins/`, then restart StreamController.

## Resume Fix (`com_rucker_ResumeFix`)

Wakes the deck after suspend. StreamController notices the resume and reloads the page, but the deck can stay dark until the app is restarted. A restart works because startup USB-resets the deck first. This plugin makes resume do the same: close the old handles, USB-reset the deck, then let the normal resume code reopen it and reload the page.

Use it with Settings → "Use new resume mode (beta)" **off**; the beta mode takes a different path that this doesn't touch. Like Page Nav, it wraps an internal (`DeckManager.on_resumed`), not plugin API.

**Install:** `ln -s "$PWD/com_rucker_ResumeFix" ~/.var/app/com.core447.StreamController/data/plugins/`, then restart StreamController.
