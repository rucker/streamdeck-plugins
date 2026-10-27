#!/usr/bin/env bash
# Installs the deck plugins for this OS and the Agent Sessions state hook.
#
#   Linux: symlinks every com_rucker_* plugin into StreamController's (Flatpak)
#          plugin dir.
#   macOS: builds the Elgato Stream Deck plugin and links it into the Stream
#          Deck app (needs Node 20+ and Elgato's CLI: npm i -g @elgato/cli),
#          and imports its ready-made Stream Deck+ profile if it isn't there yet.
#   Both:  registers hooks/claude_deck_hook.py in ~/.claude/settings.json (Claude
#          Code, and Grok, which reads Claude's hooks) and, if Copilot is
#          installed, in ~/.copilot/settings.json (idempotent; replaces entries
#          pointing at an old copy; backs up first). Also sets
#          hooks/claude_deck_statusline.py as Claude's status line (feeds the
#          Usage meter) unless you already have a status line of your own.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/hooks/claude_deck_hook.py"
statusline="$here/hooks/claude_deck_statusline.py"
settings="$HOME/.claude/settings.json"
copilot_settings="$HOME/.copilot/settings.json"

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
        next="Quit and reopen the Stream Deck app to load the plugin, then restart any running agent sessions."
    else
        next="Install Elgato's CLI (npm i -g @elgato/cli), then: streamdeck link $elgato/com.rucker.claude-sessions.sdPlugin"
    fi
    # A linked plugin doesn't get its bundled profile installed, so import it,
    # once: the app adds a new copy on every import.
    profiles="$HOME/Library/Application Support/com.elgato.StreamDeck/ProfilesV3"
    # Before the rename, the profile was called "Claude Sessions".
    if ! grep -qsE '"Name":"(Agent|Claude) Sessions"' "$profiles"/*.sdProfile/manifest.json; then
        open "$elgato/com.rucker.claude-sessions.sdPlugin/profiles/claude-sessions.streamDeckProfile"
        echo "Imported the Agent Sessions profile into the Stream Deck app"
    fi
    ;;
*)
    echo "Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

chmod +x "$hook" "$statusline"
stamp="$(date +%Y%m%d%H%M%S)"
[ -f "$settings" ] && cp "$settings" "$settings.bak.$stamp"
has_copilot=0
if command -v copilot >/dev/null || [ -d "$HOME/.copilot" ]; then
    has_copilot=1
    [ -f "$copilot_settings" ] && cp "$copilot_settings" "$copilot_settings.bak.$stamp"
fi

python3 -I - "$settings" "$hook" "$statusline" "$copilot_settings" "$has_copilot" <<'EOF'
import json, os, sys

settings_path, hook, statusline, copilot_path, has_copilot = sys.argv[1:6]
events = ["SessionStart", "UserPromptSubmit", "PermissionRequest", "PostToolUse",
          "PostToolUseFailure", "Notification", "Stop", "SessionEnd"]


def load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(path: str, settings: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def register(settings: dict, command: str) -> None:
    def is_ours(h: dict) -> bool:
        # Also matches entries for a copy of the hook that has since moved.
        return os.path.basename(hook) in str(h.get("command", ""))

    hooks = settings.setdefault("hooks", {})
    for event in events:
        groups = hooks.setdefault(event, [])
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not is_ours(h)]
        groups[:] = [g for g in groups if g["hooks"]]
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})


settings = load(settings_path)
register(settings, f"python3 -I {hook}")

# The status line is a single setting, so never replace someone else's.
current = settings.get("statusLine")
current_command = str(current.get("command", "")) if isinstance(current, dict) else ""
if not current or current_command.endswith(os.path.basename(statusline)):
    settings["statusLine"] = {"type": "command", "command": f"python3 -I {statusline}"}
    print(f"Set the status line to {statusline} (feeds the Usage meter)")
else:
    print(f"Left your status line alone; the Usage meter needs {statusline} "
          "to receive the status line JSON (pipe it in from yours).")

save(settings_path, settings)
print(f"Registered {hook} for {', '.join(events)} in {settings_path} (Claude Code and Grok)")

if has_copilot == "1":
    # Copilot sends Claude-style payloads when hooks use Claude's event names.
    copilot = load(copilot_path)
    register(copilot, f"python3 -I {hook} --agent copilot")
    save(copilot_path, copilot)
    print(f"Registered {hook} in {copilot_path} (GitHub Copilot)")
EOF

echo "$next"
