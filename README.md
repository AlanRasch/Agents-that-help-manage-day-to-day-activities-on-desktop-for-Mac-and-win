# Desktop Agent

**Create and manage small AI helpers that take care of everyday desktop tasks on macOS and Windows.**

Examples of what your agents can do:

- Tidy Downloads every evening: sort loose files into *Images*, *Documents*, *Installers*, and so on. It shows you the plan first and never deletes anything.
- Morning briefing at 08:30: today's date, free disk space, and your reminders.
- Reminders in plain language: `remind me to call Sokha at 15:30`.
- Find and open files in your Desktop, Downloads, or Documents folders.
- Custom agents that you describe in your own words. With a Claude API key, they plan and use their skills on their own.

You do not need to write code to use it. The app is driven by a few short commands, and it works (without an API key) using a built-in assistant. Add a key later to unlock Claude-powered agents.

---

Contents

1. [Safety first](#safety-first)
2. [Installation: macOS](#installation-macos)
3. [Installation: Windows](#installation-windows)
4. [Quick start](#quick-start)
5. [Creating and managing agents](#creating-and-managing-agents)
6. [Reminders and the daily summary](#reminders-and-the-daily-summary)
7. [Running automatically](#running-automatically)
8. [Skills (what agents can do)](#skills-what-agents-can-do)
9. [Configuration](#configuration)
10. [Project structure](#project-structure)
11. [Running the tests](#running-the-tests)
12. [Troubleshooting](#troubleshooting)
13. [Privacy](#privacy)
14. [Extending the app](#extending-the-app)

---

## Safety first

Agents act on your real files, so the app is built to be careful:

| Rule | What it means |
|---|---|
| **Only your chosen folders** | Agents can use Desktop, Downloads and Documents by default. Anything else is refused, including `..` tricks and symbolic links that point outside. |
| **Nothing is deleted** | There is no delete skill at all. |
| **Nothing is overwritten** | If a name is taken, the new file becomes `photo (2).jpg`. |
| **Preview before moving** | Organising is a dry run unless you explicitly apply it. |
| **Background runs are read-only by default** | A scheduled agent may only *report* unless you turn on `--auto-apply` for it. |
| **Limited skills per agent** | Each agent can only use the skills you give it. |

It does **not** control your mouse or keyboard, and it does not read your screen. It works through files, notifications, and opening items.

---

## Installation: macOS

You need **macOS 12 or newer** and **Python 3.10+**. To check, open *Terminal* and run `python3 --version`. If it is missing, install Python from [python.org](https://www.python.org/downloads/macos/).

```bash
# 1. Go to the project folder
cd ~/Downloads/desktop-agent          # or wherever you unzipped it

# 2. Create a private Python environment and install the requirements
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Optional: add your Claude API key
cp .env.example .env                  # then open .env in TextEdit and fill in the key

# 4. Check everything
python -m desktop_agent doctor
```

**macOS permissions:** the first time an agent reads or moves files in Desktop, Downloads or Documents, macOS asks whether Terminal may access them. Choose **Allow**. Notifications appear only if you allow notifications for *Script Editor* in *System Settings → Notifications*.

---

## Installation: Windows

You need **Windows 10 or 11** and **Python 3.10+**. Download Python from [python.org](https://www.python.org/downloads/windows/) and tick **"Add python.exe to PATH"** during setup.

Open **PowerShell** in the project folder (*Shift + right-click → Open in Terminal*) and run:

```powershell
# 1. Create a private Python environment and install the requirements
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Optional: add your Claude API key
copy .env.example .env                # then open .env in Notepad and fill in the key

# 3. Check everything
python -m desktop_agent doctor
```

If PowerShell says scripts are disabled, run this once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Windows notifications:** make sure *Settings → System → Notifications* is turned on.

---

## Quick start

Run these in the same terminal (with the environment activated):

```bash
# Create two agents from templates
python -m desktop_agent create organizer --template file-organizer
python -m desktop_agent create briefing  --template daily-briefing --schedule 08:30

# See what they are
python -m desktop_agent agents

# Preview how Downloads would be organised (nothing moves)
python -m desktop_agent run organizer "organize downloads"

# Actually move the files, now that you have seen the plan
python -m desktop_agent run organizer "organize downloads now"

# Set a reminder and check today's summary
python -m desktop_agent remind "Submit the grade sheet" --at 15:30
python -m desktop_agent summary
```

On Windows, use the same commands in PowerShell.

---

## Creating and managing agents

### Templates

| Template | What it is for | Default skills | Default schedule |
|---|---|---|---|
| `file-organizer` | Keep Downloads tidy | list files, organise, notify | 18:00 (preview only) |
| `daily-briefing` | Morning summary | daily summary, notify | 08:30 |
| `reminder-helper` | Reminders in plain language | add/list reminders, notify | none |
| `file-finder` | Find, read and open files | list, find, read, open | none |
| `custom` | Your own agent | list files, notify | none |

See them all with `python -m desktop_agent templates`.

### Commands

| Command | What it does |
|---|---|
| `create NAME --template T` | Create an agent from a template |
| `create NAME --instructions "..." --skills a,b` | Create a custom agent with your own instructions |
| `agents` | List your agents, with their schedule and state |
| `show NAME` | Show all details of one agent |
| `update NAME --schedule 19:00` | Change a setting (`--schedule none` removes it) |
| `update NAME --enabled no` | Pause an agent without deleting it (`--enabled yes` resumes it) |
| `update NAME --auto-apply yes` | Let scheduled runs move files (use with care) |
| `run NAME "task"` | Give an agent a task right now |
| `delete NAME` | Delete an agent (asks you to confirm) |

### Examples

```bash
# A custom agent that finds PDFs about invoices
python -m desktop_agent create invoices --instructions "Help me find invoice PDFs quickly." \
       --skills find_files,open_item,list_files

# An agent that uses Claude (needs ANTHROPIC_API_KEY) to write a short note in Documents
python -m desktop_agent create note-writer --instructions "Write short, clear meeting notes as new text files." \
       --skills write_text,notify
python -m desktop_agent run note-writer "Create Documents/meeting-notes-2026-10-09.txt with three action items for a project review"
```

> **Tip:** `write_text` can only create *new* files, never change existing ones.

---

## Reminders and the daily summary

```bash
python -m desktop_agent remind "Pay water bill" --at 17:00          # today at 17:00, or tomorrow if it has passed
python -m desktop_agent remind "Renew passport" --at "2026-12-01 09:00"
python -m desktop_agent reminders                                    # what is still to come
python -m desktop_agent summary                                      # today at a glance
```

Reminders pop up as desktop notifications **only while `serve` is running** (see below).

---

## Running automatically

Scheduled agents and reminders need the background service, `serve`. It checks the clock every 30 seconds.

**Try it now** (stop with `Ctrl+C`):

```bash
python -m desktop_agent serve
```

**Start automatically when you log in:**

- **macOS:** open `scripts/macos_launchagent.plist`, replace the two `/PATH/TO/desktop-agent` placeholders and the Python path (run `which python3` inside the activated environment), then copy it to `~/Library/LaunchAgents/com.desktopagent.plist` and run:
  ```bash
  launchctl load ~/Library/LaunchAgents/com.desktopagent.plist
  ```
  To stop it: `launchctl unload ~/Library/LaunchAgents/com.desktopagent.plist`

- **Windows:** in PowerShell, from the project folder, run:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1
  ```
  To remove it: `Unregister-ScheduledTask -TaskName "DesktopAgent" -Confirm:$false`

**Good to know:** a scheduled run happens only if the computer is awake and the service is running at that minute. If the computer was asleep at 08:30, the briefing for that day is skipped.

---

## Skills (what agents can do)

| Skill | Description | Changes things? |
|---|---|---|
| `list_files` | List an allowed folder | No |
| `find_files` | Find files by part of their name | No |
| `read_text` | Read the start of a text file | No |
| `organize_folder` | Sort loose files into category folders (dry run unless applied) | Yes, only when applied |
| `write_text` | Create a new text file | Yes (new files only) |
| `open_item` | Open a file, folder or web link | Opens an app |
| `add_reminder` / `list_reminders` | Manage reminders | No (reminder list only) |
| `daily_summary` | Date, free disk space, Downloads count, reminders | No |
| `notify` | Show a desktop notification | No |

File categories used by `organize_folder`: Images, Documents, Spreadsheets, Presentations, Archives, Audio, Video, Installers, Code, Other.

---

## Configuration

Settings go in `.env` (copy `.env.example`). Everything is optional.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Enables Claude-powered agents. Without it, the offline assistant is used. |
| `AD_MODEL` | `claude-sonnet-5-5` | Model used for Claude-powered agents |
| `AD_FOLDERS` | Desktop, Downloads, Documents | Folders agents may use, comma-separated |
| `AD_DATA` | per-system (see below) | Where agents and reminders are saved |
| `AD_MAX_ROUNDS` | `8` | Maximum steps a Claude agent may take per task |

Default data folders:

- **macOS:** `~/Library/Application Support/DesktopAgent/`
- **Windows:** `%APPDATA%\DesktopAgent\`
- **Linux:** `~/.local/share/desktop-agent/`

---

## Project structure

```
desktop-agent/
├── desktop_agent/
│   ├── __init__.py           # version
│   ├── __main__.py           # allows: python -m desktop_agent
│   ├── agents.py             # agent templates, validation, saving, schedules
│   ├── cli.py                # all commands
│   ├── config.py             # settings from .env and defaults
│   ├── platform_utils.py     # macOS / Windows / Linux differences in one place
│   ├── runner.py             # runs tasks: Claude tool use, or the offline assistant
│   ├── scheduler.py          # the background loop (serve)
│   └── skills.py             # the safe desktop actions + reminders
├── scripts/
│   ├── macos_launchagent.plist        # start at login on macOS
│   └── install_windows_startup.ps1    # start at sign-in on Windows
├── tests/
│   └── test_desktop_agent.py          # 23 offline tests
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Running the tests

```bash
python -m pytest -q
```

The tests use temporary folders only. They do not send notifications, open apps, or call the API.

---

## Troubleshooting

| Problem | What to try |
|---|---|
| `python` not found on Windows | Reinstall Python and tick *Add python.exe to PATH*, or use `py` instead of `python` |
| `ModuleNotFoundError` | Activate the environment first (`source .venv/bin/activate` or `.\.venv\Scripts\Activate.ps1`), then run `pip install -r requirements.txt` |
| `is outside your allowed folders` | Add the folder with `AD_FOLDERS` in `.env` |
| Scheduled agent did not run | Make sure `serve` is running at that time, and that the computer was awake |
| No notification appears | Turn on notifications for your terminal or Script Editor (macOS) or the system (Windows). The app prints the message to the terminal as a fallback. |
| Agent says "Error: skill ... is not enabled" | Add the skill with `update NAME --skills ...` |
| Claude mode not active | Check `ANTHROPIC_API_KEY` in `.env` and run `doctor` |
| macOS asks for folder access repeatedly | Choose *Allow* when prompted; it is needed once per folder |

---

## Privacy

- Everything stays on your computer, except when **Claude mode** is on. Then the task text and the file contents an agent reads (such as the first part of a text file) are sent to the Anthropic API to be processed. Do not use Claude mode on files you would not share with that service.
- The offline assistant never sends anything over the internet.
- Agents, reminders, and history are saved only in the data folder listed above.
- Your API key stays in `.env`, which is excluded from git by `.gitignore`.

---

## Extending the app

**Add a skill:** in `desktop_agent/skills.py`, write a method on the `Skills` class, add its description to `TOOL_SCHEMAS`, and add its name to `WRITE_SKILLS` if it changes anything. It is then available to every agent that lists it.

**Add a template:** add an entry to `TEMPLATES` in `desktop_agent/agents.py` with a description, instructions, skills, and optional schedule.

**Ideas for later:** a small tray icon for Mac and Windows, a folder watcher that organises files as they arrive, Outlook or Apple Calendar integration, and a weekly cleanup report.

---

**Author:** Dr. Firend Alan Rasch · American University of Phnom Penh
**License:** MIT (or your preferred license)
