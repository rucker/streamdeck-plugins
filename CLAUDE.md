# streamdeck-plugins

Plugins for Rick's Elgato Stream Deck+. The same physical deck moves between a Linux desktop and a Mac, and each OS drives it with its own app:

- **Linux:** [StreamController](https://github.com/StreamController/StreamController) (Flatpak `com.core447.StreamController`), with Python plugins in `com_rucker_*/`.
- **macOS:** Elgato's official Stream Deck app, with a TypeScript plugin in `elgato/`. StreamController can't be used here: on macOS it deliberately skips loading hardware decks.

User-facing docs are in `README.md`. This file covers what you need to work on the code.

## Layout

| Path | What |
|---|---|
| `hooks/agent_deck_hook.py` | Agent hook (Claude Code, Copilot, Grok), shared by both platforms. Writes per-session state files. |
| `hooks/agent_deck_statusline.py` | Claude Code status line command, shared by both platforms. Writes `rate_limits` to `~/.cache/agent-deck-usage.json` for the Usage meter; prints nothing. |
| `install.sh` | OS-aware installer. Linux: symlinks `com_rucker_*` into StreamController. macOS: `npm ci && npm run build` in `elgato/`, then `streamdeck link`. Both: registers the hook in `~/.claude/settings.json` (Claude Code and Grok) and, if Copilot is installed, `~/.copilot/settings.json` (with `--agent copilot`), replacing entries for an older hook path, and sets `statusLine` to the status line script unless a different status line is already set. |
| `com_rucker_AgentSessions/` | Linux Agent Sessions (StreamController plugin). |
| `com_rucker_PageNav/` | Linux only. Swipe the touch strip to change pages. Elgato's app does this natively. |
| `com_rucker_ResumeFix/` | Linux only. USB-resets the deck on resume so it doesn't stay dark. |
| `elgato/` | macOS Agent Sessions (Elgato SDK `@elgato/streamdeck` 3.x, Node, rollup). |
| `tools/render_agent_logos.py` | Renders the agent logo SVGs (`elgato/…sdPlugin/imgs/agents/`) to PNGs for Linux (`com_rucker_AgentSessions/assets/`). Needs PySide6. Rerun after changing a logo. |

Agent Sessions was called Claude Sessions until 2026-10-27, and its IDs and files said "claude" (`com.rucker.claude-sessions`, `com_rucker_ClaudeSessions`, `~/.cache/claude-deck/`, `claude_deck_hook.py`, `claude_deck_statusline.py`, `~/.cache/claude-deck-usage.json`). `install.sh` migrates from those names: it rewrites the old plugin IDs in saved deck layouts (after archiving the layout folder, and only while the app is closed), removes the old plugin links, moves the state and usage files, and replaces hook and status line entries that use the old filenames. "Claude" stays only where something really is Claude's: the `claude` agent, its approval dialog, the Usage meter's rate limits, `~/.claude/settings.json`, and this file.

## Agent Sessions: two implementations, one contract

The hook writes `~/.cache/agent-deck/<session_id>.json` atomically, and both front ends read it. These fields are the contract:

- `session_id`, `cwd`
- `agent`: `claude`, `copilot` or `grok`. Missing means `claude` (files from before the field existed).
- `project`: taken from the first event and never changed afterwards, so the label stays stable when the agent `cd`s.
- `tmux_pane`: `$TMUX_PANE`, e.g. `%3`.
- `started`, `updated`, `since`: epoch seconds. `since` is when `state` last changed.
- `state`: `idle`, `working`, `done` or `permission`.
- `request`: one-line summary of a pending permission.
- `request_kind`: `tool` (a `PermissionRequest` from Claude Code or Copilot; approvable from the deck) or `other` (a Notification fallback, or an agent whose dialog the deck can't recognize; never approvable).

How each agent feeds the hook (verified with Copilot CLI 1.0.104 and Grok 1.0.70):

- **Claude Code:** the reference format.
- **Grok:** reads hooks from `~/.claude/settings.json` and sends Claude's snake_case keys. The hook tells it apart by `$GROK_HOOK_EVENT`. It has no `PermissionRequest` (a pending approval comes as `Notification` / `permission_prompt`), and it sends one more `Stop` after `SessionEnd`, so `Stop` and `Notification` never create a session.
- **Copilot:** hooks registered under Claude's event names get Claude-style payloads, except `PermissionRequest`, which is camelCase (`sessionId`, `toolName`, `toolInput`) with no `hook_event_name`. `normalize()` in the hook maps it. Interactive Copilot fires `SessionStart` only with the first prompt, not at launch, so until then a new session is just an unhooked placeholder.

The Usage meter reads `~/.cache/agent-deck-usage.json`: `updated` plus optional `five_hour` and `seven_day`, each `{used_percentage, resets_at}` (epoch seconds), copied from the status line payload's `rate_limits`. A missing window, or one whose `resets_at` has passed, counts as 0%. The file deliberately lives outside `~/.cache/agent-deck/`, because every `.json` file in that directory is read as a session.

If you change the hook or the file format, update both `com_rucker_AgentSessions/sessions.py` and `elgato/src/sessions.ts`.

Behavior is meant to match across platforms. When you change one side, port the change to the other:

| Concern | Linux (Python) | macOS (TypeScript) |
|---|---|---|
| State, tmux order, pruning, approve | `sessions.py` | `src/sessions.ts` |
| Colors, labels, press/hold, slot numbering | `actions.py` | `src/actions/*.ts` (`base.ts` holds the shared parts) |
| Logo and agent badges | `logo.py` (Pillow; badges from `assets/*.png`) | `src/render.ts` (SVG, same spark geometry; badges from `imgs/agents/*.svg`) |
| Usage meter | `usage.py` (read + Pillow drawing), `UsageMeter` in `actions.py` | `src/usage.ts`, `meterSvg` in `src/render.ts`, `src/actions/usage-meter.ts` |

Behaviors that are easy to break:

- **Sort order:** sessions sort by tmux position (session name naturally, then window, then pane). Non-tmux sessions come last, by start time.
- **Unhooked placeholders:** a pane running an agent with no state file shows as a placeholder (`tmux:%N`, state `unknown`). The agent comes from `#{pane_current_command}`: `copilot`, `grok` (or its platform binary name, e.g. `grok-macos-aarc`, truncated by tmux), or `claude`, which can also show up as Claude Code's version number (e.g. `2.1.311`, its process title on macOS).
- **Automatic slots:** slots with slot `0` number themselves in reading order (keys row by row, then dials) and skip sessions claimed by manually numbered slots.
- **Approve safety:** before sending `1`, approve checks with `tmux capture-pane` that the "❯ 1. Yes … Esc to cancel" dialog is on screen. It only ever sends `1`, never "don't ask again". Each approvable agent has its own pattern in `APPROVE_DIALOGS` (both front ends) and is listed in the hook's `APPROVABLE`. Copilot's dialog sits in a box ("Do you want to …?", then `❯ 1. Yes`, footer "↑/↓ to navigate · enter to select · esc to cancel"), and "1" answers it directly. Its pattern deliberately doesn't match Copilot's folder-trust question. Grok isn't approvable yet.
- **Colors:** the agent sets the hue and the state its strength (`AGENT_COLORS` in `base.ts` and `actions.py`): "your turn" is the agent's full color, "working" a dimmed one. Ready and No status are near-black, and approve is yellow pulsing to mustard, for every agent. Keys whose background is light (`isLight` / `is_light`, luminance above 0.7: Grok's "your turn" and bright approve) get dark text and a ringed badge, decided from the color itself.
- **Badges:** session keys show the agent's logo, unaltered, on a white disc (bottom-right). Don't recolor the logos: that's what the brand guidelines forbid. The drawn spark (Next Waiting, empty slots) is ours and can be tinted.
- **Pruning:** a session is dropped only after two consecutive "dead" sightings, 10s apart.
- **Watched sessions:** a session you're already looking at (its pane is tmux's active pane and the terminal is focused) doesn't count as waiting and doesn't blink. Only `permission` blinks.

