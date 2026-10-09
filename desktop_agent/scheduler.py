"""Background loop: runs scheduled agents and fires reminders at the right time."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from .agents import AgentStore, due_agents
from .runner import Runner
from .skills import Skills


def tick(store: AgentStore, runner: Runner, skills: Skills, now: datetime) -> list[str]:
    """Do everything that is due at `now`. Returns short log lines (useful for tests and logs)."""
    log: list[str] = []
    store.load()  # pick up changes made by the CLI while we were sleeping

    for reminder in skills.reminders.due(now):
        skills.notify(reminder.text, title="Reminder")
        log.append(f"reminder fired: {reminder.text}")

    for spec in due_agents(store.all(), now):
        job = spec.task or spec.description
        task = f"Scheduled run at {now:%H:%M}. {job}"
        output = runner.run(spec, task, allow_writes=spec.auto_apply, now=now)
        store.update(spec.name, last_run_date=now.strftime("%Y-%m-%d"))
        first_line = (output.strip().splitlines() or ["Done."])[0]
        skills.notify(first_line[:200], title=spec.name)
        log.append(f"ran {spec.name}")
    return log


def serve(store: AgentStore, runner: Runner, skills: Skills, poll_seconds: int = 30,
          clock: Callable[[], datetime] = datetime.now, sleep: Callable[[float], None] = time.sleep,
          max_ticks: int | None = None) -> None:
    """Run forever (or for `max_ticks` checks in tests), checking the clock every `poll_seconds`."""
    print(f"Desktop Agent is running ({runner.mode}). Press Ctrl+C to stop.")
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        for line in tick(store, runner, skills, clock()):
            print(f"{clock():%H:%M} {line}")
        ticks += 1
        sleep(poll_seconds)
