"""Operating-system differences in one place: folders, notifications, opening files."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def os_name(system: str | None = None) -> str:
    """Return 'macos', 'windows' or 'linux'."""
    system = system or platform.system()
    return {"Darwin": "macos", "Windows": "windows"}.get(system, "linux")


def default_data_dir(system: str | None = None) -> Path:
    home = Path.home()
    kind = os_name(system)
    if kind == "macos":
        return home / "Library" / "Application Support" / "DesktopAgent"
    if kind == "windows":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "DesktopAgent"
    return Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "desktop-agent"


def default_folders() -> list[Path]:
    """Folders agents may use. Works on macOS, Windows and Linux."""
    home = Path.home()
    return [home / "Desktop", home / "Downloads", home / "Documents"]


def notify_command(system: str, title: str, message: str) -> list[str] | None:
    """Build the command that shows a desktop notification, or None if unsupported."""
    if system == "macos":
        script = f"display notification {json.dumps(message, ensure_ascii=False)} " \
                 f"with title {json.dumps(title, ensure_ascii=False)}"
        return ["osascript", "-e", script]
    if system == "windows":
        t = title.replace("'", "''")
        m = message.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
            "$n = New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
            f"$n.ShowBalloonTip(5000, '{t}', '{m}', [System.Windows.Forms.ToolTipIcon]::Info); "
            "Start-Sleep -Seconds 6; $n.Dispose()"
        )
        return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps]
    if system == "linux" and shutil.which("notify-send"):
        return ["notify-send", title, message]
    return None


def open_command(system: str, target: str) -> list[str]:
    """Build the command that opens a file, folder or web address with the default app."""
    if system == "macos":
        return ["open", target]
    if system == "windows":
        return ["cmd", "/c", "start", "", target]
    return ["xdg-open", target]


def run_quietly(cmd: list[str], timeout: int = 15) -> bool:
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
