"""Loads settings from .env / environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root = one level up from this package, e.g. .../HSE_schedule_mover/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env by absolute path rather than relying on the current working
# directory, so this also works when triggered by cron/systemd with an
# unrelated cwd.
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    hse_username: str
    hse_password: str
    db_path: Path
    state_dir: Path
    weeks_ahead: int


def load_settings() -> Settings:
    username = os.environ.get("HSE_USERNAME", "").strip()
    password = os.environ.get("HSE_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError(
            "HSE_USERNAME / HSE_PASSWORD are not set — copy .env.example to .env and fill them in"
        )

    return Settings(
        hse_username=username,
        hse_password=password,
        db_path=Path(os.environ.get("DB_PATH", PROJECT_ROOT / "data" / "schedule.db")),
        state_dir=Path(os.environ.get("STATE_DIR", PROJECT_ROOT / "data" / "state")),
        weeks_ahead=int(os.environ.get("WEEKS_AHEAD", "4")),
    )
