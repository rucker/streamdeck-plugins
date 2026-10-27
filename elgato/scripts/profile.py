"""Builds the bundled Stream Deck+ profile (a zip of the app's ProfilesV3 layout)."""

import json
import os
import sys
import uuid
import zipfile

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "com.rucker.claude-sessions.sdPlugin")
OUT = os.path.join(PLUGIN_DIR, "profiles", "claude-sessions.streamDeckProfile")
STREAM_DECK_PLUS = "20GBD9901"
NAMESPACE = uuid.UUID("6f1c7a52-3d0e-4b8e-9a51-0c2f6a1d7e43")

KEYS = {"0,0": "next-waiting", **{f"{c},{r}": "slot" for r in range(2) for c in range(4) if (c, r) != (0, 0)}}
DIALS = {"0,0": "usage", "1,0": "dial"}


def stable_id(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def main() -> None:
    with open(os.path.join(PLUGIN_DIR, "manifest.json")) as f:
        manifest = json.load(f)
    plugin = {"Name": manifest["Name"], "UUID": manifest["UUID"], "Version": manifest["Version"]}
    names = {a["UUID"]: a["Name"] for a in manifest["Actions"]}

    def actions(controller: str, layout: dict[str, str]) -> dict:
        out = {}
        for pos, short in layout.items():
            action_uuid = f"{plugin['UUID']}.{short}"
            states = [{}] if controller == "Encoder" else [{
                "FontFamily": "", "FontSize": 12, "FontStyle": "", "FontUnderline": False,
                "OutlineThickness": 2, "ShowTitle": False, "TitleAlignment": "bottom", "TitleColor": "#ffffff",
            }]
            out[pos] = {
                "ActionID": stable_id(f"{controller}/{pos}"), "LinkedTitle": True, "Name": names[action_uuid],
                "Plugin": plugin, "Resources": None, "Settings": {}, "State": 0, "States": states,
                "UUID": action_uuid,
            }
        return out

    profile_id, page_id, default_page_id = (stable_id(n).upper() for n in ("profile", "page", "default-page"))
    root = f"Profiles/{profile_id}.sdProfile"
    files = {
        "package.json": {
            "AppVersion": manifest["Software"]["MinimumVersion"], "DeviceModel": STREAM_DECK_PLUS,
            "DeviceSettings": None, "FormatVersion": 1, "OSType": "macOS",
            "RequiredPlugins": [plugin["UUID"]],
        },
        f"{root}/manifest.json": {
            "Device": {"Model": STREAM_DECK_PLUS, "UUID": stable_id("device")},
            "Name": manifest["Name"],
            "Pages": {"Current": str(uuid.UUID(int=0)), "Default": default_page_id.lower(), "Pages": [page_id.lower()]},
            "Version": "3.0",
        },
        f"{root}/Profiles/{page_id}/manifest.json": {
            "Controllers": [
                {"Actions": actions("Keypad", KEYS), "Type": "Keypad"},
                {"Actions": actions("Encoder", DIALS), "Type": "Encoder"},
            ],
            "Icon": "", "Name": "",
        },
        f"{root}/Profiles/{default_page_id}/manifest.json": {
            "Controllers": [{"Actions": None, "Type": "Keypad"}, {"Actions": None, "Type": "Encoder"}],
            "Icon": "", "Name": "",
        },
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), json.dumps(content))
    print(f"Wrote {os.path.relpath(OUT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
