from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from constants import MODE_SESSION, MODE_KEYS, color_for_percent
from settings import DEFAULT_SETTINGS


class TooltipWidget(QWidget):
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.settings = settings or DEFAULT_SETTINGS
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._data: dict | None = None
        self._warning: str | None = None
        self._active_mode: int = MODE_SESSION
        self._width = 260
        self._row_h = 22
        self.hide()

    def set_data(self, data: dict | None, warning: str | None = None):
        self._data = data
        self._warning = warning
        self._recalc_size()
        self.update()

    def set_warning(self, warning: str | None):
        self._warning = warning
        self._recalc_size()
        self.update()

    def _rows(self) -> list[tuple[str, str, dict | None]]:
        """Return (label, api_key, value_dict) tuples."""
        if not self._data:
            return []
        rows = []
        mapping = [
            ("five_hour", "Current session (5h)"),
            ("seven_day", "Weekly (all models)"),
            ("seven_day_sonnet", "Weekly (Sonnet)"),
        ]
        for key, label in mapping:
            val = self._data.get(key)
            if val:
                rows.append((label, key, val))
        return rows

    def _recalc_size(self):
        rows = self._rows()
        header_h = 46  # plan name + divider
        bar_rows = len(rows) * (self._row_h + 22)  # label + bar
        extra_h = 30  # footer
        warning_h = 36 if self._warning else 0
        h = header_h + bar_rows + extra_h + warning_h + 16
        self.setFixedSize(self._width, max(h, 80))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background rounded rect
        bg = QColor(self.settings.get("color_bg", DEFAULT_SETTINGS["color_bg"]))
        bg.setAlpha(240)
        p.setBrush(bg)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect().adjusted(4, 4, -4, -4), 10, 10)

        # Border
        border = QColor(self.settings.get("font_color", DEFAULT_SETTINGS["font_color"]))
        border.setAlpha(60)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(4, 4, -4, -4), 10, 10)

        hfs = self.settings.get("hover_font_size", DEFAULT_SETTINGS.get("hover_font_size", 9))

        if not self._data:
            p.setPen(QColor("#aaa"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs + 1))
            p.drawText(self.rect(), Qt.AlignCenter, "Loading...")
            p.end()
            return

        x_pad = 14
        y = 14

        # Plan name
        sub_type = self._data.get("_subscriptionType", "unknown")
        plan_label = {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise"}.get(sub_type, sub_type.title() if sub_type else "Unknown")
        tier = self._data.get("_rateLimitTier", "")

        p.setPen(QColor(self.settings.get("font_color", DEFAULT_SETTINGS["font_color"])))
        p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs + 2, QFont.Bold))
        p.drawText(x_pad, y + 14, f"Claude {plan_label}")

        if tier:
            tier_short = tier.replace("default_claude_", "").replace("_", " ").title()
            p.setPen(QColor("#888"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs - 1))
            p.drawText(x_pad, y + 28, tier_short)

        y += 38

        # Divider
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(x_pad, y, self._width - x_pad, y)
        y += 10

        # Usage bars
        rows = self._rows()
        active_key = MODE_KEYS[self._active_mode]
        bar_w = self._width - 2 * x_pad
        for label, api_key, val in rows:
            is_active = api_key == active_key
            util = val.get("utilization", 0) or 0
            resets = val.get("resets_at", "")

            # Highlight background for active row
            if is_active:
                hl = QColor(self.settings.get("color_orange", DEFAULT_SETTINGS["color_orange"]))
                hl.setAlpha(25)
                p.setPen(Qt.NoPen)
                p.setBrush(hl)
                p.drawRoundedRect(x_pad - 6, y - 2, bar_w + 12, self._row_h + 24, 4, 4)

            # Label + percentage
            label_color = QColor(self.settings.get("font_color", DEFAULT_SETTINGS["font_color"])) if is_active else QColor("#ccc")
            p.setPen(label_color)
            font_weight = QFont.Bold if is_active else QFont.Normal
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs, font_weight))
            p.drawText(x_pad, y + 13, label)

            pct_text = f"{util:.0f}%"
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(pct_text)
            p.setPen(color_for_percent(util, self.settings))
            p.drawText(self._width - x_pad - tw, y + 13, pct_text)
            y += 18

            # Bar background
            bar_h = 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 20))
            p.drawRoundedRect(x_pad, y, bar_w, bar_h, 3, 3)

            # Bar fill
            fill_w = max(0, min(bar_w, bar_w * util / 100))
            if fill_w > 0:
                c = color_for_percent(util, self.settings)
                p.setBrush(c)
                p.drawRoundedRect(x_pad, y, int(fill_w), bar_h, 3, 3)

            # Reset time
            if resets:
                try:
                    display_mode = self.settings.get("current_session_display") if "session" in label.lower() else self.settings.get("weekly_session_display")

                    if display_mode != "None":
                        reset_dt = datetime.fromisoformat(resets)
                        now = datetime.now(timezone.utc)
                        delta = reset_dt - now
                        total_sec = max(0, int(delta.total_seconds()))
                        hours = total_sec // 3600
                        mins = (total_sec % 3600) // 60

                        if display_mode == "Date":
                            reset_str = f"resets on {reset_dt.strftime('%b %d')}"
                        else:  # Time Until
                            reset_str = f"resets in {hours}h {mins}m" if hours else f"resets in {mins}m"

                        p.setPen(QColor("#666"))
                        p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs - 2))
                        p.drawText(x_pad, y + bar_h + 10, reset_str)
                except Exception:
                    pass

            y += bar_h + 16

        # Extra usage
        extra = self._data.get("extra_usage")
        if extra and extra.get("is_enabled"):
            p.setPen(QColor("#888"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs - 1))
            limit = extra.get("monthly_limit")
            used = extra.get("used_credits")
            if limit is not None and used is not None:
                p.drawText(x_pad, y + 10, f"Extra usage: ${used / 100:.2f} / ${limit / 100:.2f}")
            else:
                p.drawText(x_pad, y + 10, "Extra usage: enabled")
            y += 16

        # Warning section
        if self._warning:
            warn_pad = 6
            warn_h = 24
            warn_rect_x = x_pad - 2
            warn_rect_w = self._width - 2 * (x_pad - 2)
            # Dark translucent background with subtle red tint
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(80, 30, 30, 160))
            p.drawRoundedRect(warn_rect_x, y, warn_rect_w, warn_h, 4, 4)
            # Subtle red border
            p.setPen(QPen(QColor(200, 60, 60, 100), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(warn_rect_x, y, warn_rect_w, warn_h, 4, 4)
            # Warning text in muted red
            p.setPen(QColor(230, 120, 100))
            warn_font = QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs - 1)
            p.setFont(warn_font)
            fm = QFontMetrics(warn_font)
            elided = fm.elidedText(self._warning, Qt.ElideRight, warn_rect_w - 2 * warn_pad)
            p.drawText(warn_rect_x + warn_pad, y + warn_h - 8, elided)
            y += warn_h + 6

        # Last updated
        fetched = self._data.get("_fetchedAt", "")
        if fetched:
            try:
                ft = datetime.fromisoformat(fetched)
                age = datetime.now(timezone.utc) - ft
                mins_ago = int(age.total_seconds()) // 60
                if mins_ago < 1:
                    age_str = "just now"
                else:
                    age_str = f"{mins_ago}m ago"
            except Exception:
                age_str = ""
            p.setPen(QColor("#555"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), hfs - 2))
            p.drawText(x_pad, self.height() - 10, f"Updated {age_str}")

        p.end()