## macOS specifics (`elgato/`)

- **Commands:** `npm run check` (tsc), `npm run build` (rollup → `com.rucker.agent-sessions.sdPlugin/bin/plugin.js`), `npm run watch` (rebuild + `streamdeck restart` on save; needs developer mode), `npx streamdeck validate com.rucker.agent-sessions.sdPlugin`.
- **Logs:** `com.rucker.agent-sessions.sdPlugin/logs/`.
- **Terminal:** iTerm2 running plain tmux (same `tmux.conf` as Linux), not `tmux -CC` integration.
  - Raise it with `open -b com.googlecode.iterm2`.
  - Check focus with `lsappinfo front` + `lsappinfo info -only bundleid`.
  - Neither command triggers a macOS permission prompt. Avoid `osascript`, which does.
- **Environment:** the Stream Deck app starts plugins with a minimal PATH and no locale. `sessions.ts` adds `/opt/homebrew/bin` and `/usr/local/bin` so `tmux` resolves, and sets `LANG=en_US.UTF-8`: without a UTF-8 locale tmux prints the tabs in `-F` formats as `_`, which silently broke tmux ordering and unhooked placeholders. To reproduce the plugin's view, run code under `env -i HOME=$HOME PATH=/usr/bin:/bin`.
- **Rendering:**
  - Keys: 144×144 SVG data URLs via `setImage`.
  - Dials: one full-size pixmap (`layouts/canvas.json`, key `canvas`) set via `setFeedback`.
  - Text outlines are drawn as a stroked copy under the fill, because `paint-order` support in the app's SVG renderer isn't guaranteed.
  - Key images are drawn by Qt's SVG Tiny renderer, which ignores `x`/`y` on `<tspan>`, `dominant-baseline` and `rgba()`. Give every line its own `<text>` with an explicit baseline. To preview keys the way the app draws them, render the SVG with PySide6's `QSvgRenderer`.
