import platform
from pathlib import Path

from PySide6.QtGui import QColor

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

SYSTEM = platform.system()
IS_MACOS = SYSTEM == "Darwin"
IS_WINDOWS = SYSTEM == "Windows"

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
POSITION_PATH = Path.home() / ".claude" / "meter-position.json"
CODEX_SESSIONS_PATH = Path.home() / ".codex" / "sessions"

# ---------------------------------------------------------------------------
# macOS Keychain
# ---------------------------------------------------------------------------

KEYCHAIN_SERVICE = "Claude Code-credentials"


def login_command() -> str:
    """Return the shell command to invoke ``claude /login``."""
    if IS_WINDOWS:
        return "claude.cmd /login"
    import shutil
    claude = shutil.which("claude") or "claude"
    return f"{claude} /login"

# ---------------------------------------------------------------------------
# API configuration
# ---------------------------------------------------------------------------

API_BASE = "https://api.anthropic.com"
USAGE_URL = f"{API_BASE}/api/oauth/usage"
PROFILE_URL = f"{API_BASE}/api/oauth/profile"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
BETA_HEADER = "oauth-2025-04-20"

# ---------------------------------------------------------------------------
# Polling & UI
# ---------------------------------------------------------------------------

POLL_INTERVAL_MS = 5 * 60 * 1000  # 5 minutes

EDGE_MARGIN = 12

# Display modes the circle cycles through on left-click
MODE_SESSION = 0   # five_hour
MODE_WEEKLY = 1    # seven_day
MODE_KEYS = ["five_hour", "seven_day"]
MODE_LABELS = ["5h", "7d"]

PROVIDER_CLAUDE = "claude"
PROVIDER_CODEX = "codex"
PROVIDER_ORDER = [PROVIDER_CLAUDE, PROVIDER_CODEX]

PROVIDER_DEFAULTS = {
    PROVIDER_CLAUDE: {
        "name": "Claude",
        "short_name": "C",
        "enabled": True,
        "color_bg": "#1a1714",
        "color_orange": "#d9773c",
        "color_amber": "#e8a838",
        "color_red": "#e74c3c",
    },
    PROVIDER_CODEX: {
        "name": "Codex",
        "short_name": "X",
        "enabled": False,
        "color_bg": "#101820",
        "color_orange": "#2f80ed",
        "color_amber": "#56ccf2",
        "color_red": "#eb5757",
    },
}

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

COLOR_BG = QColor("#1a1714")
COLOR_ORANGE = QColor("#d9773c")
COLOR_AMBER = QColor("#e8a838")
COLOR_RED = QColor("#e74c3c")
COLOR_GREEN = QColor("#27ae60")

# ---------------------------------------------------------------------------
# Shared stylesheet for dark context menus
# ---------------------------------------------------------------------------

MENU_STYLESHEET = """
    QMenu {
        background-color: #1a1714;
        color: #ddd;
        border: 1px solid #333;
        padding: 4px;
    }
    QMenu::item:selected {
        background-color: #d9773c;
        color: white;
    }
"""


def provider_settings(settings: dict | None, provider_id: str) -> dict:
    defaults = PROVIDER_DEFAULTS.get(provider_id, PROVIDER_DEFAULTS[PROVIDER_CLAUDE])
    configured = (settings or {}).get("providers", {}).get(provider_id, {})
    merged = defaults.copy()
    merged.update(configured)
    return merged


def color_for_percent(
    pct: float,
    settings: dict | None = None,
    provider_id: str = PROVIDER_CLAUDE,
) -> QColor:
    if settings:
        provider = provider_settings(settings, provider_id)
        if pct > 80:
            return QColor(provider.get("color_red", "#e74c3c"))
        if pct > 50:
            return QColor(provider.get("color_amber", "#e8a838"))
        return QColor(provider.get("color_orange", "#d9773c"))
    if pct > 80:
        return COLOR_RED
    if pct > 50:
        return COLOR_AMBER
    return COLOR_ORANGE
