import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from constants import (
    POSITION_PATH,
    POLL_INTERVAL_MS,
    EDGE_MARGIN,
    MODE_SESSION,
    MODE_KEYS,
    MODE_LABELS,
    MENU_STYLESHEET,
    color_for_percent,
)
from settings import SettingsDialog, DEFAULT_SETTINGS
from fetcher import UsageFetcher
from tooltip_widget import TooltipWidget


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
        self._timer.timeout.connect(self.fetch_usage)
        self._timer.start(POLL_INTERVAL_MS)

        # Load saved position or default
        self._load_position()

        # Initial fetch
        QTimer.singleShot(500, self.fetch_usage)

    def load_settings(self):
        self.settings = SettingsDialog.load_settings()

    def apply_settings(self):
        radius = self.settings.get("radius", 10)
        size = 2 * radius + 2 * EDGE_MARGIN
        self.setFixedSize(size, size)
        if self._tooltip:
            self._tooltip.settings = self.settings
            self._tooltip._active_mode = self._mode
            self._tooltip.update()
        self.update()

    # -- helpers --------------------------------------------------------------

    def _active_bucket(self) -> dict | None:
        """Return the usage dict for the currently selected mode."""
        if not self._data:
            return None
        return self._data.get(MODE_KEYS[self._mode])

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
            display_mode = self.settings.get("current_session_display") if self._mode == MODE_SESSION else self.settings.get("weekly_session_display")

            if display_mode == "None":
                return ""

            reset_dt = datetime.fromisoformat(resets_iso)
            now = datetime.now(timezone.utc)
            delta = reset_dt - now
            total_sec = max(0, int(delta.total_seconds()))
            days = total_sec // 86400
            hours = (total_sec % 86400) // 3600
            mins = (total_sec % 3600) // 60

            if display_mode == "Date":
                return f"{reset_dt.strftime('%b %d')}"
            else:  # Time Until
                if days:
                    return f"{days}d {hours}h"
                if hours:
                    return f"{hours}h {mins}m"
                return f"{mins}m"
        except Exception:
            return ""

    # -- Data -----------------------------------------------------------------

    def set_data(self, data: dict):
        self._data = data
        self._tooltip.set_data(data)
        self.update()

    def on_fetch_error(self, msg: str):
        print(f"[meter] fetch error: {msg}", file=sys.stderr)

    def fetch_usage(self):
        if self._thread and self._thread.isRunning():
            return
        self._thread = QThread()
        self._fetcher = UsageFetcher()
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
        p.setBrush(QColor(self.settings.get("color_bg", DEFAULT_SETTINGS["color_bg"])))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(cx, cy), radius, radius)

        # Track ring
        ring_r = radius - 5
        ring_rect = QRect(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        track_color = QColor(self.settings.get("color_orange", DEFAULT_SETTINGS["color_orange"]))
        track_color.setAlpha(30)
        track_pen = QPen(track_color, 5)
        track_pen.setCapStyle(Qt.RoundCap)
        p.setPen(track_pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(ring_rect, 0, 360 * 16)

        # Progress arc
        arc_color = color_for_percent(pct, self.settings) if pct > 0 else QColor(self.settings.get("font_color", DEFAULT_SETTINGS["font_color"]))
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
        show_number = self.settings.get("show_number", True)
        p.setPen(arc_color)
        if self._data:
            if show_number:
                p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]), QFont.Bold))
                p.drawText(QRect(0, 0, circle_size, cy + 2),
                           Qt.AlignHCenter | Qt.AlignBottom,
                           f"{int(pct)}")
        else:
            if show_number:
                p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]) - 2, QFont.Bold))
                p.drawText(self.rect(), Qt.AlignCenter, "...")
            p.end()
            return

        # --- Bottom line: reset countdown ---
        if show_number:
            reset_str = self._format_reset(self._active_resets_at())
            if reset_str:
                p.setPen(QColor(200, 200, 200, 140))
                p.setFont(QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]) - 5))
                p.drawText(QRect(0, cy + 4, circle_size, 16),
                           Qt.AlignHCenter | Qt.AlignTop,
                           reset_str)

        # --- Mode badge (top-left) ---
        if self.settings.get("show_badge", True):
            mode_label = MODE_LABELS[self._mode]
            badge_font = QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), 7, QFont.Bold)
            fm = QFontMetrics(badge_font)
            text_w = fm.horizontalAdvance(mode_label)
            badge_w = text_w + 6
            badge_h = fm.height() + 2
            badge_x = cx - radius + 1
            badge_y = cy - radius + 1

            # Badge background
            badge_bg = QColor(self.settings.get("color_bg", DEFAULT_SETTINGS["color_bg"]))
            badge_bg.setAlpha(220)
            p.setPen(Qt.NoPen)
            p.setBrush(badge_bg)
            p.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, 3, 3)

            # Badge border
            badge_border = QColor(arc_color)
            badge_border.setAlpha(120)
            p.setPen(QPen(badge_border, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, 3, 3)

            # Badge text
            p.setPen(arc_color)
            p.setFont(badge_font)
            p.drawText(QRect(badge_x, badge_y, badge_w, badge_h),
                       Qt.AlignCenter, mode_label)

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
                self._tooltip._active_mode = self._mode
                self._tooltip.update()
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
        menu.setStyleSheet(MENU_STYLESHEET)
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

    def _on_settings_changed(self, new_settings: dict):
        """Live-update the indicator whenever a setting changes in the dialog."""
        self.settings = deepcopy(new_settings)
        self.apply_settings()

    def show_settings(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()
        # After dialog closes, reload whatever was saved (or reverted)
        self.load_settings()
        self.apply_settings()
