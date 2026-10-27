# streamdeck-plugins

Plugins for Rick's Elgato Stream Deck+. The same physical deck moves between a Linux desktop and a Mac, and each OS drives it with its own app:

- **Linux:** [StreamController](https://github.com/StreamController/StreamController) (Flatpak `com.core447.StreamController`), with Python plugins in `com_rucker_*/`.
- **macOS:** Elgato's official Stream Deck app, with a TypeScript plugin in `elgato/`. StreamController can't be used here: on macOS it deliberately skips loading hardware decks.

User-facing docs are in `README.md`. This file covers what you need to work on the code.

## Layout

| Path | What |
|---|---|
| `hooks/claude_deck_hook.py` | Claude Code hook, shared by both platforms. Writes per-session state files. |
| `hooks/claude_deck_statusline.py` | Claude Code status line command, shared by both platforms. Writes `rate_limits` to `~/.cache/claude-deck-usage.json` for the Usage meter; prints nothing. |
| `install.sh` | OS-aware installer. Linux: symlinks `com_rucker_*` into StreamController. macOS: `npm ci && npm run build` in `elgato/`, then `streamdeck link`. Both: registers the hook in `~/.claude/settings.json`, replacing entries for an older hook path, and sets `statusLine` to the status line script unless a different status line is already set. |
| `com_rucker_ClaudeSessions/` | Linux Claude Sessions (StreamController plugin). |
| `com_rucker_PageNav/` | Linux only. Swipe the touch strip to change pages. Elgato's app does this natively. |
| `com_rucker_ResumeFix/` | Linux only. USB-resets the deck on resume so it doesn't stay dark. |
| `elgato/` | macOS Claude Sessions (Elgato SDK `@elgato/streamdeck` 3.x, Node, rollup). |

## Claude Sessions: two implementations, one contract

The hook writes `~/.cache/claude-deck/<session_id>.json` atomically, and both front ends read it. These fields are the contract:

- `session_id`, `cwd`
- `project`: taken from the first event and never changed afterwards, so the label stays stable when Claude `cd`s.
- `tmux_pane`: `$TMUX_PANE`, e.g. `%3`.
- `started`, `updated`, `since`: epoch seconds. `since` is when `state` last changed.
- `state`: `idle`, `working`, `done` or `permission`.
- `request`: one-line summary of a pending permission.
- `request_kind`: `tool` (from `PermissionRequest`; approvable from the deck) or `other` (Notification fallback; never approvable).

The Usage meter reads `~/.cache/claude-deck-usage.json`: `updated` plus optional `five_hour` and `seven_day`, each `{used_percentage, resets_at}` (epoch seconds), copied from the status line payload's `rate_limits`. A missing window, or one whose `resets_at` has passed, counts as 0%. The file deliberately lives outside `~/.cache/claude-deck/`, because every `.json` file in that directory is read as a session.

If you change the hook or the file format, update both `com_rucker_ClaudeSessions/sessions.py` and `elgato/src/sessions.ts`.

Behavior is meant to match across platforms. When you change one side, port the change to the other:

| Concern | Linux (Python) | macOS (TypeScript) |
|---|---|---|
| State, tmux order, pruning, approve | `sessions.py` | `src/sessions.ts` |
| Colors, labels, press/hold, slot numbering | `actions.py` | `src/actions/*.ts` (`base.ts` holds the shared parts) |
| Logo | `logo.py` (Pillow) | `src/render.ts` (SVG, same spark geometry) |
| Usage meter | `usage.py` (read + Pillow drawing), `UsageMeter` in `actions.py` | `src/usage.ts`, `meterSvg` in `src/render.ts`, `src/actions/usage-meter.ts` |

Behaviors that are easy to break:

- **Sort order:** sessions sort by tmux position (session name naturally, then window, then pane). Non-tmux sessions come last, by start time.
- **Unhooked placeholders:** a pane running `claude` with no state file shows as a placeholder (`tmux:%N`, state `unknown`).
- **Automatic slots:** slots with slot `0` number themselves in reading order (keys row by row, then dials) and skip sessions claimed by manually numbered slots.
- **Approve safety:** before sending `1`, approve checks with `tmux capture-pane` that the "❯ 1. Yes … Esc to cancel" dialog is on screen. It only ever sends `1`, never "don't ask again".
- **Pruning:** a session is dropped only after two consecutive "dead" sightings, 10s apart.
- **Watched sessions:** a session you're already looking at (its pane is tmux's active pane and the terminal is focused) doesn't count as waiting and doesn't blink. Only `permission` blinks.

