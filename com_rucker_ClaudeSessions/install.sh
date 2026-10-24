#!/usr/bin/env bash
# Installs the Claude Sessions plugin:
#   1. symlinks this folder into StreamController's (Flatpak) plugin dir
#   2. registers the state hook in ~/.claude/settings.json (idempotent; backs up first)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_id="$(basename "$here")"
plugin_dir="$HOME/.var/app/com.core447.StreamController/data/plugins"
hook="$here/hooks/claude_deck_hook.py"
settings="$HOME/.claude/settings.json"

mkdir -p "$plugin_dir"
ln -sfn "$here" "$plugin_dir/$plugin_id"
echo "Linked $plugin_dir/$plugin_id -> $here"

chmod +x "$hook"
[ -f "$settings" ] && cp "$settings" "$settings.bak.$(date +%Y%m%d%H%M%S)"

python3 -I - "$settings" "$hook" <<'EOF'
import json, os, sys

settings_path, hook = sys.argv[1], sys.argv[2]
events = ["SessionStart", "UserPromptSubmit", "PermissionRequest", "PostToolUse",
          "PostToolUseFailure", "Notification", "Stop", "SessionEnd"]
command = f"python3 -I {hook}"

try:
    with open(settings_path) as f:
        settings = json.load(f)
except FileNotFoundError:
    settings = {}

hooks = settings.setdefault("hooks", {})
for event in events:
    groups = hooks.setdefault(event, [])
    already = any(h.get("command") == command for g in groups for h in g.get("hooks", []))
    if not already:
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print(f"Registered hook for {', '.join(events)} in {settings_path}")
EOF

echo "Restart StreamController to load the plugin."
