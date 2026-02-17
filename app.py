"""
Claude Code Usage Meter — Native floating overlay widget.
Reads OAuth credentials from ~/.claude/.credentials.json, queries the
Anthropic usage API, and renders a transparent floating circle that shows
the current rate-limit utilization.
"""

import sys

from PySide6.QtWidgets import QApplication

from meter_widget import MeterWidget
from tray import setup_tray


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    meter = MeterWidget()
    meter.show()

    tray = setup_tray(app, meter)
    meter._tray = tray

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
