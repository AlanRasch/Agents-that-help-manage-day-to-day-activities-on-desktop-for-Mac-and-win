"""Offline tests: no API key, no real notifications, nothing outside tmp folders."""

from datetime import datetime
from pathlib import Path

import pytest

from desktop_agent.agents import AgentStore, due_agents, from_template
from desktop_agent.platform_utils import notify_command, open_command, os_name
from desktop_agent.runner import Runner, route_offline
from desktop_agent.scheduler import tick
from desktop_agent.skills import SafetyError, Skills, category_for, parse_when


@pytest.fixture
def env(tmp_path):
    downloads = tmp_path / "Downloads"
    documents = tmp_path / "Documents"
    downloads.mkdir()
    documents.mkdir()
    data = tmp_path / "data"
    skills = Skills([downloads, documents], data, system="linux")
    store = AgentStore(data / "agents.json")
    runner = Runner(skills, api_key=None)
    return {"tmp": tmp_path, "downloads": downloads, "documents": documents, "data": data,
            "skills": skills, "store": store, "runner": runner}


NOON = datetime(2026, 10, 9, 12, 0)


# ---------- organising files ----------
def test_organize_is_dry_run_by_default(env):
    (env["downloads"] / "photo.jpg").write_text("x")
    out = env["skills"].organize_folder(str(env["downloads"]))
    assert "DRY RUN" in out
    assert (env["downloads"] / "photo.jpg").exists()  # nothing moved


def test_organize_apply_moves_into_categories(env):
    (env["downloads"] / "photo.jpg").write_text("x")
    (env["downloads"] / "report.pdf").write_text("x")
    (env["downloads"] / "mystery.xyz").write_text("x")
    env["skills"].organize_folder(str(env["downloads"]), apply=True)
    assert (env["downloads"] / "Images" / "photo.jpg").exists()
    assert (env["downloads"] / "Documents" / "report.pdf").exists()
    assert (env["downloads"] / "Other" / "mystery.xyz").exists()


def test_organize_never_overwrites(env):
    (env["downloads"] / "Images").mkdir()
    (env["downloads"] / "Images" / "photo.jpg").write_text("old")
    (env["downloads"] / "photo.jpg").write_text("new")
    env["skills"].organize_folder(str(env["downloads"]), apply=True)
    assert (env["downloads"] / "Images" / "photo.jpg").read_text() == "old"
    assert (env["downloads"] / "Images" / "photo (2).jpg").read_text() == "new"


def test_scheduled_run_cannot_move_files(env):
    (env["downloads"] / "photo.jpg").write_text("x")
    out = env["skills"].call("organize_folder", {"folder": str(env["downloads"]), "apply": True},
                             allow_writes=False)
    assert "DRY RUN" in out
    assert (env["downloads"] / "photo.jpg").exists()


def test_category_lookup_is_case_insensitive():
    assert category_for(Path("HOLIDAY.JPG")) == "Images"
    assert category_for(Path("notes")) == "Other"


# ---------- safety ----------
def test_paths_outside_allowed_folders_are_blocked(env):
    outside = env["tmp"] / "secret.txt"
    outside.write_text("private")
    with pytest.raises(SafetyError):
        env["skills"].read_text(str(outside))
    assert "outside your allowed folders" in env["skills"].call("read_text", {"path": str(outside)})


def test_dot_dot_escape_is_blocked(env):
    with pytest.raises(SafetyError):
        env["skills"].check_path(str(env["downloads"] / ".." / "secret.txt"))


def test_relative_paths_resolve_inside_first_folder(env):
    (env["downloads"] / "note.txt").write_text("hello")
    assert env["skills"].read_text("note.txt") == "hello"


def test_write_text_never_overwrites(env):
    env["skills"].write_text(str(env["documents"] / "todo.txt"), "one")
    assert "already exists" in env["skills"].call("write_text",
                                                  {"path": str(env["documents"] / "todo.txt"), "content": "two"})
    assert (env["documents"] / "todo.txt").read_text() == "one"


def test_write_blocked_in_background_runs(env):
    out = env["skills"].call("write_text", {"path": "x.txt", "content": "y"}, allow_writes=False)
    assert "not allowed" in out
    assert not (env["downloads"] / "x.txt").exists()


