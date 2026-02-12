import json
from pathlib import Path
import sys
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QVBoxLayout,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

SETTINGS_PATH = Path.home() / ".claude" / "meter-settings.json"
DEFAULT_SETTINGS = {
    "radius": 10,
    "font_color": "#FFFFFF",
    "font_family": "Arial",
    "font_size": 12,
    "current_session_display": "Time Until",
    "weekly_session_display": "Date",
}


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")

        self.settings = self.load_settings()

        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()

        # Radius
        self.radius_input = QComboBox()
        self.radius_input.addItems([str(i) for i in range(5, 21)])
        self.radius_input.setCurrentText(str(self.settings["radius"]))
        self.form_layout.addRow("Indicator Radius:", self.radius_input)

        # Colors
        self.color_layout = QHBoxLayout()
        self.font_color_button = QPushButton("Font Color")
        self.font_color_button.clicked.connect(self.open_font_color_dialog)
        self.color_layout.addWidget(self.font_color_button)
        self.form_layout.addRow("Colors:", self.color_layout)

        # Font
        self.font_layout = QHBoxLayout()
        self.font_family_input = QComboBox()
        self.font_family_input.addItems(
            ["Arial", "Courier New", "Georgia", "Times New Roman", "Verdana"]
        )
        self.font_family_input.setCurrentText(self.settings["font_family"])
        self.font_layout.addWidget(self.font_family_input)
        self.font_size_input = QComboBox()
        self.font_size_input.addItems([str(i) for i in range(8, 17)])
        self.font_size_input.setCurrentText(str(self.settings["font_size"]))
        self.font_layout.addWidget(self.font_size_input)
        self.form_layout.addRow("Font:", self.font_layout)

        # Refresh Display
        self.refresh_display_group = QGroupBox("Refresh Display")
        self.refresh_display_layout = QFormLayout()
        self.current_session_display = QComboBox()
        self.current_session_display.addItems(["Time Until", "Date"])
        self.current_session_display.setCurrentText(
            self.settings["current_session_display"]
        )
        self.refresh_display_layout.addRow(
            "Current Session:", self.current_session_display
        )
        self.weekly_session_display = QComboBox()
        self.weekly_session_display.addItems(["Time Until", "Date"])
        self.weekly_session_display.setCurrentText(
            self.settings["weekly_session_display"]
        )
        self.refresh_display_layout.addRow("Weekly Session:", self.weekly_session_display)
        self.refresh_display_group.setLayout(self.refresh_display_layout)
        self.form_layout.addRow(self.refresh_display_group)

        self.layout.addLayout(self.form_layout)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.save_settings)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def load_settings(self):
        if not SETTINGS_PATH.exists():
            return DEFAULT_SETTINGS
        with open(SETTINGS_PATH, "r") as f:
            try:
                settings = json.load(f)
                # Ensure all keys are present
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in settings:
                        settings[key] = value
                return settings
            except json.JSONDecodeError:
                return DEFAULT_SETTINGS

    def save_settings(self):
        self.settings["radius"] = int(self.radius_input.currentText())
        self.settings["font_family"] = self.font_family_input.currentText()
        self.settings["font_size"] = int(self.font_size_input.currentText())
        self.settings["current_session_display"] = self.current_session_display.currentText()
        self.settings["weekly_session_display"] = self.weekly_session_display.currentText()

        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(self.settings, f, indent=2)
        self.accept()

    def open_font_color_dialog(self):
        color = QColorDialog.getColor(QColor(self.settings["font_color"]), self)
        if color.isValid():
            self.settings["font_color"] = color.name()
