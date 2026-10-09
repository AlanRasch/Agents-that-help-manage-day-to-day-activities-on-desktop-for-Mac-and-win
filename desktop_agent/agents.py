"""Agent definitions: templates, validation, saving to disk, and schedules."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .skills import ALL_SKILLS

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

TEMPLATES: dict[str, dict] = {
    "file-organizer": {
        "description": "Keeps Downloads tidy by sorting loose files into category folders.",
        "instructions": "You keep the user's Downloads folder organised. Preview the plan first with a dry run. "
                        "Only move files when the user has asked you to apply the plan.",
        "task": "organize downloads",
        "skills": ["list_files", "organize_folder", "notify"],
        "schedule": "18:00",
    },
    "daily-briefing": {
        "description": "Sends a morning summary of the date, disk space and reminders.",
        "instructions": "You prepare a short, friendly daily briefing for the user using the daily summary skill.",
        "task": "daily summary",
        "skills": ["daily_summary", "notify"],
        "schedule": "08:30",
    },
    "reminder-helper": {
        "description": "Creates and lists reminders from plain-language requests.",
        "instructions": "You help the user remember things. Turn requests into reminders with clear times, "
                        "and confirm each one you create.",
        "task": "my reminders",
        "skills": ["add_reminder", "list_reminders", "notify"],
        "schedule": None,
    },
    "file-finder": {
        "description": "Finds, reads and opens files in your allowed folders.",
        "instructions": "You help the user find and read their files. Never guess file names: search first.",
        "task": "list desktop",
        "skills": ["list_files", "find_files", "read_text", "open_item"],
        "schedule": None,
    },
    "custom": {
        "description": "A blank agent you describe yourself.",
        "instructions": "You are a helpful desktop assistant.",
        "task": "",
        "skills": ["list_files", "notify"],
        "schedule": None,
    },
}


@dataclass
class AgentSpec:
    name: str
    description: str
    instructions: str
    skills: list[str]
    task: str = ""                     # the standing job used for scheduled runs
    schedule: str | None = None        # "HH:MM" each day, or None
    auto_apply: bool = False           # may a scheduled run change files? (off by default)
    enabled: bool = True
    last_run_date: str | None = None   # "YYYY-MM-DD" of the last scheduled run
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSpec":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def validate(spec: AgentSpec) -> None:
    if not NAME_RE.match(spec.name):
        raise ValueError("Name must be 2-40 characters: lowercase letters, digits, '-' or '_', starting with a letter.")
    unknown = [s for s in spec.skills if s not in ALL_SKILLS]
    if unknown:
        raise ValueError(f"Unknown skills: {', '.join(unknown)}. Available: {', '.join(ALL_SKILLS)}")
    if not spec.skills:
        raise ValueError("An agent needs at least one skill.")
    if spec.schedule is not None and not TIME_RE.match(spec.schedule):
        raise ValueError("Schedule must be a time like 18:00, or none.")


def parse_schedule(text: str | None) -> str | None:
    """'18:00' -> '18:00'; 'none' -> None."""
    if text is None or text.lower() == "none":
        return None
    return text


def from_template(template: str, name: str, *, instructions: str | None = None, skills: list[str] | None = None,
                  schedule: str | None = None, auto_apply: bool = False, description: str | None = None) -> AgentSpec:
    """Create a spec from a template. Any argument given overrides the template's value."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template '{template}'. Choose from: {', '.join(TEMPLATES)}")
    t = TEMPLATES[template]
    spec = AgentSpec(
        name=name,
        description=description or t["description"],
        instructions=instructions or t["instructions"],
        skills=list(skills) if skills else list(t["skills"]),
        task=t.get("task", ""),
        schedule=parse_schedule(schedule) if schedule is not None else t.get("schedule"),
        auto_apply=auto_apply,
    )
    validate(spec)
    return spec


class AgentStore:
    """Agents saved as JSON in the data folder. Every change is written immediately."""

    UPDATABLE = {"description", "instructions", "skills", "task", "schedule", "auto_apply", "enabled", "last_run_date"}

    def __init__(self, path: Path):
        self.path = Path(path)
        self._agents: dict[str, AgentSpec] = {}
        self.load()

    def load(self) -> None:
        self._agents = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("agents", []):
                spec = AgentSpec.from_dict(item)
                self._agents[spec.name] = spec

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "agents": [a.to_dict() for a in self.all()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, spec: AgentSpec) -> AgentSpec:
        validate(spec)
        if spec.name in self._agents:
            raise ValueError(f"An agent named '{spec.name}' already exists.")
        self._agents[spec.name] = spec
        self._save()
        return spec

    def get(self, name: str) -> AgentSpec:
        if name not in self._agents:
            raise ValueError(f"No agent named '{name}'. See: agents list")
        return self._agents[name]

    def update(self, name: str, **changes) -> AgentSpec:
        spec = self.get(name)
        for key, value in changes.items():
            if value is None:  # not given -> leave unchanged
                continue
            if key not in self.UPDATABLE:
                raise ValueError(f"Cannot change '{key}'.")
            if key == "schedule":
                value = parse_schedule(value)
            setattr(spec, key, value)
        validate(spec)
        self._save()
        return spec

    def remove(self, name: str) -> None:
        self.get(name)
        del self._agents[name]
        self._save()

    def all(self) -> list[AgentSpec]:
        return sorted(self._agents.values(), key=lambda a: a.name)


def due_agents(agents: list[AgentSpec], now: datetime) -> list[AgentSpec]:
    """Enabled agents whose scheduled time is this minute and that have not run yet today."""
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    return [a for a in agents if a.enabled and a.schedule == hhmm and a.last_run_date != today]