# ---------- reminders & time parsing ----------
def test_parse_when_today_or_tomorrow():
    assert parse_when("15:30", NOON) == datetime(2026, 10, 9, 15, 30)
    assert parse_when("09:00", NOON) == datetime(2026, 10, 10, 9, 0)
    assert parse_when("2026-12-25 08:00", NOON) == datetime(2026, 12, 25, 8, 0)
    with pytest.raises(ValueError):
        parse_when("25:00", NOON)
    with pytest.raises(ValueError):
        parse_when("next tuesday", NOON)


def test_reminder_fires_once(env):
    env["skills"].add_reminder("call Sokha", "11:00", now=NOON)  # fires tomorrow at 11:00
    fired = env["skills"].reminders.due(datetime(2026, 10, 10, 11, 0))
    assert [r.text for r in fired] == ["call Sokha"]
    assert env["skills"].reminders.due(datetime(2026, 10, 10, 11, 5)) == []


# ---------- agents ----------
def test_template_agent_created_and_saved(env):
    spec = from_template("file-organizer", "organizer")
    env["store"].add(spec)
    reloaded = AgentStore(env["data"] / "agents.json")
    assert reloaded.get("organizer").schedule == "18:00"
    assert "organize_folder" in reloaded.get("organizer").skills


def test_unknown_skill_or_bad_name_rejected(env):
    with pytest.raises(ValueError):
        from_template("custom", "helper", skills=["format_disk"])
    with pytest.raises(ValueError):
        from_template("custom", "Bad Name!")


def test_schedule_none_clears_template_schedule(env):
    spec = from_template("file-organizer", "organizer", schedule="none")
    assert spec.schedule is None
    env["store"].add(from_template("file-organizer", "org2"))
    env["store"].update("org2", schedule="none")
    assert env["store"].get("org2").schedule is None


def test_due_agents_only_once_per_day(env):
    env["store"].add(from_template("daily-briefing", "briefing"))  # 08:30
    at_0830 = datetime(2026, 10, 9, 8, 30)
    assert [a.name for a in due_agents(env["store"].all(), at_0830)] == ["briefing"]
    env["store"].update("briefing", last_run_date="2026-10-09")
    assert due_agents(env["store"].all(), at_0830) == []
    assert due_agents(env["store"].all(), datetime(2026, 10, 9, 8, 31)) == []


def test_tick_runs_scheduled_agent_offline(env):
    env["store"].add(from_template("daily-briefing", "briefing"))
    (env["downloads"] / "a.pdf").write_text("x")
    log = tick(env["store"], env["runner"], env["skills"], datetime(2026, 10, 9, 8, 30))
    assert "ran briefing" in log
    assert env["store"].get("briefing").last_run_date == "2026-10-09"


# ---------- offline assistant ----------
def test_offline_reminder_request(env):
    out = route_offline("Remind me to call Sokha at 15:30", env["skills"], True, NOON,
                        ["add_reminder", "list_reminders"])
    assert "Reminder #1 set for 2026-10-09 15:30" in out
    assert "call Sokha" in env["skills"].list_reminders()


def test_offline_organize_and_summary(env):
    (env["downloads"] / "photo.jpg").write_text("x")
    skills = ["organize_folder", "daily_summary"]
    assert "DRY RUN" in route_offline("organize downloads", env["skills"], True, NOON, skills)
    assert "Free disk space" in route_offline("daily summary", env["skills"], True, NOON, skills)


def test_offline_unknown_request_shows_help(env):
    assert "I can:" in route_offline("make me a sandwich", env["skills"], True, NOON, ["list_files"])


# ---------- platform helpers (commands are built, not executed) ----------
def test_notification_commands_per_os():
    assert notify_command("macos", "Hi", 'say "yes"')[0] == "osascript"
    win = notify_command("windows", "Hi", "it's time")
    assert win[0] == "powershell" and "it''s time" in win[-1]
    cmd = notify_command("linux", "Hi", "x")  # None when notify-send is not installed
    assert cmd is None or cmd[0] == "notify-send"


def test_open_commands_per_os():
    assert open_command("macos", "/tmp/a.txt") == ["open", "/tmp/a.txt"]
    assert open_command("windows", "C:\\a.txt")[:3] == ["cmd", "/c", "start"]
    assert open_command("linux", "/tmp/a.txt") == ["xdg-open", "/tmp/a.txt"]


def test_os_detection():
    assert os_name("Darwin") == "macos"
    assert os_name("Windows") == "windows"
    assert os_name("Linux") == "linux"
