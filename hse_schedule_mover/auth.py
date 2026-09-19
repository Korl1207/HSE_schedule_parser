"""Login to lk.hse.ru through the HSE Keycloak SSO (saml.hse.ru).

Reverse-engineered from a captured HAR of a real login:

1. GET  saml.hse.ru/realms/hse/protocol/openid-connect/auth?client_id=elk&...
   -> if there's no live SSO session, returns an HTML login page with a
      <form id="kc-form-login"> whose `action` URL carries one-time
      `session_code`/`execution` values.
   -> if there IS a live SSO session (cookies from a previous login are
      still valid), Keycloak skips the form entirely and redirects straight
      through to step 3.
2. POST that form action with username/password/credentialId (form-urlencoded)
   -> 302 redirect to lk.hse.ru/api/keycloak-auth/?code=...&session_state=...
3. lk.hse.ru exchanges the code server-side and returns an HTML page with
   `const accessToken = '...'` / `const idToken = '...'` embedded, which the
   real frontend stores in localStorage and attaches as
   `Authorization: Bearer <token>` on every /api/* call.

The access token is a 24h JWT and there is no refresh_token exposed to the
frontend. But the Keycloak SSO session cookies are long-lived, so instead of
storing the account password and using it on every run, we persist the
cookie jar and replay step 1 each time: as long as the SSO session is still
alive, that alone yields a fresh access token with no credentials needed.
The password is only used as a fallback once the SSO session has actually
expired.
"""
from __future__ import annotations

import base64
import json
import logging
import pickle
import re
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

AUTH_URL = "https://saml.hse.ru/realms/hse/protocol/openid-connect/auth"
CLIENT_ID = "elk"
REDIRECT_URI = "https://lk.hse.ru/api/keycloak-auth/"

_AUTH_PARAMS = {
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "scope": "openid",
    "ui_locales": "ru",
}

_FORM_ACTION_RE = re.compile(
    r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', re.IGNORECASE
)
_TOKEN_RE = re.compile(r"const accessToken = '([^']+)'")

_TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 60


class AuthError(RuntimeError):
    """Raised when login to the HSE SSO fails or its response is unexpected."""


@dataclass
class TokenInfo:
    access_token: str
    expires_at: float  # unix timestamp, from the JWT's `exp` claim

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at - _TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS


class HseAuth:
    """Keeps a persistent, authenticated session against lk.hse.ru."""

    def __init__(self, username: str, password: str, state_dir: Path):
        self.username = username
        self.password = password
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._cookie_path = self.state_dir / "cookies.pkl"

        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "Mozilla/5.0 (compatible; hse-schedule-mover/1.0)"}
        )
        self._token: TokenInfo | None = None
        self._load_cookies()

    @property
    def session(self) -> requests.Session:
        return self._session

    def get_access_token(self) -> str:
        """Returns a valid access token, logging in (or silently renewing) as needed."""
        if self._token is not None and not self._token.is_expired:
            return self._token.access_token

        token = self._try_silent_auth()
        if token is None:
            logger.info("SSO session absent/expired — doing full username+password login")
            token = self._full_login()
        else:
            logger.info("Renewed access token using the existing SSO session (no password needed)")

        self._token = token
        self._save_cookies()
        return token.access_token

    # -- login flow ----------------------------------------------------

    def _try_silent_auth(self) -> TokenInfo | None:
        resp = self._session.get(AUTH_URL, params=_AUTH_PARAMS, timeout=15)
        token = _extract_token(resp.text)
        return _token_info_from_jwt(token) if token else None

    def _full_login(self) -> TokenInfo:
        resp = self._session.get(AUTH_URL, params=_AUTH_PARAMS, timeout=15)
        match = _FORM_ACTION_RE.search(resp.text)
        if not match:
            raise AuthError(
                "could not find the HSE SSO login form — the login page markup "
                "may have changed"
            )
        action_url = unescape(match.group(1))

        resp = self._session.post(
            action_url,
            data={
                "username": self.username,
                "password": self.password,
                "credentialId": "",
            },
            timeout=15,
        )
        token = _extract_token(resp.text)
        if not token:
            raise AuthError(
                "login failed — check HSE_USERNAME/HSE_PASSWORD in .env "
                "(or the account requires a login step this script doesn't handle, e.g. 2FA)"
            )
        return _token_info_from_jwt(token)

    # -- cookie persistence ---------------------------------------------

    def _load_cookies(self) -> None:
        if self._cookie_path.exists():
            with self._cookie_path.open("rb") as f:
                self._session.cookies.update(pickle.load(f))

    def _save_cookies(self) -> None:
        with self._cookie_path.open("wb") as f:
            pickle.dump(self._session.cookies, f)


def _extract_token(html: str) -> str | None:
    match = _TOKEN_RE.search(html)
    return match.group(1) if match else None


def _token_info_from_jwt(token: str) -> TokenInfo:
    """Reads the `exp` claim straight out of the JWT payload (no signature
    check needed — we only use this to know when to refresh, and the token
    is only ever sent back to the server that issued it)."""
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    return TokenInfo(access_token=token, expires_at=payload["exp"])
