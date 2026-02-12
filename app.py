"""
Claude Code Usage Meter — Native Windows overlay widget.
Reads OAuth credentials from ~/.claude/.credentials.json, queries the
Anthropic usage API, and renders a transparent floating circle that shows
the current rate-limit utilization.
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from usage import UsageFetcher
from vendors.claude import Claude
from vendors.gemini import Gemini





# ---------------------------------------------------------------------------
# TooltipWidget
# ---------------------------------------------------------------------------

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
        self._width = 260
        self._row_h = 22
        self.hide()

    def set_data(self, data: dict | None):
        self._data = data
        self._recalc_size()
        self.update()

    def _rows(self) -> list[tuple[str, dict | None]]:
        if not self._data:
            return []
        
        active_vendor_name = self.settings.get("enabled_vendors", ["Claude"])[0]
        vendor_data = self._data.get(active_vendor_name)
        if not vendor_data:
            return []

        rows = []
        mapping = [
            ("five_hour", "Current session (5h)"),
            ("seven_day", "Weekly (all models)"),
            ("seven_day_sonnet", "Weekly (Sonnet)"),
            ("seven_day_opus", "Weekly (Opus)"),
            ("seven_day_oauth_apps", "Weekly (OAuth apps)"),
            ("seven_day_cowork", "Weekly (Cowork)"),
        ]
        for key, label in mapping:
            val = vendor_data.get(key)
            if val:
                rows.append((label, val))
        return rows

    def _recalc_size(self):
        rows = self._rows()
        header_h = 46  # plan name + divider
        bar_rows = len(rows) * (self._row_h + 22)  # label + bar
        extra_h = 30  # footer
        h = header_h + bar_rows + extra_h + 16
        self.setFixedSize(self._width, max(h, 80))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background rounded rect
        bg = QColor("#1a1714")
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

        if not self._data:
            p.setPen(QColor("#aaa"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 10))
            p.drawText(self.rect(), Qt.AlignCenter, "Loading...")
            p.end()
            return

        active_vendor_name = self.settings.get("enabled_vendors", ["Claude"])[0]
        vendor_data = self._data.get(active_vendor_name)
        if not vendor_data:
            p.setPen(QColor("#aaa"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 10))
            p.drawText(self.rect(), Qt.AlignCenter, f"No data for {active_vendor_name}")
            p.end()
            return

        x_pad = 14
        y = 14

        # Plan name
        sub_type = vendor_data.get("_subscriptionType", "unknown")
        plan_label = {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise"}.get(sub_type, sub_type.title() if sub_type else "Unknown")
        tier = vendor_data.get("_rateLimitTier", "")

        p.setPen(QColor(self.settings.get("font_color", DEFAULT_SETTINGS["font_color"])))
        p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 11, QFont.Bold))
        p.drawText(x_pad, y + 14, f"{active_vendor_name} {plan_label}")

        if tier:
            tier_short = tier.replace("default_claude_", "").replace("_", " ").title()
            p.setPen(QColor("#888"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 8))
            p.drawText(x_pad, y + 28, tier_short)

        y += 38

        # Divider
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(x_pad, y, self._width - x_pad, y)
        y += 10

        # Usage bars
        rows = self._rows()
        bar_w = self._width - 2 * x_pad
        for label, val in rows:
            util = val.get("utilization", 0) or 0
            resets = val.get("resets_at", "")

            # Label + percentage
            p.setPen(QColor("#ccc"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 9))
            p.drawText(x_pad, y + 13, label)

            pct_text = f"{util:.0f}%"
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(pct_text)
            p.setPen(color_for_percent(util))
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
                c = color_for_percent(util)
                p.setBrush(c)
                p.drawRoundedRect(x_pad, y, int(fill_w), bar_h, 3, 3)

            # Reset time
            if resets:
                try:
                    reset_dt = datetime.fromisoformat(resets)
                    now = datetime.now(timezone.utc)
                    delta = reset_dt - now
                    total_sec = max(0, int(delta.total_seconds()))
                    hours = total_sec // 3600
                    mins = (total_sec % 3600) // 60
                    
                    display_mode = self.settings.get("current_session_display") if "session" in label.lower() else self.settings.get("weekly_session_display")

                    if display_mode == "Date":
                        reset_str = f"resets on {reset_dt.strftime('%b %d')}"
                    else: # Time Until
                        reset_str = f"resets in {hours}h {mins}m" if hours else f"resets in {mins}m"

                    p.setPen(QColor("#666"))
                    p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 7))
                    p.drawText(x_pad, y + bar_h + 10, reset_str)
                except Exception:
                    pass

            y += bar_h + 16

        # Extra usage
        extra = vendor_data.get("extra_usage")
        if extra and extra.get("is_enabled"):
            p.setPen(QColor("#888"))
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 8))
            limit = extra.get("monthly_limit")
            used = extra.get("used_credits")
            if limit is not None and used is not None:
                p.drawText(x_pad, y + 10, f"Extra usage: ${used / 100:.2f} / ${limit / 100:.2f}")
            else:
                p.drawText(x_pad, y + 10, "Extra usage: enabled")
            y += 16

        # Last updated
        fetched = vendor_data.get("_fetchedAt", "")
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
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 7))
            p.drawText(x_pad, self.height() - 10, f"Updated {age_str}")

        p.end()


# ---------------------------------------------------------------------------
# MeterWidget — the floating circle
# ---------------------------------------------------------------------------

class MeterWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.settings = {}
        self._data: dict | None = None
        self._mode = MODE_SESSION
        self._dragging = False
        self._drag_started = False
        self._drag_offset = QPoint()
        self._tooltip: TooltipWidget | None = None

        self.load_settings()

        self.vendors = {
            "Claude": Claude(api_key=self.settings.get("claude_api_key")),
            "Gemini": Gemini(api_key=self.settings.get("gemini_api_key"))
        }
        self.enabled_vendors = self.settings.get("enabled_vendors", ["Claude"])
        
        self._tooltip = TooltipWidget(settings=self.settings)

        self.apply_settings()

        self._mode = MODE_SESSION  # which bucket to display

        # Snap animation
        self._snap_anim = QPropertyAnimation(self, b"pos")
        self._snap_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._snap_anim.setDuration(250)

        # Fetcher thread
        self._thread: QThread | None = None
        self._fetcher: UsageFetcher | None = None

        # Periodic poll timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.fetch_all_usages)
        self._timer.start(POLL_INTERVAL_MS)

        # Load saved position or default
        self._load_position()

        # Initial fetch
        QTimer.singleShot(500, self.fetch_all_usages)

    def fetch_all_usages(self):
        for vendor_name in self.enabled_vendors:
            self.fetch_usage(vendor_name)

    def load_settings(self):
        if not SETTINGS_PATH.exists():
            self.settings = DEFAULT_SETTINGS
            return
        with open(SETTINGS_PATH, "r") as f:
            try:
                self.settings = json.load(f)
                # Ensure all keys are present
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in self.settings:
                        self.settings[key] = value
            except json.JSONDecodeError:
                self.settings = DEFAULT_SETTINGS

    def apply_settings(self):
        radius = self.settings.get("radius", 10)
        size = 2 * radius + 2 * EDGE_MARGIN
        self.setFixedSize(size, size)
        if self._tooltip:
            self._tooltip.settings = self.settings
        self.update()

    # -- helpers --------------------------------------------------------------

    def _active_vendor_name(self) -> str | None:
        return self.enabled_vendors[0] if self.enabled_vendors else None

    def _active_vendor_data(self) -> dict | None:
        vendor_name = self._active_vendor_name()
        if not vendor_name or not self._data:
            return None
        return self._data.get(vendor_name)

    def _active_bucket(self) -> dict | None:
        """Return the usage dict for the currently selected mode."""
        vendor_data = self._active_vendor_data()
        if not vendor_data:
            return None
        return vendor_data.get(MODE_KEYS[self._mode])

    def _active_percent(self) -> float:
        b = self._active_bucket()
        return (b.get("utilization", 0) or 0) if b else 0.0

    def _active_resets_at(self) -> str:
        b = self._active_bucket()
        return (b.get("resets_at", "") or "") if b else ""

    def _format_reset(self, resets_iso: str) -> str:
        """Return a compact string like '2h 14m' or '3d 5h'."""
        if not resets_iso:
            return ""
        try:
            reset_dt = datetime.fromisoformat(resets_iso)
            now = datetime.now(timezone.utc)
            delta = reset_dt - now
            total_sec = max(0, int(delta.total_seconds()))
            days = total_sec // 86400
            hours = (total_sec % 86400) // 3600
            mins = (total_sec % 3600) // 60
            
            display_mode = self.settings.get("current_session_display") if self._mode == MODE_SESSION else self.settings.get("weekly_session_display")

            if display_mode == "Date":
                return f"{reset_dt.strftime('%b %d')}"
            else: # Time Until
                if days:
                    return f"{days}d {hours}h"
                if hours:
                    return f"{hours}h {mins}m"
                return f"{mins}m"
        except Exception:
            return ""

    # -- Data -----------------------------------------------------------------

    def set_data(self, data: dict):
        vendor_name = data.get("vendor")
        usage = data.get("usage")
        if not vendor_name or not usage:
            return
    
        if self._data is None:
            self._data = {}
    
        self._data[vendor_name] = usage
        self._tooltip.set_data(self._data)
        self.update()

    def on_fetch_error(self, msg: str):
        print(f"[meter] fetch error: {msg}", file=sys.stderr)

    def fetch_usage(self, vendor_name: str):
        if self._thread and self._thread.isRunning():
            # For simplicity, we'll just skip if a fetch is already in progress.
            # A more robust solution might queue requests.
            return

        vendor = self.vendors.get(vendor_name)
        if not vendor:
            self.on_fetch_error(f"Unknown vendor: {vendor_name}")
            return

        self._thread = QThread()
        self._fetcher = UsageFetcher(vendor)
        self._fetcher.moveToThread(self._thread)
        self._thread.started.connect(self._fetcher.run)
        self._fetcher.finished.connect(self.set_data)
        self._fetcher.finished.connect(self._thread.quit)
        self._fetcher.error.connect(self.on_fetch_error)
        self._fetcher.error.connect(self._thread.quit)
        self._thread.start()

    # -- Painting -------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        pct = self._active_percent()
        
        radius = self.settings.get("radius", 10)
        circle_size = 2 * radius + 2 * EDGE_MARGIN
        cx, cy = circle_size // 2, circle_size // 2
        
        # Drop shadow
        shadow = QRadialGradient(cx, cy + 2, radius + 6)
        shadow.setColorAt(0, QColor(0, 0, 0, 80))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(shadow)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(cx, cy + 2), radius + 4, radius + 4)

        # Background circle
        p.setBrush(COLOR_BG)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(cx, cy), radius, radius)

        # Track ring
        ring_r = radius - 5
        ring_rect = QRect(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        track_pen = QPen(QColor(217, 119, 60, 30), 5)
        track_pen.setCapStyle(Qt.RoundCap)
        p.setPen(track_pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(ring_rect, 0, 360 * 16)

        # Progress arc
        arc_color = color_for_percent(pct) if pct > 0 else QColor(self.settings.get("font_color", DEFAULT_SETTINGS["font_color"]))
        if pct > 0:
            arc_pen = QPen(arc_color, 5)
            arc_pen.setCapStyle(Qt.RoundCap)
            p.setPen(arc_pen)
            start_angle = 90 * 16  # top
            span_angle = -int(pct * 3.6 * 16)
            p.drawArc(ring_rect, start_angle, span_angle)

        # Top dot at 12-o'clock
        dot_r = 3
        p.setPen(Qt.NoPen)
        p.setBrush(arc_color)
        p.drawEllipse(QPoint(cx, cy - ring_r), dot_r, dot_r)

        # --- Center: percentage number (shifted up to make room for reset line) ---
        p.setPen(arc_color)
        if self._data:
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]), QFont.Bold))
            p.drawText(QRect(0, 0, circle_size, cy + 2),
                       Qt.AlignHCenter | Qt.AlignBottom,
                       f"{int(pct)}")
        else:
            p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]) - 2, QFont.Bold))
            p.drawText(self.rect(), Qt.AlignCenter, "...")
            p.end()
            return

        # --- Bottom line: reset countdown + mode label ---
        reset_str = self._format_reset(self._active_resets_at())
        mode_label = MODE_LABELS[self._mode]
        bottom_text = f"{reset_str}  {mode_label}" if reset_str else mode_label

        p.setPen(QColor(200, 200, 200, 140))
        p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]) - 5))
        p.drawText(QRect(0, cy + 4, circle_size, 16),
                   Qt.AlignHCenter | Qt.AlignTop,
                   bottom_text)

        p.end()

    # -- Drag & Click ---------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_started = False
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._drag_started = True
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            was_drag = self._drag_started
            self._dragging = False
            self._drag_started = False
            if was_drag:
                self._snap_to_edge()
            else:
                # Pure click — toggle mode
                self._mode = (self._mode + 1) % len(MODE_KEYS)
                self.update()

    def _snap_to_edge(self):
        screen = QApplication.primaryScreen().availableGeometry()
        pos = self.pos()
        radius = self.settings.get("radius", 10)
        circle_size = 2 * radius + 2 * EDGE_MARGIN
        mid_x = pos.x() + circle_size // 2

        if mid_x < screen.center().x():
            target_x = screen.left() + EDGE_MARGIN
        else:
            target_x = screen.right() - circle_size - EDGE_MARGIN

        # Clamp Y
        target_y = max(screen.top() + EDGE_MARGIN, min(pos.y(), screen.bottom() - circle_size - EDGE_MARGIN))

        target = QPoint(target_x, target_y)
        self._snap_anim.setStartValue(self.pos())
        self._snap_anim.setEndValue(target)
        self._snap_anim.start()

        self._save_position(target)

    def _save_position(self, pos: QPoint):
        try:
            POSITION_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(POSITION_PATH, "w") as f:
                json.dump({"x": pos.x(), "y": pos.y()}, f)
        except Exception:
            pass

    def _load_position(self):
        try:
            if POSITION_PATH.exists():
                with open(POSITION_PATH, "r") as f:
                    d = json.load(f)
                self.move(d["x"], d["y"])
                return
        except Exception:
            pass
        # Default: right-center
        screen = QApplication.primaryScreen().availableGeometry()
        radius = self.settings.get("radius", 10)
        circle_size = 2 * radius + 2 * EDGE_MARGIN
        x = screen.right() - circle_size - EDGE_MARGIN
        y = screen.center().y() - circle_size // 2
        self.move(x, y)

    # -- Tooltip --------------------------------------------------------------

    def enterEvent(self, event):
        self._show_tooltip()

    def leaveEvent(self, event):
        self._tooltip.hide()

    def _show_tooltip(self):
        screen = QApplication.primaryScreen().availableGeometry()
        pos = self.pos()
        radius = self.settings.get("radius", 10)
        circle_size = 2 * radius + 2 * EDGE_MARGIN

        # Position tooltip to the left or right of the circle
        tt_w = self._tooltip.width()
        if pos.x() + circle_size + tt_w + 8 <= screen.right():
            tx = pos.x() + circle_size + 8
        else:
            tx = pos.x() - tt_w - 8

        ty = pos.y() - 20
        # Clamp
        ty = max(screen.top(), min(ty, screen.bottom() - self._tooltip.height()))

        self._tooltip.move(tx, ty)
        self._tooltip.show()

    # -- Right-click menu -----------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
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
        """)
        refresh_action = menu.addAction("Refresh")
        login_action = menu.addAction("Log in")
        settings_action = menu.addAction("Settings")
        menu.addSeparator()
        quit_action = menu.addAction("Quit")

        action = menu.exec(event.globalPos())
        if action == refresh_action:
            self.fetch_usage()
        elif action == login_action:
            try:
                subprocess.Popen("claude.cmd /login", shell=True)
            except Exception:
                pass
        elif action == settings_action:
            self.show_settings()
        elif action == quit_action:
            QApplication.quit()

    def show_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.load_settings()
            self.apply_settings()



