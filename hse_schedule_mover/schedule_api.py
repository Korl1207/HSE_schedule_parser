"""Raw HTTP access to lk.hse.ru's get-myschedule endpoint."""
from __future__ import annotations

from datetime import date, timedelta

import requests

from .auth import HseAuth

SCHEDULE_URL = "https://lk.hse.ru/api/get-myschedule"


def get_week_raw(auth: HseAuth, monday: date) -> list[dict]:
    """Fetches one week of schedule starting from `monday`.

    The endpoint requires `begin_date` and returns 400 without it; per
    observed behavior it should be a Monday to reliably get the full week
    back.
    """
    if monday.weekday() != 0:
        raise ValueError(f"begin_date must be a Monday, got {monday.isoformat()}")

    token = auth.get_access_token()
    resp = auth.session.get(
        SCHEDULE_URL,
        params={"begin_date": monday.isoformat()},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def mondays_from(start: date, count: int) -> list[date]:
    """`count` consecutive Mondays, starting from the Monday of `start`'s week."""
    first_monday = start - timedelta(days=start.weekday())
    return [first_monday + timedelta(weeks=i) for i in range(count)]
