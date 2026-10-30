# streamdeck-plugins

Custom plugins for my Stream Deck+: [StreamController](https://github.com/StreamController/StreamController) plugins for Linux (`com_rucker_*`), and an Elgato Stream Deck app plugin for macOS (`elgato/`).

**Install:** `./install.sh`. Upgrading from when the plugin was called Claude Sessions? On macOS, quit the Stream Deck app first: the installer moves your layouts, sessions and hooks over to the new names, and won't touch the layouts while the app is running. On Linux it stops StreamController, links every `com_rucker_*` plugin, adds a ready-made "Agent Sessions" page (unless you already have one by that name), and starts StreamController again; on macOS it builds and links the Elgato plugin. On both it registers the Agent Sessions hook in `~/.claude/settings.json` (used by Claude Code and Grok) and, if Copilot is installed, in `~/.copilot/settings.json`, and sets the status line command that feeds the Usage meter (unless you already have a status line). Then restart the Stream Deck app on macOS, and any running agent sessions.

## Agent Sessions (`com_rucker_AgentSessions`)

Shows every running coding agent session on the deck and jumps to it on press. Supported agents: **Claude Code**, **GitHub Copilot CLI** and **Grok**. Each session key shows its agent's logo in a corner badge.

Each agent has its own color. The state sets how strong it is: full strength when it's your turn, dimmed while the agent works.

| State | Claude Code | Copilot | Grok | Meaning |
|---|---|---|---|---|
| Your turn | Orange | Blue | Near-white | The agent finished and is waiting for you |
| Working | Brown | Dark blue | Grey | The agent is busy |
| Ready | Near-black | Near-black | Near-black | New session, nothing asked yet |
| No status | Near-black | Near-black | Near-black | An agent is running in tmux but hasn't fired a hook yet (e.g. started before the hooks were installed, or a Copilot session before its first prompt) |
| APPROVE | Yellow (pulsing) | Yellow (pulsing) | Yellow (pulsing) | Blocked on a permission prompt or question |

Light keys (Grok's "your turn", and approve) use dark text.

**Actions**

- **Session Slot** (key or dial): one session per key. Press to jump; **long-press to approve** a pending tool permission. Slots are automatic by default: drop several on a page and they fill in reading order (keys row by row, then dials). Sessions follow tmux window order, so keys renumber the way tmux windows do (`renumber-windows`); sessions outside tmux come last. Set a slot number (1–32) to pin a key to the Nth session instead; automatic slots skip pinned ones.
- **Next Waiting Session** (key or dial): how many sessions need you. Press to jump to the one that has waited longest; permission prompts come first.
- **Session Picker** (dial): turn to pick a session, press or tap the strip to jump; long-press to approve.
- **Usage Meter** (key or dial): your Claude plan's 5-hour and weekly usage limits as bars, with the time until each resets. Green, orange from 70%, red from 90%.
- **Demo Mode** (key): press to start a demo, which opens a tmux session `zz-demo` with three agent sessions doing small tasks, and they show up on your session keys. While it runs, the key is green: press to jump to the demo, **long-press to stop it**. Your own sessions are left alone.

A session you're already looking at (its tmux pane is active and the terminal has focus) doesn't count as waiting and doesn't pulse. On a dial, a red session's strip segment shows what the agent is asking for, e.g. `$ npm test` or `Edit main.py`.

**Context use:** each session key shows how full that session's context window is, e.g. `44%`, in the bottom-left corner next to the badge (centered at the bottom on Linux). It comes from each agent's status line, so it appears once a session has updated its status line, which is after its first prompt. Copilot keys also show the AI Credits (AIC) the session has used, on the line above (e.g. `2.25`, `842`, `4.2k`, `12k`).

**Approving from the deck** answers a one-time "Yes" (never "don't ask again" or always-approve), and only for a tool approval (not a question) whose dialog is verifiably on screen (`tmux capture-pane`). Otherwise the key shows an error and nothing is sent. This works for Claude Code, Copilot and Grok, each with its own dialog check. Grok's "Yes" isn't always the same option (3 for a file edit, 2 for a shell command), so the deck reads which one it is from the screen, and sends nothing if you've moved the highlight off it. Once you've answered a dialog, from the deck or in the terminal, the key switches to "Working" within about 2s, by noticing that the dialog has left the screen (the agents send nothing until the approved command finishes).

**Demo Mode** (`hooks/agent_deck_demo.py`, shared by both platforms) uses whichever of Claude Code, Copilot and Grok are installed, one session each, repeating agents to make three. Each works in its own folder under `/tmp/agent-deck-demo/` (`haiku`, `octopus`, `limerick`, which become the key labels), writing a poem or a few octopus facts. Each agent stops to ask for approval, so you can approve from the deck: Claude Code to write its file, Copilot for its file and then a shell command (`ls -la`), and Grok for a shell command (`date > done.txt`), after writing its file without asking (`--allow Edit --allow Write`). The script answers each agent's "trust this folder" prompt when it sees it on screen (session-only for Copilot). Stopping kills the tmux session, removes its sessions from the deck right away, and empties the folders. The folders themselves stay, because agents remember which folders you've trusted.

**Usage meter data** is the real limit usage the API reports to Claude Code (subscribers only), not an estimate. `hooks/agent_deck_statusline.py` is registered as Claude Code's status line command: it receives `rate_limits` on every status line update, writes it to `~/.cache/agent-deck-usage.json`, and prints nothing. The numbers only move while a Claude Code session is talking to the API, so usage elsewhere (claude.ai, the apps) shows up with the next response. The same script is registered as Copilot's and Grok's status line too, where it records each session's context use (and Copilot's AI Credits). If you have your own status line in any of the three, install.sh leaves it alone; pipe its stdin into `agent_deck_statusline.py` as well.

**Logos:** each session key has its agent's logo on a white disc in the bottom-right corner, so every logo stays legible and unaltered on any key color. The logos come from [LobeHub Icons](https://github.com/lobehub/lobe-icons) (MIT); see `elgato/com.rucker.agent-sessions.sdPlugin/imgs/agents/NOTICE.md`. They're trademarks of Anthropic, GitHub and xAI, used only to show which agent a session belongs to. The plugin's own mark is a robot head drawn in code (`logo.py`, `render.ts`): at the top of Next Waiting, faded on empty slots, and as the plugin's icon in the Stream Deck app. It's steel grey, and dark on light keys.

**How it works**

1. `hooks/agent_deck_hook.py` (shared by both platforms) runs on the `SessionStart`, `UserPromptSubmit`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `Notification`, `Stop` and `SessionEnd` hooks, and writes `~/.cache/agent-deck/<session_id>.json` with the agent, state, project, `$TMUX_PANE` and a one-line summary of any pending permission request. All three agents speak Claude Code's hook format: Claude Code runs it from `~/.claude/settings.json`, Grok reads that same file (on folders you've trusted in Grok), and Copilot runs it from `~/.copilot/settings.json` with `--agent copilot`.
2. The plugin reads those files every tick. Jumping runs `tmux switch-client`/`select-pane` on the host (via `flatpak-spawn --host`) and raises the terminal through the [Window Calls](https://github.com/ickyicky/window-calls) GNOME extension.
3. Every 10s, sessions whose tmux pane is gone, or has dropped back to a shell, are pruned.

**Requirements (Linux):** the agents running inside tmux, gnome-terminal, and the Window Calls GNOME extension.


### On macOS (`elgato/`)

The same five actions for Elgato's Stream Deck app, written in TypeScript with Elgato's SDK. They read the same hook state files, so the behavior and look match the Linux version, with a few platform differences:

- Jumping runs the same tmux commands, then brings iTerm2 forward with `open -b com.googlecode.iterm2`. "Already looking at it" means iTerm2 is the frontmost app (`lsappinfo front`) and the pane is tmux's active one. Neither needs an Automation or Accessibility permission. Plain tmux inside iTerm2 is assumed, not `tmux -CC` integration.
- The Stream Deck app starts plugins with a minimal PATH, so the plugin adds `/opt/homebrew/bin` and `/usr/local/bin` to find tmux.
- The slot number is a dropdown in the key's settings panel (Automatic, or Session 1–32).
- **Deck recovery:** when the Mac wakes with the deck plugged in (e.g. plugging the laptop back into a KVM), the Stream Deck app sometimes fails to reconnect to it and never tries again, so the deck keeps showing its last images until you unplug and replug it. The plugin watches the app's log for that failure and replugs the deck in software (`bin/reenumerate`, built from `native/reenumerate.c`): about 10s later the deck is back, on the page it was on, without restarting the app. It tries up to 3 times in 2 minutes per deck.
- install.sh imports a ready-made "Agent Sessions" profile for the Stream Deck+ (once; it's skipped if any profile already uses the plugin). It has Next Waiting plus seven automatic slots on the keys, and the Usage Meter and Session Picker on the first two dials. The other two dials are left free. Pick it from the profile menu in the app. The layout is generated by `elgato/scripts/profile.py` during `npm run build`.

**Requirements (macOS):** the agents running inside tmux in iTerm2, Elgato's Stream Deck app 7.1+, Node 20+, and Elgato's CLI (`npm i -g @elgato/cli`) for linking.

**Developing:** in `elgato/`, `npm run check` type-checks, `npm run build` bundles into `com.rucker.agent-sessions.sdPlugin/bin/`, and `npm run watch` rebuilds and restarts the plugin on save. Restarting the plugin from the command line (`streamdeck restart com.rucker.agent-sessions`, which `npm run watch` uses) needs the Stream Deck app's developer mode. Turn it on with `streamdeck dev` (`streamdeck dev -d` turns it off). Without it the command reports success but the old plugin keeps running, so quit and reopen the app instead. Logs are in `com.rucker.agent-sessions.sdPlugin/logs/`.

## Page Nav (`com_rucker_PageNav`)

Linux only (Elgato's app does this itself). Swipe the touch strip to change pages, on every page, with nothing to set up per page:

- **Swipe left:** next page
- **Swipe right:** previous page

Pages follow the Page Manager's order and wrap around. Swipes never reach the page's own touch strip action (e.g. Better Volume Mixer Plus scrolls through apps on a swipe; that's lost); taps still work. A swipe while the screensaver is showing just wakes the deck.

StreamController has no global inputs, so this wraps `DeckController.touchscreen_event_callback`, an internal rather than plugin API. If an update breaks it, swiping just stops changing pages.


## Resume Fix (`com_rucker_ResumeFix`)

Linux only. Wakes the deck after suspend. StreamController notices the resume and reloads the page, but the deck can stay dark until the app is restarted. A restart works because startup USB-resets the deck first. This plugin makes resume do the same: close the old handles, USB-reset the deck, then let the normal resume code reopen it and reload the page.

Use it with Settings → "Use new resume mode (beta)" **off**; the beta mode takes a different path that this doesn't touch. Like Page Nav, it wraps an internal (`DeckManager.on_resumed`), not plugin API.
