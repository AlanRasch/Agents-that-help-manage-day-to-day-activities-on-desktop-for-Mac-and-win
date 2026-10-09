"""Runs an agent's task.

With an Anthropic API key, Claude plans and calls the agent's skills (tool use).
Without a key, a built-in rule-based assistant handles common requests, so the
app still works offline and for demos.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .agents import AgentSpec
from .skills import TOOL_SCHEMAS, Skills

HELP = ("I can: organise a folder (\"organize downloads\"), show a summary (\"daily summary\"), "
        "set a reminder (\"remind me to call Sokha at 15:30\"), list reminders (\"my reminders\"), "
        "find files (\"find invoice\"), list a folder (\"list desktop\"), or open a file (\"open Desktop/notes.txt\").")
FOLDER_WORDS = ("desktop", "downloads", "documents")


def _folder_word(low: str) -> str | None:
    """Return the folder name mentioned in a request, e.g. 'Downloads' from 'organize my downloads'."""
    word = next((w for w in FOLDER_WORDS if w in low), None)
    return word.capitalize() if word else None


class Runner:
    def __init__(self, skills: Skills, api_key: str | None = None, model: str = "claude-sonnet-5-5",
                 max_rounds: int = 8):
        self.skills = skills
        self.model = model
        self.max_rounds = max_rounds
        self.client = None
        if api_key:
            import anthropic  # imported lazily so offline use needs no SDK
            self.client = anthropic.Anthropic(api_key=api_key)

    @property
    def mode(self) -> str:
        return "Claude" if self.client else "offline assistant"

    def run(self, spec: AgentSpec, task: str, allow_writes: bool = True, now: datetime | None = None) -> str:
        if self.client:
            return self._run_with_claude(spec, task, allow_writes)
        return route_offline(task, self.skills, allow_writes, now or datetime.now(), spec.skills)

    # ----- Claude tool-use loop -----
    def _run_with_claude(self, spec: AgentSpec, task: str, allow_writes: bool) -> str:
        tools = [TOOL_SCHEMAS[s] for s in spec.skills]
        system = (
            f"{spec.instructions}\n\n"
            "You work on a desktop computer for a non-technical user. Use your tools; do not invent file names. "
            "Never claim you deleted or changed something unless a tool reported it. "
            "Keep answers short and plain."
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        final = ""
        for _ in range(self.max_rounds):
            resp = self.client.messages.create(model=self.model, max_tokens=1024, system=system,
                                               messages=messages, tools=tools)
            texts = [b.text for b in resp.content if b.type == "text"]
            if texts:
                final = "\n".join(texts)
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                return final
            messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
            results = []
            for call in calls:
                output = self.skills.call(call.name, dict(call.input), allow_writes=allow_writes) \
                    if call.name in spec.skills else f"Error: skill '{call.name}' is not enabled for this agent."
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": output[:4000]})
            messages.append({"role": "user", "content": results})
        return final + "\n(Stopped: reached the step limit.)"


def route_offline(task: str, skills: Skills, allow_writes: bool, now: datetime, enabled: list[str]) -> str:
    """Rule-based assistant used when no API key is set. Keeps the same safety rules."""
    text = task.strip()
    low = text.lower()

    def can(skill: str) -> bool:
        return skill in enabled

    m = re.search(r"remind me (?:to )?(.+?) at (\d{1,2}:\d{2})", low)
    if m and can("add_reminder"):
        original = text[m.start(1):m.end(1)]
        try:
            return skills.add_reminder(original, m.group(2), now)
        except ValueError as err:
            return f"Error: {err}"
    if "reminder" in low and can("list_reminders"):
        return skills.list_reminders()
    if ("summary" in low or "briefing" in low) and can("daily_summary"):
        return skills.daily_summary(now)
    if "organi" in low and can("organize_folder"):
        folder = skills.folder_by_name(_folder_word(low) or "Downloads")
        apply = allow_writes and bool(re.search(r"\b(apply|now|move)\b", low))
        return skills.call("organize_folder", {"folder": folder, "apply": apply}, allow_writes)
    if low.startswith("find ") and can("find_files"):
        needle = re.sub(r"^find (files? )?(named |called )?", "", low).strip()
        folder = skills.folder_by_name(_folder_word(low) or "")
        return skills.call("find_files", {"name_contains": needle, "folder": folder}, allow_writes)
    if low.startswith("list ") and can("list_files"):
        folder = skills.folder_by_name(_folder_word(low) or "")
        return skills.call("list_files", {"folder": folder}, allow_writes)
    if low.startswith("open ") and can("open_item"):
        return skills.call("open_item", {"target": text[5:].strip()}, allow_writes)
    return HELP