- **Press and hold:** the SDK has no hold event. `base.ts` times key/dial down→up (500ms = hold = approve; a short release = jump). Touch taps use the payload's `hold` flag.
- **Slot setting:** a `<sdpi-select>` in `ui/session-slot.html`, stored as a string. Always parse it with `Number(...)`.
- **Bundled profile:** `scripts/profile.py` writes `profiles/agent-sessions.streamDeckProfile` (Stream Deck+ only) as part of `npm run build`. The app installs bundled profiles only for packaged plugins, not linked ones, so `install.sh` imports it with `open`, once.
- **Agent logos:** `render.ts` reads `imgs/agents/<agent>.svg` (located from `import.meta.url`) and inlines its paths, since Qt's renderer can't be trusted with nested `<image>` SVGs. Licensing and sources are in `imgs/agents/NOTICE.md`.

## Linux specifics

- **Flatpak:** StreamController runs in a Flatpak. Host commands go through `flatpak-spawn --host --directory=~`, and `--directory` is required.
- **Plugin manifests:** StreamController plugins need a `github` URL in `manifest.json` or `register()` fails. Use relative imports, because plugins load as `plugins.<folder>.main`.
- **Internal hooks:** Page Nav and Resume Fix monkeypatch StreamController internals (`DeckController.touchscreen_event_callback`, `DeckManager.on_resumed`). If an update breaks them, look there first.

## Status

- Linux: all three plugins are in daily use and confirmed working on the deck. The Usage meter is new (2026-10-26): the data path is verified with real `rate_limits`, but it has not yet been seen on the deck.
- macOS: installed and running on the Mac (2026-10-27, Stream Deck app 7.6, the app's bundled Node 24). Confirmed:
  - The plugin loads and connects, and the actions appear under the plugin's category and work on the deck.
  - The hook and status line register, and the hook writes session state on macOS.
  - The bundled profile imports with the expected layout.
  - Key and touch strip rendering and fonts, the iTerm2 focus check, jumping to the pane, and the Usage meter.
  - The slot dropdown, and automatic numbering across keys and dials.
  - Gotcha: `streamdeck restart` (and so `npm run watch`) only works with the app in developer mode. Without it, the app logs the restart link as handled and keeps the old plugin process, and the CLI still prints "Restarted". Rick's Mac has developer mode on (`streamdeck dev`, enabled 2026-10-27). `install.sh` deliberately doesn't turn it on, since it's an app-wide setting; it tells you to relaunch the app instead. To confirm a reload, check that the PID from `pgrep -f agent-sessions.sdPlugin/bin/plugin.js` changed.

  Still to verify on the Mac: hold-to-approve timing on hardware.
- Agent Sessions (2026-10-27): the hook was verified end to end with real Copilot and Grok runs on the Mac (states, agent field, cleanup on exit), and the badges were checked with Qt's renderer and Pillow. On the Mac's deck, Copilot sessions show up (with their badge) once they've had a prompt. Fixed after that: unhooked placeholders and tmux ordering (the locale bug above, verified in the plugin's environment), and Copilot approval (verified end to end against a real Copilot dialog through the plugin's approve code). Confirmed on the Mac's deck (2026-10-27): holding to approve Copilot, and "No status" placeholders for idle Copilot and Grok sessions. Still to verify: everything on Linux, where the plugin changes are compiled but untested in StreamController.

## Conventions

- User-facing text is sentence case ("Your turn", "No sessions"). "APPROVE" is all caps on purpose.
- Commit only when Rick asks.
