"""SQLite storage for the synced schedule, with change tracking so the
(future) Google Calendar sync only has to touch what actually changed."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .models import Lesson

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
    slot_id             TEXT PRIMARY KEY,
    date                TEXT NOT NULL,
    begin_time          TEXT NOT NULL,
    end_time            TEXT NOT NULL,
    name                TEXT NOT NULL,
    lesson_type         TEXT,
    lesson_type_id      INTEGER,
    building            TEXT,
    auditorium          TEXT,
    lecturer            TEXT,
    lesson_number       TEXT,
    parent_schedule     TEXT,
    url1                TEXT,
    url1_description    TEXT,
    url2                TEXT,
    url2_description    TEXT,
    content_hash        TEXT NOT NULL,
    google_event_id     TEXT,
    synced_content_hash TEXT,
    is_deleted          INTEGER NOT NULL DEFAULT 0,
    first_seen_at       TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lessons_date ON lessons(date);
"""


@dataclass
class SyncResult:
    added: list[str]
    updated: list[str]
    removed: list[str]
    unchanged: int


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def upsert_week(conn: sqlite3.Connection, lessons: list[Lesson], monday: date, sunday: date) -> SyncResult:
    """Stores `lessons` (all belonging to the [monday, sunday] range) and
    diffs them against what's already in the DB for that same range:
      - new slot_id                      -> added
      - existing slot_id, hash changed    -> updated
      - existing slot_id, hash unchanged  -> unchanged
      - DB row in range, absent from fetch -> marked is_deleted (removed)
    """
    now = datetime.utcnow().isoformat()

    existing = dict(
        conn.execute(
            "SELECT slot_id, content_hash FROM lessons "
            "WHERE date >= ? AND date <= ? AND is_deleted = 0",
            (monday.isoformat(), sunday.isoformat()),
        ).fetchall()
    )

    fetched_ids: set[str] = set()
    added: list[str] = []
    updated: list[str] = []
    unchanged = 0

    for lesson in lessons:
        slot_id = lesson.slot_id
        content_hash = lesson.content_hash
        fetched_ids.add(slot_id)

        if slot_id not in existing:
            added.append(slot_id)
            conn.execute(
                """
                INSERT INTO lessons (
                    slot_id, date, begin_time, end_time, name, lesson_type,
                    lesson_type_id, building, auditorium, lecturer,
                    lesson_number, parent_schedule, url1, url1_description,
                    url2, url2_description, content_hash, is_deleted,
                    first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    slot_id, lesson.date, lesson.begin_time, lesson.end_time,
                    lesson.name, lesson.lesson_type, lesson.lesson_type_id,
                    lesson.building, lesson.auditorium, lesson.lecturer,
                    lesson.lesson_number, lesson.parent_schedule, lesson.url1,
                    lesson.url1_description, lesson.url2, lesson.url2_description,
                    content_hash, now, now,
                ),
            )
        elif existing[slot_id] != content_hash:
            updated.append(slot_id)
            conn.execute(
                """
                UPDATE lessons SET
                    begin_time = ?, end_time = ?, name = ?, lesson_type = ?,
                    lesson_type_id = ?, building = ?, auditorium = ?,
                    lecturer = ?, lesson_number = ?, parent_schedule = ?,
                    url1 = ?, url1_description = ?, url2 = ?,
                    url2_description = ?, content_hash = ?, updated_at = ?
                WHERE slot_id = ?
                """,
                (
                    lesson.begin_time, lesson.end_time, lesson.name,
                    lesson.lesson_type, lesson.lesson_type_id, lesson.building,
                    lesson.auditorium, lesson.lecturer, lesson.lesson_number,
                    lesson.parent_schedule, lesson.url1, lesson.url1_description,
                    lesson.url2, lesson.url2_description, content_hash, now,
                    slot_id,
                ),
            )
        else:
            unchanged += 1

    removed = [slot_id for slot_id in existing if slot_id not in fetched_ids]
    if removed:
        conn.executemany(
            "UPDATE lessons SET is_deleted = 1, updated_at = ? WHERE slot_id = ?",
            [(now, slot_id) for slot_id in removed],
        )

    conn.commit()
    return SyncResult(added=added, updated=updated, removed=removed, unchanged=unchanged)


def mark_synced(conn: sqlite3.Connection, slot_id: str, google_event_id: str, content_hash: str) -> None:
    """Call after successfully creating/updating the Google Calendar event
    for this lesson, so it's not picked up again until it changes further."""
    conn.execute(
        "UPDATE lessons SET google_event_id = ?, synced_content_hash = ? WHERE slot_id = ?",
        (google_event_id, content_hash, slot_id),
    )
    conn.commit()


def pending_calendar_changes(conn: sqlite3.Connection) -> sqlite3.Cursor:
    """Rows that the (future) calendar sync step needs to act on: lessons
    that are new, changed since their last sync, or removed but still have
    a Google event to delete."""
    return conn.execute(
        "SELECT * FROM lessons WHERE "
        "(is_deleted = 0 AND (google_event_id IS NULL OR synced_content_hash != content_hash)) OR "
        "(is_deleted = 1 AND google_event_id IS NOT NULL)"
    )
