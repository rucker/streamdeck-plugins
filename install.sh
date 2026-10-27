#!/usr/bin/env bash
# Installs the deck plugins for this OS and the Agent Sessions state hook.
#
#   Linux: symlinks every com_rucker_* plugin into StreamController's (Flatpak)
#          plugin dir.
#   macOS: builds the Elgato Stream Deck plugin and links it into the Stream
#          Deck app (needs Node 20+ and Elgato's CLI: npm i -g @elgato/cli),
#          and imports its ready-made Stream Deck+ profile if it isn't there yet.
#   Both:  registers hooks/agent_deck_hook.py in ~/.claude/settings.json (Claude
#          Code, and Grok, which reads Claude's hooks) and, if Copilot is
#          installed, in ~/.copilot/settings.json (idempotent; replaces entries
#          pointing at an old copy; backs up first). Also sets
#          hooks/agent_deck_statusline.py as Claude's status line (feeds the
#          Usage meter) unless you already have a status line of your own.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/hooks/agent_deck_hook.py"
statusline="$here/hooks/agent_deck_statusline.py"
settings="$HOME/.claude/settings.json"
copilot_settings="$HOME/.copilot/settings.json"
grok_config="$HOME/.grok/config.toml"
stamp="$(date +%Y%m%d%H%M%S)"

# Until 2026-10-27 the plugin was Claude Sessions, and its IDs and files said
# "claude". migrate_layout rewrites old IDs in an app's saved layouts, after
# archiving the whole folder next to it. The app must not be running, or it
# could write its old copy back.
migrate_layout() {  # <layout dir> <old id> <new id> <app name> <running? command>
    local dir="$1" old="$2" new="$3" app="$4"
    shift 4
    grep -rqsIF "$old" "$dir" || return 0
    if "$@" >/dev/null; then
        echo "Your $app layouts still use the old plugin ID. Quit $app, then run this again." >&2
        exit 1
    fi
    tar -czf "$dir.bak.$stamp.tar.gz" -C "$(dirname "$dir")" "$(basename "$dir")"
    grep -rlsIF "$old" "$dir" | while IFS= read -r file; do
        python3 -I -c 'import sys; p, a, b = sys.argv[1:]; s = open(p).read(); open(p, "w").write(s.replace(a, b))' \
            "$file" "$old" "$new"
    done
    echo "Migrated your $app layouts to the new plugin ID (backup: $dir.bak.$stamp.tar.gz)"
}

case "$(uname -s)" in
Linux)
    data="$HOME/.var/app/com.core447.StreamController/data"
    plugin_dir="$data/plugins"
    migrate_layout "$data/pages" com_rucker_ClaudeSessions com_rucker_AgentSessions StreamController \
        pgrep -f com.core447.StreamController
    [ -L "$plugin_dir/com_rucker_ClaudeSessions" ] && rm "$plugin_dir/com_rucker_ClaudeSessions"
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
    app_data="$HOME/Library/Application Support/com.elgato.StreamDeck"
    profiles="$app_data/ProfilesV3"
    migrate_layout "$profiles" com.rucker.claude-sessions com.rucker.agent-sessions "Stream Deck" \
        pgrep -x "Stream Deck"
    [ -L "$app_data/Plugins/com.rucker.claude-sessions.sdPlugin" ] && rm "$app_data/Plugins/com.rucker.claude-sessions.sdPlugin"
    (cd "$elgato" && npm ci && npm run build)
    if command -v streamdeck >/dev/null; then
        streamdeck link "$elgato/com.rucker.agent-sessions.sdPlugin"
        next="Quit and reopen the Stream Deck app to load the plugin, then restart any running agent sessions."
    else
        next="Install Elgato's CLI (npm i -g @elgato/cli), then: streamdeck link $elgato/com.rucker.agent-sessions.sdPlugin"
    fi
    # A linked plugin doesn't get its bundled profile installed, so import it,
    # once (the app adds a new copy on every import): only if no profile uses
    # the plugin yet.
    if ! grep -rqsF com.rucker.agent-sessions "$profiles"; then
        open "$elgato/com.rucker.agent-sessions.sdPlugin/profiles/agent-sessions.streamDeckProfile"
        echo "Imported the Agent Sessions profile into the Stream Deck app"
    fi
    ;;
