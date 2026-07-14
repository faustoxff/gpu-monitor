#!/usr/bin/env python3
"""GPU Monitor — entry point."""

import sys
import os

# Ensure local packages are importable when running directly from this dir.
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication

from detector import detect_gpus
from ui.main_window import MainWindow

_DARK_STYLE = """
QWidget {
    font-family: "Inter", "Segoe UI", "Ubuntu", sans-serif;
}
QScrollArea {
    border: none;
}
QToolTip {
    background-color: #1e293b;
    color: #f1f5f9;
    border: 1px solid #475569;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}
"""


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GPU Monitor")
    app.setApplicationDisplayName("GPU Monitor")
    app.setStyle("Fusion")
    app.setStyleSheet(_DARK_STYLE)

    backends = detect_gpus()

    if not backends:
        print("Warning: no GPUs detected. The window will display an informational message.")

    window = MainWindow(backends)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
