#!/usr/bin/env python3
"""Register this checkout in the current user's application menu."""
import os
from pathlib import Path


def exec_argument(value):
    # Desktop Exec quoting is applied after desktop-entry string unescaping.
    quoted = '"' + "".join("\\" + char if char in '\\"$`' else char for char in str(value)) + '"'
    return quoted.replace("\\", "\\\\").replace("%", "%%")


def main():
    launcher = Path(__file__).resolve().with_name("launch-assistant.sh")
    data_home = Path(os.environ.get("XDG_DATA_HOME", ""))
    if not data_home.is_absolute():
        data_home = Path.home() / ".local/share"
    applications = data_home / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / "gpt-linux-assistant.desktop"
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=GPT Linux Assistant\n"
        "Comment=Voice assistant for your Linux desktop\n"
        f"Exec=/bin/sh {exec_argument(launcher)}\n"
        "Icon=audio-input-microphone\n"
        "Terminal=false\n"
        "Categories=Utility;\n",
        encoding="utf-8",
    )
    print(f"Registered GPT Linux Assistant in the applications menu ({entry}).")


if __name__ == "__main__":
    main()