# ---------------------------------------------------------------------------
# Tray icon helper
# ---------------------------------------------------------------------------

def _make_tray_icon() -> QIcon:
    """Paint a small orange circle icon for the system tray."""
    size = 64
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(COLOR_ORANGE)
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, size - 8, size - 8)
    p.setPen(QColor("#1a1714"))
    p.setFont(QFont("Segoe UI", 26, QFont.Bold))
    p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, "C")
    p.end()
    return QIcon(QPixmap.fromImage(img))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    meter = MeterWidget()
    meter.show()

    # --- System tray ---
    tray = QSystemTrayIcon(_make_tray_icon(), app)
    tray.setToolTip("Claude Usage Meter")

    tray_menu = QMenu()
    tray_menu.setStyleSheet("""
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
    """)

    toggle_action = QAction("Hide Indicator", tray_menu)

    def _toggle_indicator():
        if meter.isVisible():
            meter.hide()
            meter._tooltip.hide()
            toggle_action.setText("Show Indicator")
        else:
            meter.show()
            toggle_action.setText("Hide Indicator")

    toggle_action.triggered.connect(_toggle_indicator)
    tray_menu.addAction(toggle_action)

    refresh_action = QAction("Refresh", tray_menu)
    refresh_action.triggered.connect(meter.fetch_usage)
    tray_menu.addAction(refresh_action)

    tray_menu.addSeparator()

    quit_action = QAction("Quit", tray_menu)
    quit_action.triggered.connect(QApplication.quit)
    tray_menu.addAction(quit_action)

    tray.setContextMenu(tray_menu)

    # Left-click on tray icon toggles indicator
    def _on_tray_activated(reason):
        if reason == QSystemTrayIcon.Trigger:
            _toggle_indicator()

    tray.activated.connect(_on_tray_activated)
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
