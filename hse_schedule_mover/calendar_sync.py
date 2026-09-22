"""Pushes pending DB changes (see db.pending_calendar_changes) into a
dedicated secondary Google Calendar, so the bot never touches anything
outside events it created itself.

Design choices (see conversation / README for the full reasoning):
  - a separate calendar, not the primary one, is the isolation boundary
  - real timed Events (not Tasks) — classes have a fixed start/end
  - location: just the auditorium for offline, "Онлайн" for remote
  - description: lecturer / group / type, plus the meeting link if remote
  - colorId: one color for offline, another for online lessons
  - reminders: the earliest lesson of each day gets a popup reminder
    90 min ahead if offline, 30 min if online. For online lessons that
    aren't the first of the day there's no reminder, so the bot doesn't
    spam a popup per class. For offline lessons that aren't the first of
    the day, there's still a popup, just 5 min ahead — enough to walk to
    a different room without an interruption anywhere close to class start.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Settings
from .db import clear_google_event, connect, mark_synced, pending_calendar_changes, recompute_day_first
from .google_auth import get_credentials

logger = logging.getLogger(__name__)

CALENDAR_TIMEZONE = "Europe/Moscow"

EVENT_COLOR_OFFLINE = "7"  # Peacock (blue)
EVENT_COLOR_ONLINE = "10"  # Basil (green)

REMINDER_MINUTES_OFFLINE_FIRST = 90
REMINDER_MINUTES_OFFLINE_LATER = 5
REMINDER_MINUTES_ONLINE = 30

_LINK_LABELS = {
    "zoom.us": "Zoom",
    "ktalk.ru": "Kontur Talk",
    "meet.google.com": "Google Meet",
    "teams.microsoft.com": "MS Teams",
}


@dataclass
class CalendarSyncResult:
    created: int
    updated: int
    deleted: int


def _is_online(row: sqlite3.Row) -> bool:
    return row["building"] == "ONLINE"


def _guess_link_label(url: str) -> str:
    for domain, label in _LINK_LABELS.items():
        if domain in url:
            return label
    return "Ссылка на встречу"


def _build_location(row: sqlite3.Row) -> str:
    if _is_online(row):
        return "Онлайн"
    return row["auditorium"] or ""


def _build_description(row: sqlite3.Row) -> str:
    lines = []
    if row["lesson_type"]:
        lines.append(f"Тип занятия: {row['lesson_type']}")
    if row["lecturer"]:
        lines.append(f"Преподаватель: {row['lecturer']}")
    if row["parent_schedule"]:
        lines.append(f"Группа: {row['parent_schedule']}")
    if _is_online(row):
        for url, desc in (
            (row["url1"], row["url1_description"]),
            (row["url2"], row["url2_description"]),
        ):
            if url:
                label = desc or _guess_link_label(url)
                lines.append(f"{label}: {url}")
    return "\n".join(lines)


def _build_reminders(row: sqlite3.Row) -> dict:
    if _is_online(row):
        if not row["is_day_first"]:
            return {"useDefault": False, "overrides": []}
        minutes = REMINDER_MINUTES_ONLINE
    else:
        minutes = REMINDER_MINUTES_OFFLINE_FIRST if row["is_day_first"] else REMINDER_MINUTES_OFFLINE_LATER
    return {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes}]}


def lesson_row_to_event_body(row: sqlite3.Row) -> dict:
    return {
        "summary": row["name"],
        "location": _build_location(row),
        "description": _build_description(row),
        "start": {"dateTime": f"{row['date']}T{row['begin_time']}:00", "timeZone": CALENDAR_TIMEZONE},
        "end": {"dateTime": f"{row['date']}T{row['end_time']}:00", "timeZone": CALENDAR_TIMEZONE},
        "colorId": EVENT_COLOR_ONLINE if _is_online(row) else EVENT_COLOR_OFFLINE,
        "reminders": _build_reminders(row),
    }


def _ensure_calendar(service, calendar_id_path: Path, calendar_name: str) -> str:
    """Returns the id of the dedicated secondary calendar, creating it on
    the very first run and remembering its id afterwards."""
    if calendar_id_path.exists():
        return calendar_id_path.read_text(encoding="utf-8").strip()

    logger.info("Creating dedicated secondary calendar %r", calendar_name)
    calendar = (
        service.calendars()
        .insert(body={"summary": calendar_name, "timeZone": CALENDAR_TIMEZONE})
        .execute()
    )
    calendar_id = calendar["id"]

    calendar_id_path.parent.mkdir(parents=True, exist_ok=True)
    calendar_id_path.write_text(calendar_id, encoding="utf-8")
    return calendar_id


def sync_calendar(settings: Settings) -> CalendarSyncResult:
    creds = get_credentials(settings.google_client_secret, settings.google_token_path)
    service = build("calendar", "v3", credentials=creds)
    calendar_id = _ensure_calendar(service, settings.google_calendar_id_path, settings.google_calendar_name)

    conn = connect(settings.db_path)
    recompute_day_first(conn)

    created = updated = deleted = 0

    for row in pending_calendar_changes(conn).fetchall():
        if row["is_deleted"]:
            try:
                service.events().delete(calendarId=calendar_id, eventId=row["google_event_id"]).execute()
            except HttpError as exc:
                if exc.resp.status not in (404, 410):
                    raise
            clear_google_event(conn, row["slot_id"])
            deleted += 1
            continue

        body = lesson_row_to_event_body(row)

        if row["google_event_id"]:
            try:
                event = (
                    service.events()
                    .update(calendarId=calendar_id, eventId=row["google_event_id"], body=body)
                    .execute()
                )
                updated += 1
            except HttpError as exc:
                if exc.resp.status != 404:
                    raise
                # The event was deleted on the Google side (e.g. by hand) —
                # recreate it instead of failing the whole sync.
                event = service.events().insert(calendarId=calendar_id, body=body).execute()
                created += 1
        else:
            event = service.events().insert(calendarId=calendar_id, body=body).execute()
            created += 1

        mark_synced(conn, row["slot_id"], event["id"], row["content_hash"], bool(row["is_day_first"]))

    conn.close()
    logger.info("Calendar sync: +%d created, ~%d updated, -%d deleted", created, updated, deleted)
    return CalendarSyncResult(created=created, updated=updated, deleted=deleted)
