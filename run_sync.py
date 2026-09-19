#!/usr/bin/env python3
"""Entry point for manual runs and for cron/systemd to call.

Usage:
    python3 run_sync.py
"""
import logging

from hse_schedule_mover.config import load_settings
from hse_schedule_mover.sync import sync

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sync(load_settings())
