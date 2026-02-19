import json
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
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from constants import (
    POSITION_PATH,
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
        self._warning: str | None = None  # current warning/error message
        self._warn_badge_rect: QRect | None = None  # hit-test area for warning badge
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
        interval_ms = self.settings.get("poll_interval_minutes", 5) * 60 * 1000
        self._timer.start(interval_ms)

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
        self._warning = None  # clear error on successful fetch
        self._tooltip.set_data(data, warning=None)
        self.update()

    def on_fetch_error(self, msg: str):
        print(f"[meter] fetch error: {msg}", file=sys.stderr)
        self._warning = msg
        self._tooltip.set_warning(msg)
        self.update()

    def _check_stale(self) -> str | None:
        """Return a warning string if data is stale (>2x poll interval)."""
        if not self._data:
            return None
        fetched = self._data.get("_fetchedAt", "")
        if not fetched:
            return None
        try:
            ft = datetime.fromisoformat(fetched)
            age_sec = (datetime.now(timezone.utc) - ft).total_seconds()
            interval_sec = self.settings.get("poll_interval_minutes", 5) * 60
            if age_sec > 2 * interval_sec:
                mins = int(age_sec) // 60
                return f"Data is stale (last updated {mins}m ago)"
        except Exception:
            pass
        return None

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

    def login_and_fetch(self):
        """Run ``claude /login`` in a background thread, then fetch usage."""
        if self._thread and self._thread.isRunning():
            return
        self._thread = QThread()
        self._fetcher = UsageFetcher()
        self._fetcher.moveToThread(self._thread)
        self._thread.started.connect(self._fetcher.login_and_run)
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
            badge_font = QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("badge_size", DEFAULT_SETTINGS["badge_size"]), QFont.Bold)
            fm = QFontMetrics(badge_font)
            text_w = fm.horizontalAdvance(mode_label)
            badge_w = text_w + 6
            badge_h = fm.height() + 2
            # Reference metrics at default badge size (7) for stable positioning
            ref_font = QFont(badge_font)
            ref_font.setPointSize(DEFAULT_SETTINGS["badge_size"])
            ref_fm = QFontMetrics(ref_font)
            ref_w = ref_fm.horizontalAdvance(mode_label) + 6
            ref_h = ref_fm.height() + 2
            # At default size, badge sits 1px inside the circle edge.
            # For larger sizes, shift outward by half the growth so it straddles.
            badge_x = cx - radius + 1 - (badge_w - ref_w) // 2
            badge_y = cy - radius + 1 - (badge_h - ref_h) // 2

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

        # --- Warning badge (bottom-left, styled like mode badge) ---
        active_warning = self._warning or self._check_stale()
        if active_warning:
            warn_label = "!"
            warn_font = QFont(self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]), self.settings.get("badge_size", DEFAULT_SETTINGS["badge_size"]), QFont.Bold)
            wfm = QFontMetrics(warn_font)
            wb_w = wfm.horizontalAdvance(warn_label) + 6
            wb_h = wfm.height() + 2
            ref_font = QFont(warn_font)
            ref_font.setPointSize(DEFAULT_SETTINGS["badge_size"])
            ref_fm = QFontMetrics(ref_font)
            ref_w = ref_fm.horizontalAdvance(warn_label) + 6
            ref_h = ref_fm.height() + 2
            wb_x = cx - radius + 1 - (wb_w - ref_w) // 2
            wb_y = cy + radius - ref_h - 1 - (wb_h - ref_h) // 2

            # Badge background (red)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#e74c3c"))
            p.drawRoundedRect(wb_x, wb_y, wb_w, wb_h, 3, 3)

            # Badge border
            warn_border = QColor(255, 255, 255, 120)
            p.setPen(QPen(warn_border, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(wb_x, wb_y, wb_w, wb_h, 3, 3)

            # Badge text (white)
            p.setPen(QColor("white"))
            p.setFont(warn_font)
            p.drawText(QRect(wb_x, wb_y, wb_w, wb_h),
                       Qt.AlignCenter, warn_label)

            self._warn_badge_rect = QRect(wb_x, wb_y, wb_w, wb_h)
        else:
            self._warn_badge_rect = None

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
            elif (self._warn_badge_rect
                  and self._warn_badge_rect.contains(event.position().toPoint())):
                # Click on warning badge — show error detail window
                active_warning = self._warning or self._check_stale()
                if active_warning:
                    self._show_error_window(active_warning)
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
            with open(POSITION_PATH, "w", encoding="utf-8") as f:
                json.dump({"x": pos.x(), "y": pos.y()}, f)
        except Exception:
            pass

    def _load_position(self):
        try:
            if POSITION_PATH.exists():
                with open(POSITION_PATH, "r", encoding="utf-8") as f:
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
        # Update warning state (stale check is dynamic)
        active_warning = self._warning or self._check_stale()
        self._tooltip.set_warning(active_warning)

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

        hide_action = menu.addAction("Hide Indicator")
        refresh_action = menu.addAction("Refresh")
        login_action = menu.addAction("Log in")
        settings_action = menu.addAction("Settings")
        about_action = menu.addAction("About")
        menu.addSeparator()
        quit_action = menu.addAction("Quit")

        action = menu.exec(event.globalPos())
        if action == hide_action:
            if hasattr(self, "_tray"):
                self._tray.toggle_indicator()
            else:
                self.hide()
                self._tooltip.hide()
        elif action == refresh_action:
            self.fetch_usage()
        elif action == login_action:
            self.login_and_fetch()
        elif action == settings_action:
            self.show_settings()
        elif action == about_action:
            self.show_about()
        elif action == quit_action:
            QApplication.quit()

    def _on_settings_changed(self, new_settings: dict):
        """Live-update the indicator whenever a setting changes in the dialog."""
        self.settings = deepcopy(new_settings)
        self.apply_settings()
        # Restart poll timer if interval changed
        interval_ms = self.settings.get("poll_interval_minutes", 5) * 60 * 1000
        if self._timer.interval() != interval_ms:
            self._timer.start(interval_ms)

    def show_settings(self):
        self._show_tooltip()
        dialog = SettingsDialog(self.settings, self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()
        self._tooltip.hide()
        # After dialog closes, reload whatever was saved (or reverted)
        self.load_settings()
        self.apply_settings()

    # -- About dialog helpers -------------------------------------------------

    @staticmethod
    def _build_session_html(result: dict | None) -> tuple[str, str]:
        """Return (session_html, api_status_html) from a fetch_profile result."""
        if not result:
            return "", ""
        profile = result.get("profile")
        diag = result.get("diagnostics", {})

        session_html = ""

        # --- Account / Session section ---
        acct_rows: list[str] = []
        if profile:
            acct = profile.get("account", {})
            org = profile.get("organization", {})
            name = acct.get("display_name") or acct.get("full_name") or ""
            email = acct.get("email", "")
            org_type = org.get("organization_type", "")
            plan = {"claude_pro": "Pro", "claude_max": "Max", "claude_team": "Team",
                    "claude_enterprise": "Enterprise"}.get(org_type, org_type.replace("_", " ").title())
            tier = org.get("rate_limit_tier", "")
            if tier:
                tier = tier.replace("default_", "").replace("_", " ").title()
            sub_status = org.get("subscription_status", "")

            if name:
                acct_rows.append(f"<b>Account:</b> {name}")
            if email:
                acct_rows.append(f"<b>Email:</b> {email}")
            if plan:
                acct_rows.append(f"<b>Plan:</b> {plan}")
            if tier:
                acct_rows.append(f"<b>Rate Limit:</b> {tier}")
            if sub_status:
                acct_rows.append(f"<b>Status:</b> {sub_status.replace('_', ' ').title()}")

        if acct_rows:
            session_html += (
                '<hr><p style="margin-bottom:2px"><b>Current Session</b></p>'
                "<p>" + "<br>".join(acct_rows) + "</p>"
            )

        # --- Connection / Diagnostics (without API Status) ---
        diag_rows: list[str] = []
        api_base = diag.get("api_base", "")
        if api_base:
            diag_rows.append(f"<b>API Endpoint:</b> {api_base}")
        cred_src = diag.get("credential_source", "")
        if cred_src:
            diag_rows.append(f"<b>Credentials:</b> {cred_src}")
        token_exp = diag.get("token_expires", "")
        if token_exp:
            expired_tag = ' <span style="color:#e74c3c">(expired)</span>' if diag.get("token_expired") else ""
            diag_rows.append(f"<b>Token Expires:</b> {token_exp}{expired_tag}")

        if diag_rows:
            session_html += (
                '<hr><p style="margin-bottom:2px"><b>Connection</b></p>'
                "<p>" + "<br>".join(diag_rows) + "</p>"
            )

        # --- API Status (rendered separately so refresh button can update it) ---
        api_status = diag.get("api_status", "")
        if api_status == 200:
            api_status_html = '<b>API Status:</b> <span style="color:#27ae60">200 OK</span>'
        elif api_status:
            api_status_html = f'<b>API Status:</b> <span style="color:#e74c3c">{api_status}</span>'
        else:
            api_status_html = '<b>API Status:</b> <span style="color:#888">unknown</span>'

        return session_html, api_status_html

    def _show_error_window(self, message: str):
        """Show a dialog with the full warning/error text and a Copy button."""
        from tray import make_tray_icon
        from PySide6.QtWidgets import QTextEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("Warning Details")
        dlg.setWindowIcon(make_tray_icon())
        dlg.setMinimumSize(400, 200)
        dlg.setStyleSheet(MENU_STYLESHEET + """
            QDialog { background-color: #1a1714; }
            QTextEdit {
                background-color: #2a2520;
                color: #ccc;
                border: 1px solid #333;
                padding: 8px;
                font-size: 12px;
            }
            QPushButton {
                background-color: #d9773c;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #e8a838; }
        """)
        layout = QVBoxLayout(dlg)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(message)
        layout.addWidget(text_edit)
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(message))
        layout.addWidget(copy_btn)
        dlg.exec()

    def show_about(self):
        from tray import make_tray_icon

        fetcher = UsageFetcher()
        result = fetcher.fetch_profile()
        session_html, api_status_html = self._build_session_html(result)

        dlg = QDialog(self)
        dlg.setWindowTitle("About Claude Usage Meter")
        dlg.setWindowIcon(make_tray_icon())
        dlg.setStyleSheet(
            MENU_STYLESHEET
            + "QDialog { background-color: #1a1714; color: #ddd; }"
              "QLabel { color: #ddd; }"
              "QPushButton { background: #333; color: #ddd; border: 1px solid #555;"
              "  border-radius: 3px; padding: 1px 6px; }"
              "QPushButton:hover { background: #d9773c; color: white; }"
              "QPushButton#refresh { font-size: 10px; padding: 0px; margin: 0px;"
              "  border: none; background: transparent; color: #999; }"
              "QPushButton#refresh:hover { color: #d9773c; }"
        )

        layout = QVBoxLayout(dlg)

        # Main about content
        about_label = QLabel(
            "<h3>Claude Usage Meter</h3>"
            "<p>A desktop widget for monitoring Claude API usage in real-time.</p>"
            "<p>Created by <b>Yonathan Amir</b><br>"
            "Built with <b>Claude Code</b></p>"
            '<p><a href="https://github.com/yonathanamir/claude-usage-meter">'
            "github.com/yonathanamir/claude-usage-meter</a></p>"
            + session_html
        )
        about_label.setTextFormat(Qt.RichText)
        about_label.setOpenExternalLinks(True)
        about_label.setWordWrap(True)
        layout.addWidget(about_label)

        # API Status row with refresh button
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(4)
        status_label = QLabel(api_status_html)
        status_label.setTextFormat(Qt.RichText)
        status_row.addWidget(status_label)

        refresh_btn = QPushButton("\u21bb")
        refresh_btn.setObjectName("refresh")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setToolTip("Refresh API status")

        def on_refresh():
            refresh_btn.setEnabled(False)
            refresh_btn.setText("\u22ef")
            QApplication.processEvents()
            new_result = fetcher.fetch_profile()
            _, new_api_html = self._build_session_html(new_result)
            status_label.setText(new_api_html)
            refresh_btn.setText("\u21bb")
            refresh_btn.setEnabled(True)

        refresh_btn.clicked.connect(on_refresh)
        status_row.addWidget(refresh_btn)
        status_row.addStretch()
        layout.addLayout(status_row)

        # OK button
        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(28)
        ok_btn.clicked.connect(dlg.accept)
        ok_layout = QHBoxLayout()
        ok_layout.addStretch()
        ok_layout.addWidget(ok_btn)
        layout.addLayout(ok_layout)

        dlg.exec()