## macOS specifics (`elgato/`)

- **Commands:** `npm run check` (tsc), `npm run build` (rollup → `com.rucker.claude-sessions.sdPlugin/bin/plugin.js`), `npm run watch` (rebuild + `streamdeck restart` on save), `npx streamdeck validate com.rucker.claude-sessions.sdPlugin`.
- **Logs:** `com.rucker.claude-sessions.sdPlugin/logs/`.
- **Terminal:** iTerm2 running plain tmux (same `tmux.conf` as Linux), not `tmux -CC` integration.
  - Raise it with `open -b com.googlecode.iterm2`.
  - Check focus with `lsappinfo front` + `lsappinfo info -only bundleid`.
  - Neither command triggers a macOS permission prompt. Avoid `osascript`, which does.
- **PATH:** the Stream Deck app starts plugins with a minimal PATH. `sessions.ts` adds `/opt/homebrew/bin` and `/usr/local/bin` so `tmux` resolves.
- **Rendering:**
  - Keys: 144×144 SVG data URLs via `setImage`.
  - Dials: one full-size pixmap (`layouts/canvas.json`, key `canvas`) set via `setFeedback`.
  - Text outlines are drawn as a stroked copy under the fill, because `paint-order` support in the app's SVG renderer isn't guaranteed.
- **Press and hold:** the SDK has no hold event. `base.ts` times key/dial down→up (500ms = hold = approve; a short release = jump). Touch taps use the payload's `hold` flag.
- **Slot setting:** a `<sdpi-select>` in `ui/session-slot.html`, stored as a string. Always parse it with `Number(...)`.
- **Optional user logo:** a PNG at `~/.local/share/claude-deck/logo.png` replaces the spark. It's kept out of the repo on purpose (trademark), and isn't recolored.

## Linux specifics

- **Flatpak:** StreamController runs in a Flatpak. Host commands go through `flatpak-spawn --host --directory=~`, and `--directory` is required.
- **Plugin manifests:** StreamController plugins need a `github` URL in `manifest.json` or `register()` fails. Use relative imports, because plugins load as `plugins.<folder>.main`.
- **Internal hooks:** Page Nav and Resume Fix monkeypatch StreamController internals (`DeckController.touchscreen_event_callback`, `DeckManager.on_resumed`). If an update breaks them, look there first.

## Status

- Linux: all three plugins are in daily use and confirmed working on the deck. The Usage meter is new (2026-10-26): the data path is verified with real `rate_limits`, but it has not yet been seen on the deck.
- macOS: written and validated on Linux (build, type-check, manifest validation, and rendering plus session reading against real tmux). **Not yet run in Elgato's app.** Still to verify on the Mac:
  - The plugin loads, and the actions appear under the "Claude Sessions" category.
  - Key and strip rendering in the real app, especially the text outline and fonts.
  - The iTerm2 focus check, jumping, and raising iTerm2.
  - Hold-to-approve timing on hardware.
  - The slot dropdown, and automatic numbering across keys and dials.
  - The Usage meter on a key and a dial (the status line script is shared, so its data is already verified on Linux).

## Conventions

- User-facing text is sentence case ("Your turn", "No sessions"). "APPROVE" is all caps on purpose.
- Commit only when Rick asks.
