"""Parses the raw get-myschedule JSON into normalized Lesson records."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

# Суффиксы в скобках в конце названия, не несущие смысла для календаря:
# язык преподавания, уровень курса и т.п.
# Снимаются по одному с конца, поэтому "Алгебра (углубленный курс) (рус)"
# -> "Алгебра (углубленный курс)" -> "Алгебра".
_SUBJECT_SUFFIXES = {
    "рус",
    "русский",
    "на русском",
    "анг",
    "англ",
    "английский",
    "на английском",
    "english",
    "углубленный курс",
    "углублённый курс",
    "углубленный",
    "углублённый",
    "базовый курс",
    "базовый",
    "продвинутый курс",
    "продвинутый",
}

_SUBJECT_SUFFIX_RE = re.compile(r"\s*\(([^()]*)\)\s*$")

# Словарь для переименования предметов после чистки суффиксов.
# Ключ — имя после снятия суффиксов, значение — то, что показать в календаре.
# Пример: SUBJECT_RENAMES = {"МатАн": "Математический анализ"}
SUBJECT_RENAMES: dict[str, str] = {}


def _clean(value) -> str:
    """The API sometimes returns null instead of "" for empty text fields."""
    return value if value is not None else ""


def clean_subject_name(raw: str | None) -> str:
    """Убирает служебные суффиксы вида (рус)/(анг)/(углубленный курс)
    с конца названия и применяет SUBJECT_RENAMES."""
    name = _clean(raw).strip()
    while True:
        match = _SUBJECT_SUFFIX_RE.search(name)
        if not match:
            break
        if match.group(1).strip().lower() not in _SUBJECT_SUFFIXES:
            break
        name = name[: match.start()].strip()
    return SUBJECT_RENAMES.get(name, name)


@dataclass(frozen=True)
class Lesson:
    date: str  # "YYYY-MM-DD"
    begin_time: str  # "HH:MM"
    end_time: str
    name: str
    lesson_type: str
    lesson_type_id: int | None
    building: str
    auditorium: str
    lecturer: str
    lesson_number: str | None
    parent_schedule: str
    url1: str
    url1_description: str
    url2: str
    url2_description: str

    @property
    def slot_id(self) -> str:
        """Stable identity for "this occurrence of this lesson", independent
        of details like room/lecturer that can change between fetches."""
        raw = "|".join(
            [self.date, self.begin_time, self.name, self.lesson_type, self.parent_schedule]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def content_hash(self) -> str:
        """Hash of everything that can meaningfully change for a given
        slot_id — used to detect e.g. a room or lecturer change."""
        raw = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_week(raw_days: list[dict]) -> list[Lesson]:
    """raw_days is the JSON returned by get-myschedule: a list of
    {date, lessons: [...]} entries, one per day of the week."""
    lessons: list[Lesson] = []
    for day in raw_days:
        date = day["date"]
        for item in day.get("lessons", []):
            lessons.append(
                Lesson(
                    date=date,
                    begin_time=item["begin_time"],
                    end_time=item["end_time"],
                    name=clean_subject_name(item["name"]),
                    lesson_type=_clean(item.get("lesson_type")),
                    lesson_type_id=item.get("lesson_type_id"),
                    building=_clean(item.get("building")),
                    auditorium=_clean(item.get("auditorium")),
                    lecturer=_clean(item.get("lecturer")),
                    lesson_number=item.get("lesson_number"),
                    parent_schedule=_clean(item.get("parent_schedule")),
                    url1=_clean(item.get("url1")),
                    url1_description=_clean(item.get("url1_description")),
                    url2=_clean(item.get("url2")),
                    url2_description=_clean(item.get("url2_description")),
                )
            )
    return lessons
