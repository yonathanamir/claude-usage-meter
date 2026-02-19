import json
import subprocess
import time
from datetime import datetime, timezone

import requests
from PySide6.QtCore import QObject, Signal

from constants import (
    CREDENTIALS_PATH, USAGE_URL, TOKEN_URL, BETA_HEADER,
    IS_MACOS, KEYCHAIN_SERVICE, login_command,
)


class UsageFetcher(QObject):
    finished = Signal(dict)
    error = Signal(str)

    # ------------------------------------------------------------------
    # Credential reading
    # ------------------------------------------------------------------

    def _read_full_credentials(self):
        """Return the full credentials dict (with 'claudeAiOauth' key).

        Tries the JSON file first, then macOS Keychain.
        """
        # Try file first (works on all platforms)
        if CREDENTIALS_PATH.exists():
            try:
                with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("claudeAiOauth"):
                    return data
            except (json.JSONDecodeError, OSError):
                pass

        # On macOS, try Keychain
        if IS_MACOS:
            return self._read_keychain()

        return None

    def _read_credentials(self):
        """Return just the claudeAiOauth dict (access/refresh tokens etc.)."""
        full = self._read_full_credentials()
        if full:
            return full.get("claudeAiOauth")
        return None

    def _read_keychain(self):
        """Read the full credentials JSON from macOS Keychain."""
        try:
            result = subprocess.run(
                ["security", "find-generic-password",
                 "-s", KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            return json.loads(result.stdout.strip())
        except (json.JSONDecodeError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError):
            return None

    # ------------------------------------------------------------------
    # Credential writing
    # ------------------------------------------------------------------

    def _persist_full_credentials(self, full: dict):
        """Write credentials back to the appropriate store."""
        if IS_MACOS:
            self._write_keychain(full)
        else:
            CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
                json.dump(full, f, indent=2)

    def _write_keychain(self, full: dict):
        """Write credentials JSON into macOS Keychain.

        Falls back to file if keychain write fails.
        """
        try:
            json_str = json.dumps(full)
            acct = self._get_keychain_account() or ""

            # Delete old entry (ignore errors if it doesn't exist)
            subprocess.run(
                ["security", "delete-generic-password",
                 "-s", KEYCHAIN_SERVICE, "-a", acct],
                capture_output=True, timeout=5,
            )
            # Add updated entry
            subprocess.run(
                ["security", "add-generic-password",
                 "-s", KEYCHAIN_SERVICE, "-a", acct,
                 "-w", json_str],
                capture_output=True, timeout=5, check=True,
            )
        except Exception:
            # Fallback: persist to file
            CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
                json.dump(full, f, indent=2)

    def _get_keychain_account(self):
        """Return the 'acct' attribute of the keychain entry, or None."""
        try:
            result = subprocess.run(
                ["security", "find-generic-password",
                 "-s", KEYCHAIN_SERVICE],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            # security prints attributes to stderr
            for line in (result.stderr + result.stdout).splitlines():
                if '"acct"<blob>=' in line:
                    return line.split("<blob>=", 1)[1].strip().strip('"')
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    def _refresh_token(self, refresh_token: str):
        """Exchange a refresh token for a new access token."""
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "user:profile user:inference user:sessions:claude_code user:mcp_servers",
        }
        r = requests.post(TOKEN_URL, json=payload,
                          headers={"Content-Type": "application/json"}, timeout=10)
        if r.status_code != 200:
            return None
        body = r.json()
        access_token = body.get("access_token")
        new_refresh = body.get("refresh_token", refresh_token)
        expires_in = body.get("expires_in", 3600)
        expires_at = int(time.time() * 1000) + expires_in * 1000

        # Persist refreshed tokens
        full = self._read_full_credentials() or {}
        oauth = full.get("claudeAiOauth", {})
        oauth["accessToken"] = access_token
        oauth["refreshToken"] = new_refresh
        oauth["expiresAt"] = expires_at
        full["claudeAiOauth"] = oauth
        self._persist_full_credentials(full)

        return access_token

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def _login(self):
        """Spawn `claude /login` and wait for user to complete OAuth."""
        try:
            subprocess.run(login_command(), shell=True, timeout=120)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def login_and_run(self):
        """Force a fresh ``claude /login``, then fetch usage."""
        self._login()
        self.run()

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