*)
    echo "Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

# Sessions and usage recorded under the old names keep showing.
if [ -d "$HOME/.cache/claude-deck" ]; then
    mkdir -p "$HOME/.cache/agent-deck"
    find "$HOME/.cache/claude-deck" -maxdepth 1 -name '*.json' -exec mv {} "$HOME/.cache/agent-deck/" \;
    rm -rf "$HOME/.cache/claude-deck"
fi
[ -f "$HOME/.cache/claude-deck-usage.json" ] && mv "$HOME/.cache/claude-deck-usage.json" "$HOME/.cache/agent-deck-usage.json"

chmod +x "$hook" "$statusline"
[ -f "$settings" ] && cp "$settings" "$settings.bak.$stamp"
has_copilot=0
if command -v copilot >/dev/null || [ -d "$HOME/.copilot" ]; then
    has_copilot=1
    [ -f "$copilot_settings" ] && cp "$copilot_settings" "$copilot_settings.bak.$stamp"
fi
has_grok=0
if command -v grok >/dev/null || [ -d "$HOME/.grok" ]; then
    has_grok=1
    [ -f "$grok_config" ] && cp "$grok_config" "$grok_config.bak.$stamp"
fi

python3 -I - "$settings" "$hook" "$statusline" "$copilot_settings" "$has_copilot" "$grok_config" "$has_grok" <<'EOF'
import json, os, sys

settings_path, hook, statusline, copilot_path, has_copilot, grok_path, has_grok = sys.argv[1:8]
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


# Names from before the rename to Agent Sessions.
OLD_HOOK, OLD_STATUSLINE = "claude_deck_hook.py", "claude_deck_statusline.py"


def register(settings: dict, command: str) -> None:
    def is_ours(h: dict) -> bool:
        # Also matches entries for a copy of the hook that has since moved or been renamed.
        command = str(h.get("command", ""))
        return os.path.basename(hook) in command or OLD_HOOK in command

    hooks = settings.setdefault("hooks", {})
    for event in events:
        groups = hooks.setdefault(event, [])
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not is_ours(h)]
        groups[:] = [g for g in groups if g["hooks"]]
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})


# "|| true": if the hook can't even start (moved, renamed, python3 missing),
# Python exits 2, which agents read as "block this action". The hook must
# never block an agent, so any failure to launch it counts as success.
settings = load(settings_path)
register(settings, f"python3 -I {hook} || true")

# The status line is a single setting, so never replace someone else's.
current = settings.get("statusLine")
current_command = str(current.get("command", "")) if isinstance(current, dict) else ""
if not current or current_command.endswith((os.path.basename(statusline), OLD_STATUSLINE)):
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
    register(copilot, f"python3 -I {hook} --agent copilot || true")
    # Its status line feeds the context figure on session keys.
    current = copilot.get("statusLine")
    if not current or os.path.basename(statusline) in str(current.get("command", "") if isinstance(current, dict) else ""):
        copilot["statusLine"] = {"type": "command", "command": f"python3 -I {statusline} || true"}
    else:
        print("Left Copilot's status line alone; session keys won't show its context use.")
    save(copilot_path, copilot)
    print(f"Registered {hook} and the status line in {copilot_path} (GitHub Copilot)")

if has_grok == "1":
    # Grok reads its hooks from Claude's settings, but its status line only from
    # its own config. Append one unless a status line is already configured.
    try:
        with open(grok_path) as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    try:
        import tomllib
        configured = "status_line" in tomllib.loads(text).get("ui", {})
    except ImportError:
        configured = "[ui.status_line]" in text
    except tomllib.TOMLDecodeError:
        configured = True  # not ours to fix; leave the file alone
    if not configured:
        os.makedirs(os.path.dirname(grok_path), exist_ok=True)
        with open(grok_path, "a") as f:
            f.write(("\n" if text and not text.endswith("\n") else "")
                    + f'\n# Agent Sessions: feeds the context figure on session keys; prints nothing.\n'
                    f'[ui.status_line]\ntype = "command"\ncommand = "python3 -I {statusline} || true"\n')
        print(f"Set Grok's status line in {grok_path}")
    elif os.path.basename(statusline) not in text:
        print("Left Grok's status line alone; session keys won't show its context use.")
EOF

echo "$next"
