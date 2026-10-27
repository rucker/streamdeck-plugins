#!/usr/bin/env bash
# Installs the deck plugins for this OS and the Claude Sessions state hook.
#
#   Linux: symlinks every com_rucker_* plugin into StreamController's (Flatpak)
#          plugin dir.
#   macOS: builds the Elgato Stream Deck plugin and links it into the Stream
#          Deck app (needs Node 20+ and Elgato's CLI: npm i -g @elgato/cli),
#          and imports its ready-made Stream Deck+ profile if it isn't there yet.
#   Both:  registers hooks/claude_deck_hook.py in ~/.claude/settings.json
#          (idempotent; replaces entries pointing at an old copy; backs up first),
#          and hooks/claude_deck_statusline.py as the status line (feeds the
#          Usage meter) unless you already have a status line of your own.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/hooks/claude_deck_hook.py"
statusline="$here/hooks/claude_deck_statusline.py"
settings="$HOME/.claude/settings.json"

case "$(uname -s)" in
Linux)
    plugin_dir="$HOME/.var/app/com.core447.StreamController/data/plugins"
    mkdir -p "$plugin_dir"
    for plugin in "$here"/com_rucker_*/; do
        plugin="${plugin%/}"
        ln -sfn "$plugin" "$plugin_dir/$(basename "$plugin")"
        echo "Linked $plugin_dir/$(basename "$plugin") -> $plugin"
    done
    next="Restart StreamController to load the plugins."
    ;;
Darwin)
    elgato="$here/elgato"
    (cd "$elgato" && npm ci && npm run build)
    if command -v streamdeck >/dev/null; then
        streamdeck link "$elgato/com.rucker.claude-sessions.sdPlugin"
        next="Restart the Stream Deck app (streamdeck restart com.rucker.claude-sessions)."
    else
        next="Install Elgato's CLI (npm i -g @elgato/cli), then: streamdeck link $elgato/com.rucker.claude-sessions.sdPlugin"
    fi
    # A linked plugin doesn't get its bundled profile installed, so import it,
    # once: the app adds a new copy on every import.
    profiles="$HOME/Library/Application Support/com.elgato.StreamDeck/ProfilesV3"
    if ! grep -qs '"Name":"Claude Sessions"' "$profiles"/*.sdProfile/manifest.json; then
        open "$elgato/com.rucker.claude-sessions.sdPlugin/profiles/claude-sessions.streamDeckProfile"
        echo "Imported the Claude Sessions profile into the Stream Deck app"
    fi
    ;;
*)
    echo "Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

chmod +x "$hook" "$statusline"
[ -f "$settings" ] && cp "$settings" "$settings.bak.$(date +%Y%m%d%H%M%S)"

python3 -I - "$settings" "$hook" "$statusline" <<'EOF'
import json, os, sys

settings_path, hook, statusline = sys.argv[1:4]
events = ["SessionStart", "UserPromptSubmit", "PermissionRequest", "PostToolUse",
          "PostToolUseFailure", "Notification", "Stop", "SessionEnd"]
command = f"python3 -I {hook}"

try:
    with open(settings_path) as f:
        settings = json.load(f)
except FileNotFoundError:
    settings = {}


def is_ours(h: dict) -> bool:
    # Also matches entries for a copy of the hook that has since moved.
    return str(h.get("command", "")).endswith(os.path.basename(hook))


hooks = settings.setdefault("hooks", {})
for event in events:
    groups = hooks.setdefault(event, [])
    for g in groups:
        g["hooks"] = [h for h in g.get("hooks", []) if not is_ours(h)]
    groups[:] = [g for g in groups if g["hooks"]]
    groups.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})

# The status line is a single setting, so never replace someone else's.
current = settings.get("statusLine")
current_command = str(current.get("command", "")) if isinstance(current, dict) else ""
if not current or current_command.endswith(os.path.basename(statusline)):
    settings["statusLine"] = {"type": "command", "command": f"python3 -I {statusline}"}
    print(f"Set the status line to {statusline} (feeds the Usage meter)")
else:
    print(f"Left your status line alone; the Usage meter needs {statusline} "
          "to receive the status line JSON (pipe it in from yours).")

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print(f"Registered {hook} for {', '.join(events)} in {settings_path}")
EOF

echo "$next"
