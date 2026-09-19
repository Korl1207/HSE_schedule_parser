"""Google Calendar OAuth: one-time interactive browser consent, then a
cached refresh token so every later run is unattended.

This is a personal, unpublished OAuth client (consent screen left in
"Testing" status) authorized directly by the calendar's owner, so no Google
app-verification review is needed — the full `calendar` scope is fine here.
"""
from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_credentials(client_secret_path: Path, token_path: Path) -> Credentials:
    """Returns valid Credentials for the Calendar API, refreshing a saved
    token or running the one-time browser consent flow as needed.
    `token_path` is created/updated in place so subsequent runs don't need a
    browser at all."""
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired Google access token")
        creds.refresh(Request())
    else:
        if not client_secret_path.exists():
            raise RuntimeError(
                f"Google OAuth client secret not found at {client_secret_path} — "
                "download it from Google Cloud Console (APIs & Services > "
                "Credentials > OAuth client, Desktop app type) and put it there"
            )
        logger.info(
            "No saved Google credentials — opening a browser for the one-time consent flow"
        )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds
