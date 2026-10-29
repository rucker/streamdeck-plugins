# macOS Agent Sessions (`elgato/`)

The cross-platform contract and the behaviors both front ends share are in the root `CLAUDE.md`.

- **Validate the manifest:** `npx streamdeck validate com.rucker.agent-sessions.sdPlugin` (not an npm script).
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
