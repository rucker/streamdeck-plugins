# streamdeck-plugins

Custom plugins for my Stream Deck+: [StreamController](https://github.com/StreamController/StreamController) plugins for Linux (`com_rucker_*`), and an Elgato Stream Deck app plugin for macOS (`elgato/`).

**Install:** `./install.sh`. On Linux it links every `com_rucker_*` plugin into StreamController; on macOS it builds and links the Elgato plugin. On both it registers the Claude Sessions hook in `~/.claude/settings.json`, and sets the status line command that feeds the Usage meter (unless you already have a status line). Then restart StreamController (or the Stream Deck app) and any running Claude sessions.

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
- **Usage Meter** (key or dial): your plan's 5-hour and weekly usage limits as bars, with the time until each resets. Green, orange from 70%, red from 90%.

A session you're already looking at (its tmux pane is active and the terminal has focus) doesn't count as waiting and doesn't pulse. On a dial, a red session's strip segment shows what Claude is asking for, e.g. `$ npm test` or `Edit main.py`.

**Approving from the deck** answers "1. Yes" (never "don't ask again"), and only when the request came from a `PermissionRequest` hook (not a question) and the dialog is verifiably on screen (`tmux capture-pane`). Otherwise the key shows an error and nothing is sent.

**Usage meter data** is the real limit usage the API reports to Claude Code (subscribers only), not an estimate. `hooks/claude_deck_statusline.py` is registered as Claude Code's status line command: it receives `rate_limits` on every status line update, writes it to `~/.cache/claude-deck-usage.json`, and prints nothing. The numbers only move while a Claude Code session is talking to the API, so usage elsewhere (claude.ai, the apps) shows up with the next response. If you have your own status line, install.sh leaves it alone; pipe its stdin into `claude_deck_statusline.py` as well.

**Logo:** a Claude-style spark (drawn in code by `logo.py`) sits at the top of Next Waiting, in the corner of each session key, and faded on empty slots. To use the official Claude logo instead, save a PNG to `~/.local/share/claude-deck/logo.png` and restart StreamController. It's kept outside this repo on purpose, so the trademark isn't redistributed. On orange and red keys the logo is drawn as a cream silhouette.

**How it works**

1. `hooks/claude_deck_hook.py` (shared by both platforms) runs on Claude Code's `SessionStart`, `UserPromptSubmit`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `Notification`, `Stop` and `SessionEnd` hooks, and writes `~/.cache/claude-deck/<session_id>.json` with the state, project, `$TMUX_PANE` and a one-line summary of any pending permission request.
2. The plugin reads those files every tick. Jumping runs `tmux switch-client`/`select-pane` on the host (via `flatpak-spawn --host`) and raises the terminal through the [Window Calls](https://github.com/ickyicky/window-calls) GNOME extension.
3. Every 10s, sessions whose tmux pane is gone, or has dropped back to a shell, are pruned.

**Requirements (Linux):** Claude Code running inside tmux, gnome-terminal, and the Window Calls GNOME extension.


### On macOS (`elgato/`)

The same four actions for Elgato's Stream Deck app, written in TypeScript with Elgato's SDK. They read the same hook state files, so the behavior and look match the Linux version, with a few platform differences:

- Jumping runs the same tmux commands, then brings iTerm2 forward with `open -b com.googlecode.iterm2`. "Already looking at it" means iTerm2 is the frontmost app (`lsappinfo front`) and the pane is tmux's active one. Neither needs an Automation or Accessibility permission. Plain tmux inside iTerm2 is assumed, not `tmux -CC` integration.
- The Stream Deck app starts plugins with a minimal PATH, so the plugin adds `/opt/homebrew/bin` and `/usr/local/bin` to find tmux.
- The slot number is a dropdown in the key's settings panel (Automatic, or Session 1–32).
- install.sh imports a ready-made "Claude Sessions" profile for the Stream Deck+ (once; it's skipped if a profile by that name exists). It has Next Waiting plus seven automatic slots on the keys, and the Usage Meter and Session Picker on the first two dials. The other two dials are left free. Pick it from the profile menu in the app. The layout is generated by `elgato/scripts/profile.py` during `npm run build`.
- A user logo at `~/.local/share/claude-deck/logo.png` is used as-is; it isn't recolored on orange/red keys.

**Requirements (macOS):** Claude Code running inside tmux in iTerm2, Elgato's Stream Deck app 7.1+, Node 20+, and Elgato's CLI (`npm i -g @elgato/cli`) for linking.

**Developing:** in `elgato/`, `npm run check` type-checks, `npm run build` bundles into `com.rucker.claude-sessions.sdPlugin/bin/`, and `npm run watch` rebuilds and restarts the plugin on save. Logs are in `com.rucker.claude-sessions.sdPlugin/logs/`.

## Page Nav (`com_rucker_PageNav`)

Linux only (Elgato's app does this itself). Swipe the touch strip to change pages, on every page, with nothing to set up per page:

- **Swipe left:** next page
- **Swipe right:** previous page

Pages follow the Page Manager's order and wrap around. Swipes never reach the page's own touch strip action (e.g. Better Volume Mixer Plus scrolls through apps on a swipe; that's lost); taps still work. A swipe while the screensaver is showing just wakes the deck.

StreamController has no global inputs, so this wraps `DeckController.touchscreen_event_callback`, an internal rather than plugin API. If an update breaks it, swiping just stops changing pages.


## Resume Fix (`com_rucker_ResumeFix`)

Linux only. Wakes the deck after suspend. StreamController notices the resume and reloads the page, but the deck can stay dark until the app is restarted. A restart works because startup USB-resets the deck first. This plugin makes resume do the same: close the old handles, USB-reset the deck, then let the normal resume code reopen it and reload the page.

Use it with Settings → "Use new resume mode (beta)" **off**; the beta mode takes a different path that this doesn't touch. Like Page Nav, it wraps an internal (`DeckManager.on_resumed`), not plugin API.
