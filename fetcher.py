import json
import subprocess
import time
from datetime import datetime, timezone

import requests
from PySide6.QtCore import QObject, Signal

from constants import CREDENTIALS_PATH, API_BASE, USAGE_URL, TOKEN_URL, BETA_HEADER


class UsageFetcher(QObject):
    finished = Signal(dict)
    error = Signal(str)

    def _read_credentials(self):
        if not CREDENTIALS_PATH.exists():
            return None
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("claudeAiOauth")

    def _refresh_token(self, refresh_token: str):
        """Exchange a refresh token for a new access token."""
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "user:profile user:inference user:sessions:claude_code user:mcp_servers",
        }
        r = requests.post(TOKEN_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if r.status_code != 200:
            return None
        body = r.json()
        access_token = body.get("access_token")
        new_refresh = body.get("refresh_token", refresh_token)
        expires_in = body.get("expires_in", 3600)
        expires_at = int(time.time() * 1000) + expires_in * 1000

        # Persist refreshed tokens
        if CREDENTIALS_PATH.exists():
            with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
                full = json.load(f)
            oauth = full.get("claudeAiOauth", {})
            oauth["accessToken"] = access_token
            oauth["refreshToken"] = new_refresh
            oauth["expiresAt"] = expires_at
            full["claudeAiOauth"] = oauth
            with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
                json.dump(full, f, indent=2)

        return access_token

    def _login(self):
        """Spawn `claude /login` and wait for user to complete OAuth."""
        try:
            subprocess.run("claude.cmd /login", shell=True, timeout=120)
        except Exception:
            pass

    def _build_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "anthropic-beta": BETA_HEADER,
            "User-Agent": "claude-code-usage-meter/1.0",
        }

    def _fetch(self, token: str):
        r = requests.get(USAGE_URL, headers=self._build_headers(token), timeout=10)
        return r

    def run(self):
        try:
            creds = self._read_credentials()
            if not creds:
                self._login()
                creds = self._read_credentials()
                if not creds:
                    self.error.emit("No credentials found after login")
                    return

            token = creds.get("accessToken")
            expires_at = creds.get("expiresAt", 0)

            # Refresh if expired
            if expires_at < time.time() * 1000:
                refresh = creds.get("refreshToken")
                if refresh:
                    token = self._refresh_token(refresh)
                if not token:
                    self._login()
                    creds = self._read_credentials()
                    if not creds:
                        self.error.emit("Login failed")
                        return
                    token = creds.get("accessToken")

            resp = self._fetch(token)

            # Retry once on auth failure
            if resp.status_code in (401, 403):
                refresh = creds.get("refreshToken")
                if refresh:
                    token = self._refresh_token(refresh)
                if not token or (resp := self._fetch(token)).status_code in (401, 403):
                    self._login()
                    creds = self._read_credentials()
                    if not creds:
                        self.error.emit("Auth failed")
                        return
                    token = creds["accessToken"]
                    resp = self._fetch(token)

            if resp.status_code != 200:
                self.error.emit(f"API {resp.status_code}: {resp.text[:200]}")
                return

            data = resp.json()
            # Attach subscription info from credentials
            creds = self._read_credentials()
            if creds:
                data["_subscriptionType"] = creds.get("subscriptionType", "")
                data["_rateLimitTier"] = creds.get("rateLimitTier", "")
            data["_fetchedAt"] = datetime.now(timezone.utc).isoformat()
            self.finished.emit(data)

        except Exception as exc:
            self.error.emit(str(exc))
