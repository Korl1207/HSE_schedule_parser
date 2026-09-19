"""Fetches the upcoming weeks of schedule from lk.hse.ru, parses them, and
stores the result in SQLite. This is the module the cron job / scheduler
calls; Google Calendar sync (reading db.pending_calendar_changes) is a
separate step to be added on top of this.
"""
from __future__ import annotations

import logging
from datetime import date

from .auth import HseAuth
from .config import Settings
from .db import SyncResult, connect, upsert_week
from .models import parse_week
from .schedule_api import get_week_raw, mondays_from

logger = logging.getLogger(__name__)


def sync(settings: Settings) -> list[SyncResult]:
    auth = HseAuth(settings.hse_username, settings.hse_password, settings.state_dir)
    conn = connect(settings.db_path)

    results = []
    for monday in mondays_from(date.today(), settings.weeks_ahead):
        sunday = monday.fromordinal(monday.toordinal() + 6)
        raw = get_week_raw(auth, monday)
        lessons = parse_week(raw)
        result = upsert_week(conn, lessons, monday, sunday)
        results.append(result)
        logger.info(
            "%s..%s: +%d added, ~%d updated, -%d removed, %d unchanged",
            monday, sunday, len(result.added), len(result.updated),
            len(result.removed), result.unchanged,
        )

    conn.close()
    return results
