"""Command-line interface:  python -m desktop_agent <command>"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .agents import TEMPLATES, AgentStore, from_template
from .config import Settings
from .platform_utils import os_name
from .runner import Runner
from .scheduler import serve
from .skills import ALL_SKILLS, Skills


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="desktop-agent", description="AI helpers for your day-to-day desktop work.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Show your setup: system, allowed folders, AI mode")
    sub.add_parser("templates", help="List agent templates and skills")

    c = sub.add_parser("create", help="Create an agent from a template")
    c.add_argument("name")
    c.add_argument("--template", default="custom", choices=list(TEMPLATES))
    c.add_argument("--instructions", help="Your own instructions (overrides the template)")
    c.add_argument("--skills", help="Comma-separated skills (overrides the template)")
    c.add_argument("--schedule", help="Daily time, e.g. 18:00, or 'none'")
    c.add_argument("--auto-apply", action="store_true", help="Let scheduled runs move files (use with care)")
    c.add_argument("--description")

    sub.add_parser("agents", help="List your agents")

    s = sub.add_parser("show", help="Show one agent")
    s.add_argument("name")

    u = sub.add_parser("update", help="Change an agent")
    u.add_argument("name")
    u.add_argument("--instructions")
    u.add_argument("--skills")
    u.add_argument("--schedule", help="Daily time, e.g. 18:00, or 'none'")
    u.add_argument("--auto-apply", choices=["yes", "no"])
    u.add_argument("--enabled", choices=["yes", "no"])

    d = sub.add_parser("delete", help="Delete an agent")
    d.add_argument("name")
    d.add_argument("-y", "--yes", action="store_true")

    r = sub.add_parser("run", help="Give an agent a task now")
    r.add_argument("name")
    r.add_argument("task")

    rem = sub.add_parser("remind", help="Set a reminder")
    rem.add_argument("text")
    rem.add_argument("--at", required=True, help="HH:MM or 'YYYY-MM-DD HH:MM'")

    sub.add_parser("reminders", help="List upcoming reminders")
    sub.add_parser("summary", help="Print today's summary")
    sub.add_parser("serve", help="Keep running: scheduled agents and reminders")
    return p


def _skills_list(text: str | None) -> list[str] | None:
    return [s.strip() for s in text.split(",") if s.strip()] if text else None


def _yes_no(text: str | None) -> bool | None:
    return None if text is None else text == "yes"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    store = AgentStore(settings.data_dir / "agents.json")
    skills = Skills(settings.folders, settings.data_dir)
    runner = Runner(skills, settings.api_key, settings.model, settings.max_rounds)
    try:
        return dispatch(args, settings, store, skills, runner)
    except (ValueError, KeyError, OSError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def dispatch(args, settings: Settings, store: AgentStore, skills: Skills, runner: Runner) -> int:
    if args.cmd == "doctor":
        print(f"System:        {os_name()}")
        print(f"Data folder:   {settings.data_dir}")
        print("Allowed folders:")
        for f in settings.folders:
            print(f"  {'✔' if f.exists() else '✘ (missing)'} {f}")
        print(f"AI mode:       {runner.mode}" + ("" if settings.api_key else "  (set ANTHROPIC_API_KEY for Claude)"))

    elif args.cmd == "templates":
        for name, t in TEMPLATES.items():
            print(f"  {name:<16} {t['description']}")
        print("\nSkills:", ", ".join(ALL_SKILLS))

    elif args.cmd == "create":
        spec = from_template(
            args.template, args.name,
            instructions=args.instructions, skills=_skills_list(args.skills),
            schedule=args.schedule, auto_apply=args.auto_apply, description=args.description,
        )
        store.add(spec)
        print(f"✔ Created '{spec.name}' ({args.template}). Skills: {', '.join(spec.skills)}")
        if spec.schedule:
            print(f"  Runs daily at {spec.schedule}.")

    elif args.cmd == "agents":
        agents = store.all()
        if not agents:
            print("No agents yet. Try: desktop-agent create organizer --template file-organizer")
        for a in agents:
            state = "on " if a.enabled else "off"
            when = a.schedule or "manual"
            print(f"  [{state}] {a.name:<18} {when:<8} {a.description}")

    elif args.cmd == "show":
        for key, value in store.get(args.name).to_dict().items():
            print(f"{key}: {value}")

    elif args.cmd == "update":
        store.update(args.name, instructions=args.instructions, skills=_skills_list(args.skills),
                     schedule=args.schedule, auto_apply=_yes_no(args.auto_apply), enabled=_yes_no(args.enabled))
        print(f"✔ Updated '{args.name}'.")

    elif args.cmd == "delete":
        if not args.yes and input(f"Delete agent '{args.name}'? [y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return 0
        store.remove(args.name)
        print(f"✔ Deleted '{args.name}'.")

    elif args.cmd == "run":
        spec = store.get(args.name)
        print(runner.run(spec, args.task, allow_writes=True))

    elif args.cmd == "remind":
        print(skills.add_reminder(args.text, args.at))

    elif args.cmd == "reminders":
        print(skills.list_reminders())

    elif args.cmd == "summary":
        print(skills.daily_summary())

    elif args.cmd == "serve":
        serve(store, runner, skills)

    return 0


if __name__ == "__main__":
    sys.exit(main())
