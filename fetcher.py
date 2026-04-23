import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal

from constants import (
    CREDENTIALS_PATH, USAGE_URL, PROFILE_URL, TOKEN_URL, BETA_HEADER,
    IS_MACOS, KEYCHAIN_SERVICE, login_command, CODEX_SESSIONS_PATH,
    PROVIDER_CLAUDE, PROVIDER_CODEX,
)


class UsageFetcher(QObject):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, providers: list[str] | None = None):
        super().__init__()
        self.providers = providers or [PROVIDER_CLAUDE]

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

    def fetch_profile(self):
        """Fetch the user's profile and connection diagnostics.

        Returns a dict with 'profile' (API response or None) and
        'diagnostics' (credential/connection metadata), or None if
        no credentials exist at all.
        """
        result = {"profile": None, "diagnostics": {}}
        diag = result["diagnostics"]

        # Credential source
        full = self._read_full_credentials()
        if full is None:
            if IS_MACOS:
                diag["credential_source"] = "Not found (file / Keychain)"
            else:
                diag["credential_source"] = "Not found"
            return result

        diag["credential_source"] = "File"
        if IS_MACOS and not CREDENTIALS_PATH.exists():
            diag["credential_source"] = "macOS Keychain"

        creds = full.get("claudeAiOauth", {})
        token = creds.get("accessToken")

        # Token expiry
        expires_at = creds.get("expiresAt", 0)
        if expires_at:
            try:
                exp_dt = datetime.fromtimestamp(expires_at / 1000, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                diag["token_expires"] = exp_dt.strftime("%Y-%m-%d %H:%M UTC")
                diag["token_expired"] = expires_at < time.time() * 1000
            except Exception:
                pass

        # API endpoint
        diag["api_base"] = PROFILE_URL.rsplit("/api/", 1)[0]

        if not token:
            return result

        # Fetch profile from API
        try:
            r = requests.get(PROFILE_URL, headers=self._build_headers(token), timeout=10)
            diag["api_status"] = r.status_code
            if r.status_code == 200:
                result["profile"] = r.json()
            else:
                diag["api_error"] = r.text[:200]
        except requests.ConnectionError:
            diag["api_status"] = "Connection failed"
        except requests.Timeout:
            diag["api_status"] = "Timeout"
        except Exception as exc:
            diag["api_status"] = f"Error: {exc}"

        return result

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def login_and_run(self):
        """Force a fresh ``claude /login``, then fetch usage."""
        self._login()
        self.run()

    def run(self):
        results = {}
        for provider_id in self.providers:
            try:
                if provider_id == PROVIDER_CLAUDE:
                    results[provider_id] = {"data": self._fetch_claude_usage(), "warning": None}
                elif provider_id == PROVIDER_CODEX:
                    results[provider_id] = {"data": self._fetch_codex_usage(), "warning": None}
            except Exception as exc:
                results[provider_id] = {"data": None, "warning": str(exc)}

        if results:
            self.finished.emit(results)
        else:
            self.error.emit("No subscriptions are enabled")

    def _fetch_claude_usage(self) -> dict:
        try:
            creds = self._read_credentials()
            if not creds:
                self._login()
                creds = self._read_credentials()
                if not creds:
                    raise RuntimeError("No credentials found after login")

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
                        raise RuntimeError("Login failed")
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
                        raise RuntimeError("Auth failed")
                    token = creds["accessToken"]
                    resp = self._fetch(token)

            if resp.status_code != 200:
                raise RuntimeError(f"API {resp.status_code}: {resp.text[:200]}")

            data = resp.json()
            # Attach subscription info from credentials
            creds = self._read_credentials()
            if creds:
                data["_subscriptionType"] = creds.get("subscriptionType", "")
                data["_rateLimitTier"] = creds.get("rateLimitTier", "")
            data["_fetchedAt"] = datetime.now(timezone.utc).isoformat()
            return data

        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    def _fetch_codex_usage(self) -> dict:
        event = self._latest_codex_rate_limit_event()
        if not event:
            raise RuntimeError("No Codex rate-limit snapshot found. Run Codex once, then refresh.")

        payload = event.get("payload", {})
        rate_limits = payload.get("rate_limits") or {}
        primary = rate_limits.get("primary") or {}
        secondary = rate_limits.get("secondary") or {}
        credits = rate_limits.get("credits") or {}

        fetched_at = self._codex_timestamp(event.get("timestamp"))
        data = {
            "_subscriptionType": rate_limits.get("plan_type") or "codex",
            "_rateLimitTier": "Credits available" if credits.get("has_credits") else "",
            "_fetchedAt": fetched_at,
        }

        if primary:
            data["five_hour"] = self._codex_bucket(primary)
        if secondary:
            data["seven_day"] = self._codex_bucket(secondary)
        if credits:
            data["extra_usage"] = {
                "is_enabled": bool(credits.get("has_credits")),
                "used_credits": None,
                "monthly_limit": None,
            }
        if not primary and not secondary:
            raise RuntimeError("Latest Codex snapshot did not include rate-limit data")
        return data

    @staticmethod
    def _codex_bucket(raw: dict) -> dict:
        resets_at = raw.get("resets_at")
        if isinstance(resets_at, (int, float)):
            resets_at = datetime.fromtimestamp(resets_at, tz=timezone.utc).isoformat()
        return {
            "utilization": raw.get("used_percent", 0) or 0,
            "resets_at": resets_at or "",
            "window_minutes": raw.get("window_minutes"),
        }

    @staticmethod
    def _codex_timestamp(timestamp: str | None) -> str:
        if not timestamp:
            return datetime.now(timezone.utc).isoformat()
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return datetime.now(timezone.utc).isoformat()

    def _latest_codex_rate_limit_event(self) -> dict | None:
        if not CODEX_SESSIONS_PATH.exists():
            return None

        files = sorted(
            CODEX_SESSIONS_PATH.rglob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files[:20]:
            event = self._latest_rate_limit_event_in_file(path)
            if event:
                return event
        return None

    @staticmethod
    def _latest_rate_limit_event_in_file(path: Path) -> dict | None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload") or {}
            if payload.get("type") == "token_count" and payload.get("rate_limits"):
                return event
        return None
