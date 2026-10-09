"""Settings, read from environment variables or a .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .platform_utils import default_data_dir, default_folders


@dataclass
class Settings:
    data_dir: Path
    folders: list[Path]          # the ONLY places agents may read or change
    api_key: str | None = None   # optional: enables Claude-powered agents
    model: str = "claude-sonnet-5-5"
    max_rounds: int = 8

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        data_dir = Path(os.getenv("AD_DATA", default_data_dir())).expanduser()
        raw = os.getenv("AD_FOLDERS", "")
        folders = [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()] or default_folders()
        return cls(
            data_dir=data_dir,
            folders=folders,
            api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            model=os.getenv("AD_MODEL", cls.model),
            max_rounds=int(os.getenv("AD_MAX_ROUNDS", cls.max_rounds)),
        )
