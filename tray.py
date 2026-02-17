import subprocess

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from constants import COLOR_ORANGE, MENU_STYLESHEET


def make_tray_icon() -> QIcon:
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


def setup_tray(app, meter) -> QSystemTrayIcon:
    """Create and configure the system tray icon with its context menu."""
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("Claude Usage Meter")

    tray_menu = QMenu()
    tray_menu.setStyleSheet(MENU_STYLESHEET)

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

    login_action = QAction("Log in", tray_menu)
    login_action.triggered.connect(lambda: subprocess.Popen("claude.cmd /login", shell=True))
    tray_menu.addAction(login_action)

    settings_action = QAction("Settings", tray_menu)
    settings_action.triggered.connect(meter.show_settings)
    tray_menu.addAction(settings_action)

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

    tray.toggle_action = toggle_action
    tray.toggle_indicator = _toggle_indicator

    return tray
