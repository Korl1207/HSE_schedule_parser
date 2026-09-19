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
    google_client_secret: Path
    google_token_path: Path
    google_calendar_id_path: Path
    google_calendar_name: str


def load_settings() -> Settings:
    username = os.environ.get("HSE_USERNAME", "").strip()
    password = os.environ.get("HSE_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError(
            "HSE_USERNAME / HSE_PASSWORD are not set — copy .env.example to .env and fill them in"
        )

    state_dir = Path(os.environ.get("STATE_DIR", PROJECT_ROOT / "data" / "state"))

    return Settings(
        hse_username=username,
        hse_password=password,
        db_path=Path(os.environ.get("DB_PATH", PROJECT_ROOT / "data" / "schedule.db")),
        state_dir=state_dir,
        weeks_ahead=int(os.environ.get("WEEKS_AHEAD", "4")),
        google_client_secret=Path(
            os.environ.get("GOOGLE_CLIENT_SECRET", state_dir / "client_secret.json")
        ),
        google_token_path=Path(
            os.environ.get("GOOGLE_TOKEN_PATH", state_dir / "google_token.json")
        ),
        google_calendar_id_path=Path(
            os.environ.get("GOOGLE_CALENDAR_ID_PATH", state_dir / "google_calendar_id.txt")
        ),
        google_calendar_name=os.environ.get("GOOGLE_CALENDAR_NAME", "HSE Пары"),
    )
