"""Skills: the actions an agent can take on the desktop.

Every skill is guarded:
  * paths must be inside the allowed folders (see config.py)
  * nothing is ever deleted and existing files are never overwritten
  * moving files is a dry run unless explicitly applied
  * background (scheduled) runs cannot change anything unless the agent allows it
"""

from __future__ import annotations

import itertools
import shutil
from dataclasses import asdict, dataclass
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .platform_utils import notify_command, open_command, os_name, run_quietly

CATEGORIES: dict[str, set[str]] = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".svg", ".bmp", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".pages", ".odt"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".numbers", ".ods"},
    "Presentations": {".ppt", ".pptx", ".key", ".odp"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Audio": {".mp3", ".wav", ".m4a", ".flac", ".aac"},
    "Video": {".mp4", ".mov", ".avi", ".mkv", ".wmv"},
    "Installers": {".dmg", ".pkg", ".exe", ".msi"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".c", ".cpp", ".go"},
}
READABLE_LIMIT = 200_000  # bytes read from a text file at most


class SafetyError(Exception):
    """Raised when an action would leave the allowed folders or break a rule."""


def category_for(path: Path) -> str:
    suffix = path.suffix.lower()
    for name, suffixes in CATEGORIES.items():
        if suffix in suffixes:
            return name
    return "Other"


@dataclass
class Reminder:
    id: int
    text: str
    at: str          # ISO date-time, local time
    done: bool = False


class ReminderStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> list[Reminder]:
        if not self.path.exists():
            return []
        return [Reminder(**r) for r in json.loads(self.path.read_text(encoding="utf-8"))]

    def _save(self, items: list[Reminder]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(r) for r in items], indent=2), encoding="utf-8")

    def add(self, text: str, at: datetime) -> Reminder:
        items = self._load()
        new = Reminder(id=max((r.id for r in items), default=0) + 1, text=text, at=at.isoformat(timespec="minutes"))
        items.append(new)
        self._save(items)
        return new

    def pending(self) -> list[Reminder]:
        return sorted((r for r in self._load() if not r.done), key=lambda r: r.at)

    def due(self, now: datetime) -> list[Reminder]:
        """Return reminders whose time has come and mark them done."""
        items = self._load()
        ready = [r for r in items if not r.done and datetime.fromisoformat(r.at) <= now]
        for r in ready:
            r.done = True
        if ready:
            self._save(items)
        return ready


def _pretty(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")


def parse_when(text: str, now: datetime) -> datetime:
    """'15:30' means the next 15:30; 'YYYY-MM-DD HH:MM' is an exact date and time."""
    text = text.strip()
    if text.count(":") == 1 and len(text) <= 5 and text.replace(":", "").isdigit():
        h, m = (int(x) for x in text.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Time must be between 00:00 and 23:59")
        when = now.replace(hour=h, minute=m, second=0, microsecond=0)
        return when if when > now else when + timedelta(days=1)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("Use HH:MM (e.g. 15:30) or 'YYYY-MM-DD HH:MM'") from None


# Tool descriptions the language model sees. Names match Skills methods.
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_files": {
        "name": "list_files",
        "description": "List the files and folders in an allowed folder.",
        "input_schema": {"type": "object", "properties": {"folder": {"type": "string"}}},
    },
    "find_files": {
        "name": "find_files",
        "description": "Find files whose name contains a word, searching inside an allowed folder.",
        "input_schema": {
            "type": "object",
            "properties": {"folder": {"type": "string"}, "name_contains": {"type": "string"}},
            "required": ["name_contains"],
        },
    },
    "organize_folder": {
        "name": "organize_folder",
        "description": "Sort the loose files in a folder into category subfolders (Images, Documents, ...). "
                        "Dry run unless apply is true. Only set apply to true when the user explicitly asked to move files.",
        "input_schema": {
            "type": "object",
            "properties": {"folder": {"type": "string"}, "apply": {"type": "boolean"}},
            "required": ["folder"],
        },
    },
    "read_text": {
        "name": "read_text",
        "description": "Read the beginning of a text file (txt, md, csv, json, py, ...).",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    "write_text": {
        "name": "write_text",
        "description": "Create a NEW text file inside an allowed folder. Existing files are never overwritten.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    "open_item": {
        "name": "open_item",
        "description": "Open a file, folder or web address (http/https) in the default app.",
        "input_schema": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
    },
    "add_reminder": {
        "name": "add_reminder",
        "description": "Create a reminder that pops up as a notification at a given time.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "when": {"type": "string", "description": "HH:MM or YYYY-MM-DD HH:MM"}},
            "required": ["text", "when"],
        },
    },
    "list_reminders": {
        "name": "list_reminders",
        "description": "List reminders that have not fired yet.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "daily_summary": {
        "name": "daily_summary",
        "description": "Summary of today: date, free disk space, Downloads count, and upcoming reminders.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "notify": {
        "name": "notify",
        "description": "Show a desktop notification.",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "message": {"type": "string"}},
            "required": ["message"],
        },
    },
}
ALL_SKILLS = list(TOOL_SCHEMAS)
WRITE_SKILLS = {"write_text", "open_item"}  # always blocked in background runs


