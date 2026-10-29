# streamdeck-plugins

Plugins for Rick's Elgato Stream Deck+. The same physical deck moves between a Linux desktop and a Mac, and each OS drives it with its own app:

- **Linux:** [StreamController](https://github.com/StreamController/StreamController) (Flatpak `com.core447.StreamController`), with Python plugins in `com_rucker_*/`.
- **macOS:** Elgato's official Stream Deck app, with a TypeScript plugin in `elgato/`. StreamController can't be used here: on macOS it deliberately skips loading hardware decks.

User-facing docs are in `README.md`. This file covers what you need to work on the code; macOS-only specifics are in `elgato/CLAUDE.md`.

## History

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

Session keys show how full each session's context window is, bottom-left beside the badge (centered at the bottom on Linux, where StreamController labels can't be left-aligned). It comes from `~/.cache/agent-deck-stats/<session_id>.json`: `context_used_percentage` (a whole number) and `updated`, written by the status line script from `context_window.used_percentage` (Claude Code, Grok) or `context_window.current_context_used_percentage` (Copilot, which leaves the first null). For Copilot it also has `ai_credits`: the AI Credits used this session (`ai_used.total_nano_aiu` / 10⁹, two decimals; matches the "Session: N AIC used" in Copilot's UI, verified with 1.0.105). Keys show it on the line above the context figure, abbreviated to at most 5 characters (`formatCredits` / `format_credits`: 2.25, 42.3, 842, 4.2k, 12k); the context figure stays level with the badge. Claude Code's and Grok's payloads have only `cost.total_cost_usd`; for Claude.ai subscribers that's an API-price estimate, not what's billed, so their keys deliberately show no second line (whether Grok's figure is a real charge is unverified). The status line's `session_id` matches the hook's for all three agents (verified). It's a separate file because the hook and the status line run independently: sharing the state file would let one overwrite the other's update. The hook's `SessionEnd` and the front ends' pruning remove it with the session. Copilot and Grok don't report plan limits to scripts (Copilot's status line has only session credits; Grok's says outright it sends no rate-limit summary), so the Usage meter stays Claude-only.

If you change the hook or the file format, update both `com_rucker_AgentSessions/sessions.py` and `elgato/src/sessions.ts`.

Behavior is meant to match across platforms. When you change one side, port the change to the other:

| Concern | Linux (Python) | macOS (TypeScript) |
|---|---|---|
| State, tmux order, pruning, approve | `sessions.py` | `src/sessions.ts` |
| Colors, labels, press/hold, slot numbering | `actions.py` | `src/actions/*.ts` (`base.ts` holds the shared parts) |
| Logo and agent badges | `logo.py` (Pillow; badges from `assets/*.png`) | `src/render.ts` (SVG, same robot geometry; badges from `imgs/agents/*.svg`) |
| Usage meter | `usage.py` (read + Pillow drawing), `UsageMeter` in `actions.py` | `src/usage.ts`, `meterSvg` in `src/render.ts`, `src/actions/usage-meter.ts` |

Behaviors that are easy to break:

- **Sort order:** sessions sort by tmux position (session name naturally, then window, then pane). Non-tmux sessions come last, by start time.
- **Unhooked placeholders:** a pane running an agent with no state file shows as a placeholder (`tmux:%N`, state `unknown`). The agent comes from `#{pane_current_command}`: `copilot`, `grok` (or its platform binary name, e.g. `grok-macos-aarc`, truncated by tmux), or `claude`, which can also show up as Claude Code's version number (e.g. `2.1.311`, its process title on macOS).
- **Automatic slots:** slots with slot `0` number themselves in reading order (keys row by row, then dials) and skip sessions claimed by manually numbered slots.
- **Approve safety:** before sending `1`, approve checks with `tmux capture-pane` that the "❯ 1. Yes … Esc to cancel" dialog is on screen. It only ever sends `1`, never "don't ask again". Each approvable agent has its own pattern in `APPROVE_DIALOGS` (both front ends) and is listed in the hook's `APPROVABLE`. Copilot's dialog sits in a box ("Do you want to …?", then `❯ 1. Yes`, footer "↑/↓ to navigate · enter to select · esc to cancel"), and "1" answers it directly. Its pattern deliberately doesn't match Copilot's folder-trust question. Grok isn't approvable yet.
- **Colors:** the agent sets the hue and the state its strength (`AGENT_COLORS` in `base.ts` and `actions.py`): "your turn" is the agent's full color, "working" a dimmed one. Ready and No status are near-black, and approve is yellow pulsing to mustard, for every agent. Keys whose background is light (`isLight` / `is_light`, luminance above 0.7: Grok's "your turn" and bright approve) get dark text and a ringed badge, decided from the color itself.
- **Badges:** session keys show the agent's logo, unaltered, on a white disc (bottom-right). Don't recolor the logos: that's what the brand guidelines forbid. The robot mark (Next Waiting, empty slots, the plugin icons in `imgs/`) is ours and can be tinted: steel grey, dark on light keys. Its geometry is a 100×100 grid shared by `logo.py` and `render.ts`.
- **Hooks must never block an agent:** the hook always exits 0, and `install.sh` registers it as `python3 -I … || true`. Without `|| true`, a hook that can't start (moved, renamed, `python3` missing) exits 2, which Claude Code, Copilot and Grok all read as "block this action". That happened once: a Copilot session started before the 2026-10-27 rename kept calling the old path and had its tool calls blocked. Running agents keep their hook list until restarted, so after moving the hook, restart them.
- **Pruning:** a session is dropped only after two consecutive "dead" sightings, 10s apart.
- **One session per pane:** when a session first writes from a tmux pane (new, or resumed there), the hook deletes any other session's files that name the same pane. Resuming or starting over inside a running agent (Copilot's `/resume`, for one) sends no `SessionEnd` for the old session, and since the pane still runs the agent, pruning would never drop it, leaving two keys for one pane.
- **Watched sessions:** a session you're already looking at (its pane is tmux's active pane and the terminal is focused) doesn't count as waiting and doesn't blink. Only `permission` blinks.

## Linux specifics

- **Flatpak:** StreamController runs in a Flatpak. Host commands go through `flatpak-spawn --host --directory=~`, and `--directory` is required.
- **Plugin manifests:** StreamController plugins need a `github` URL in `manifest.json` or `register()` fails. Use relative imports, because plugins load as `plugins.<folder>.main`.
- **Running check:** use `flatpak ps`, not `pgrep -f com.core447.StreamController`, which also matches plugin backends (e.g. the OBS plugin's) that run from paths containing the app ID.
- **Pages:** plain JSON in `data/pages/<name>.json`: `keys` keyed `"<col>x<row>"`, `dials` keyed by index, each `{"states": {"0": {"actions": [{"id": "<plugin>::<action>", "settings": {}}], …}}}`. The app only reads them at startup and may write its copy back, so edit them only while it's stopped.
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
