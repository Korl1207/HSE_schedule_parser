#!/usr/bin/env python3
"""Pushes pending DB changes to Google Calendar on their own, without
re-fetching the schedule first.

Run this once by hand after putting data/state/client_secret.json in place
— it will open a browser for the one-time consent screen. After that it's
unattended and can run from cron (run_sync.py calls it automatically after
every schedule fetch, so this script is mainly for that first run / manual
debugging).

Usage:
    python3 run_calendar_sync.py
"""
import logging

from hse_schedule_mover.calendar_sync import sync_calendar
from hse_schedule_mover.config import load_settings

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sync_calendar(load_settings())