class Skills:
    def __init__(self, folders: list[Path], data_dir: Path, system: str | None = None):
        self.folders = [Path(f).expanduser().resolve() for f in folders]
        self.system = os_name(system)
        self.reminders = ReminderStore(Path(data_dir) / "reminders.json")

    # ----- safety -----
    def check_path(self, path: str | Path) -> Path:
        """Resolve a path and make sure it is inside an allowed folder (symlinks are followed)."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.folders[0] / p
        resolved = p.resolve()
        for root in self.folders:
            if resolved == root or root in resolved.parents:
                return resolved
        allowed = ", ".join(str(f) for f in self.folders)
        raise SafetyError(f"'{resolved}' is outside your allowed folders ({allowed}).")

    @staticmethod
    def _unique(target: Path) -> Path:
        if not target.exists():
            return target
        for i in itertools.count(2):
            candidate = target.with_name(f"{target.stem} ({i}){target.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError("unreachable")

    def folder_by_name(self, name: str) -> str:
        """Full path of an allowed folder such as 'Downloads'; falls back to the first allowed folder."""
        match = next((f for f in self.folders if f.name.lower() == name.lower()), None)
        return str(match or self.folders[0])

    # ----- files -----
    def list_files(self, folder: str = ".") -> str:
        root = self.check_path(folder)
        if not root.is_dir():
            raise SafetyError(f"'{root}' is not a folder.")
        items = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        lines = [f"{'📄' if p.is_file() else '📁'} {p.name}" for p in items[:200]]
        more = f"\n…and {len(items) - 200} more" if len(items) > 200 else ""
        return "\n".join(lines) + more if lines else "(empty folder)"

    def find_files(self, name_contains: str, folder: str = ".") -> str:
        root = self.check_path(folder)
        needle = name_contains.lower()
        hits: list[str] = []
        for scanned, p in enumerate(root.rglob("*")):
            if scanned > 20_000:
                break
            if p.is_file() and needle in p.name.lower():
                hits.append(str(p))
                if len(hits) >= 30:
                    break
        return "\n".join(hits) or f"No files with '{name_contains}' in the name."

    def organize_folder(self, folder: str, apply: bool = False) -> str:
        root = self.check_path(folder)
        if not root.is_dir():
            raise SafetyError(f"'{root}' is not a folder.")
        loose = [p for p in root.iterdir() if p.is_file() and not p.name.startswith(".")]
        if not loose:
            return "Nothing to organise: no loose files in that folder."
        plan = [(p, root / category_for(p) / p.name) for p in sorted(loose)]
        if not apply:
            lines = [f"  {src.name}  →  {dst.parent.name}/" for src, dst in plan]
            return "DRY RUN, nothing moved yet:\n" + "\n".join(lines) + \
                   "\nAsk to apply the plan to move these files."
        moved = []
        for src, dst in plan:
            dst.parent.mkdir(exist_ok=True)
            final = self._unique(dst)  # never overwrite
            shutil.move(str(src), str(final))
            moved.append(f"{src.name} → {final.parent.name}/{final.name}")
        return f"Moved {len(moved)} file(s):\n" + "\n".join(moved)

    def read_text(self, path: str) -> str:
        p = self.check_path(path)
        if not p.is_file():
            raise SafetyError(f"'{p}' is not a file.")
        data = p.read_bytes()[:READABLE_LIMIT]
        return data.decode("utf-8", errors="replace")

    def write_text(self, path: str, content: str) -> str:
        p = self.check_path(path)
        if p.exists():
            raise SafetyError(f"'{p.name}' already exists. Choose a new file name.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Created {p}"

    def open_item(self, target: str) -> str:
        if target.lower().startswith(("http://", "https://")):
            resolved = target
        else:
            resolved = str(self.check_path(target))
            if not Path(resolved).exists():
                return f"Nothing found at {resolved}."
        ok = run_quietly(open_command(self.system, resolved))
        return f"Opened {target}." if ok else f"Could not open {target}."

    # ----- reminders, notifications, summary -----
    def notify(self, message: str, title: str = "Desktop Agent") -> str:
        cmd = notify_command(self.system, title, message)
        if cmd and run_quietly(cmd):
            return "Notification shown."
        print(f"[{title}] {message}")
        return "Notification printed to the terminal (no desktop notification support found)."

    def add_reminder(self, text: str, when: str, now: datetime | None = None) -> str:
        at = parse_when(when, now or datetime.now())
        r = self.reminders.add(text, at)
        return f"Reminder #{r.id} set for {at:%Y-%m-%d %H:%M}: {text}"

    def list_reminders(self) -> str:
        items = self.reminders.pending()
        return "\n".join(f"#{r.id} {_pretty(r.at)}  {r.text}" for r in items) or "No upcoming reminders."

    def daily_summary(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        free_gb = shutil.disk_usage(self.folders[0]).free / 1e9
        downloads = next((f for f in self.folders if f.name == "Downloads"), None)
        dl_count = sum(1 for p in downloads.iterdir() if p.is_file()) if downloads and downloads.exists() else 0
        lines = [
            f"Good {'morning' if now.hour < 12 else 'afternoon' if now.hour < 18 else 'evening'}! "
            f"It is {now:%A %d %B %Y, %H:%M}.",
            f"Free disk space: {free_gb:.1f} GB.",
            f"Loose files in Downloads: {dl_count}.",
        ]
        upcoming = self.reminders.pending()[:5]
        lines.append("Upcoming reminders:\n" + "\n".join(f"  • {_pretty(r.at)}  {r.text}" for r in upcoming)
                     if upcoming else "No upcoming reminders.")
        return "\n".join(lines)

    # ----- dispatch -----
    def call(self, name: str, args: dict[str, Any], allow_writes: bool = True) -> str:
        """Run a skill by name. Errors are returned as text so the agent can recover."""
        if name not in TOOL_SCHEMAS:
            return f"Error: unknown skill '{name}'."
        if not allow_writes and name in WRITE_SKILLS:
            return "Error: this agent is not allowed to change things in background runs."
        if name == "organize_folder" and not allow_writes:
            args = {**args, "apply": False}
        try:
            method = getattr(self, name)
            return str(method(**args))
        except SafetyError as e:
            return f"Blocked: {e}"
        except (TypeError, ValueError, OSError) as e:
            return f"Error: {e}"
