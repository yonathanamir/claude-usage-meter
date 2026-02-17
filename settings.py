import json
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from tray import make_tray_icon
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

SETTINGS_PATH = Path.home() / ".claude" / "meter-settings.json"
DEFAULT_SETTINGS = {
    "radius": 30,
    "font_color": "#FFFFFF",
    "font_family": "Segoe UI",
    "font_size": 12,
    "show_number": True,
    "show_badge": True,
    "color_bg": "#1a1714",
    "color_orange": "#d9773c",
    "color_amber": "#e8a838",
    "color_red": "#e74c3c",
    "current_session_display": "Time Until",
    "weekly_session_display": "Date",
    "poll_interval_minutes": 5,
}


def _color_button_style(color_hex: str) -> str:
    """Return stylesheet for a color swatch button."""
    return (
        f"background-color: {color_hex}; border: 1px solid #555; "
        f"border-radius: 3px; min-width: 28px; min-height: 28px; max-width: 28px; max-height: 28px;"
    )


class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setWindowIcon(make_tray_icon())
        self.setMinimumWidth(340)

        # Snapshot so Cancel can restore
        self._open_settings = deepcopy(current_settings)
        self.settings = deepcopy(current_settings)

        self._build_ui()
        self._connect_live_signals()

    # -- UI construction -------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)

        # --- Radius ---
        radius_group = QGroupBox("Indicator Radius")
        radius_lay = QHBoxLayout()
        self._radius_slider = QSlider(Qt.Horizontal)
        self._radius_slider.setRange(10, 50)
        self._radius_slider.setValue(self.settings.get("radius", 30))
        self._radius_label = QLabel(str(self._radius_slider.value()))
        self._radius_label.setFixedWidth(24)
        self._radius_slider.valueChanged.connect(
            lambda v: self._radius_label.setText(str(v))
        )
        radius_lay.addWidget(self._radius_slider)
        radius_lay.addWidget(self._radius_label)
        radius_group.setLayout(radius_lay)
        root.addWidget(radius_group)

        # --- Colors ---
        colors_group = QGroupBox("Colors")
        colors_lay = QFormLayout()

        self._color_buttons: dict[str, QPushButton] = {}
        color_rows = [
            ("font_color", "Font Color"),
            ("color_bg", "Background"),
            ("color_orange", "Arc (0-50%)"),
            ("color_amber", "Arc (50-80%)"),
            ("color_red", "Arc (80-100%)"),
        ]
        for key, label in color_rows:
            btn = QPushButton()
            btn.setCursor(Qt.PointingHandCursor)
            hex_val = self.settings.get(key, DEFAULT_SETTINGS[key])
            btn.setStyleSheet(_color_button_style(hex_val))
            btn.setToolTip(hex_val)
            btn.clicked.connect(lambda checked=False, k=key: self._pick_color(k))
            self._color_buttons[key] = btn
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addWidget(QLabel(label))
            row.addStretch()
            colors_lay.addRow(row)

        colors_group.setLayout(colors_lay)
        root.addWidget(colors_group)

        # --- Font ---
        font_group = QGroupBox("Font")
        font_lay = QFormLayout()

        self._font_family = QComboBox()
        self._font_family.addItems(
            ["Segoe UI", "Arial", "Courier New", "Georgia", "Times New Roman",
             "Verdana", "Consolas", "Tahoma"]
        )
        self._font_family.setCurrentText(
            self.settings.get("font_family", DEFAULT_SETTINGS["font_family"])
        )
        font_lay.addRow("Family:", self._font_family)

        font_size_lay = QHBoxLayout()
        self._font_size_slider = QSlider(Qt.Horizontal)
        self._font_size_slider.setRange(8, 16)
        self._font_size_slider.setValue(self.settings.get("font_size", DEFAULT_SETTINGS["font_size"]))
        self._font_size_label = QLabel(str(self._font_size_slider.value()))
        self._font_size_label.setFixedWidth(24)
        self._font_size_slider.valueChanged.connect(
            lambda v: self._font_size_label.setText(str(v))
        )
        font_size_lay.addWidget(self._font_size_slider)
        font_size_lay.addWidget(self._font_size_label)
        font_lay.addRow("Size:", font_size_lay)

        self._show_number = QCheckBox("Show percentage number")
        self._show_number.setChecked(self.settings.get("show_number", True))
        font_lay.addRow(self._show_number)

        self._show_badge = QCheckBox("Show mode badge (5h/7d)")
        self._show_badge.setChecked(self.settings.get("show_badge", True))
        font_lay.addRow(self._show_badge)

        font_group.setLayout(font_lay)
        root.addWidget(font_group)

        # --- Refresh Display ---
        refresh_group = QGroupBox("Refresh Display")
        refresh_lay = QFormLayout()

        self._current_session = QComboBox()
        self._current_session.addItems(["Time Until", "Date", "None"])
        self._current_session.setCurrentText(
            self.settings.get("current_session_display", DEFAULT_SETTINGS["current_session_display"])
        )
        refresh_lay.addRow("Current Session (5h):", self._current_session)

        self._weekly_session = QComboBox()
        self._weekly_session.addItems(["Time Until", "Date", "None"])
        self._weekly_session.setCurrentText(
            self.settings.get("weekly_session_display", DEFAULT_SETTINGS["weekly_session_display"])
        )
        refresh_lay.addRow("Weekly Session (7d):", self._weekly_session)

        refresh_group.setLayout(refresh_lay)
        root.addWidget(refresh_group)

        # --- Polling ---
        polling_group = QGroupBox("Polling")
        polling_lay = QFormLayout()

        self._poll_interval = QComboBox()
        self._poll_interval.addItems(["1", "2", "5", "10", "15", "30"])
        self._poll_interval.setCurrentText(
            str(self.settings.get("poll_interval_minutes", DEFAULT_SETTINGS["poll_interval_minutes"]))
        )
        polling_lay.addRow("Interval (minutes):", self._poll_interval)

        polling_group.setLayout(polling_lay)
        root.addWidget(polling_group)

        # --- Buttons ---
        btn_lay = QHBoxLayout()
        self._restore_btn = QPushButton("Restore Defaults")
        self._restore_btn.clicked.connect(self._restore_defaults)
        btn_lay.addWidget(self._restore_btn)
        btn_lay.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel)
        btn_lay.addWidget(self._cancel_btn)
        self._ok_btn = QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._ok)
        btn_lay.addWidget(self._ok_btn)
        root.addLayout(btn_lay)

    # -- Live preview ----------------------------------------------------------

    def _connect_live_signals(self):
        self._radius_slider.valueChanged.connect(lambda _: self._emit_live())
        self._font_family.currentTextChanged.connect(lambda _: self._emit_live())
        self._font_size_slider.valueChanged.connect(lambda _: self._emit_live())
        self._show_number.stateChanged.connect(lambda _: self._emit_live())
        self._show_badge.stateChanged.connect(lambda _: self._emit_live())
        self._current_session.currentTextChanged.connect(lambda _: self._emit_live())
        self._weekly_session.currentTextChanged.connect(lambda _: self._emit_live())
        self._poll_interval.currentTextChanged.connect(lambda _: self._emit_live())

    def _collect(self) -> dict:
        """Read all widget values into a settings dict."""
        s = deepcopy(self.settings)
        s["radius"] = self._radius_slider.value()
        s["font_family"] = self._font_family.currentText()
        s["font_size"] = self._font_size_slider.value()
        s["show_number"] = self._show_number.isChecked()
        s["show_badge"] = self._show_badge.isChecked()
        s["current_session_display"] = self._current_session.currentText()
        s["weekly_session_display"] = self._weekly_session.currentText()
        s["poll_interval_minutes"] = int(self._poll_interval.currentText())
        # Color keys are updated directly in self.settings via _pick_color
        return s

    def _emit_live(self):
        self.settings = self._collect()
        self.settings_changed.emit(self.settings)

    # -- Color picker ----------------------------------------------------------

    def _pick_color(self, key: str):
        cur = QColor(self.settings.get(key, DEFAULT_SETTINGS[key]))
        color = QColorDialog.getColor(cur, self, f"Pick {key}")
        if color.isValid():
            self.settings[key] = color.name()
            self._color_buttons[key].setStyleSheet(_color_button_style(color.name()))
            self._color_buttons[key].setToolTip(color.name())
            self._emit_live()

    # -- Button handlers -------------------------------------------------------

    def _ok(self):
        self.settings = self._collect()
        self._save(self.settings)
        self.settings_changed.emit(self.settings)
        self.accept()

    def _cancel(self):
        # Revert to settings from when the dialog was opened
        self.settings_changed.emit(self._open_settings)
        self.reject()

    def _restore_defaults(self):
        defaults = deepcopy(DEFAULT_SETTINGS)
        self.settings = defaults

        # Update all widgets to match defaults
        self._radius_slider.blockSignals(True)
        self._radius_slider.setValue(defaults["radius"])
        self._radius_label.setText(str(defaults["radius"]))
        self._radius_slider.blockSignals(False)

        self._font_family.blockSignals(True)
        self._font_family.setCurrentText(defaults["font_family"])
        self._font_family.blockSignals(False)

        self._font_size_slider.blockSignals(True)
        self._font_size_slider.setValue(defaults["font_size"])
        self._font_size_label.setText(str(defaults["font_size"]))
        self._font_size_slider.blockSignals(False)

        self._show_number.blockSignals(True)
        self._show_number.setChecked(defaults["show_number"])
        self._show_number.blockSignals(False)

        self._show_badge.blockSignals(True)
        self._show_badge.setChecked(defaults["show_badge"])
        self._show_badge.blockSignals(False)

        self._current_session.blockSignals(True)
        self._current_session.setCurrentText(defaults["current_session_display"])
        self._current_session.blockSignals(False)

        self._weekly_session.blockSignals(True)
        self._weekly_session.setCurrentText(defaults["weekly_session_display"])
        self._weekly_session.blockSignals(False)

        self._poll_interval.blockSignals(True)
        self._poll_interval.setCurrentText(str(defaults["poll_interval_minutes"]))
        self._poll_interval.blockSignals(False)

        for key, btn in self._color_buttons.items():
            hex_val = defaults.get(key, "#FFFFFF")
            btn.setStyleSheet(_color_button_style(hex_val))
            btn.setToolTip(hex_val)

        self.settings_changed.emit(self.settings)

    # -- Persistence -----------------------------------------------------------

    @staticmethod
    def _save(settings: dict):
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)

    @staticmethod
    def load_settings() -> dict:
        if not SETTINGS_PATH.exists():
            return deepcopy(DEFAULT_SETTINGS)
        with open(SETTINGS_PATH, "r") as f:
            try:
                settings = json.load(f)
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in settings:
                        settings[key] = value
                return settings
            except json.JSONDecodeError:
                return deepcopy(DEFAULT_SETTINGS)
