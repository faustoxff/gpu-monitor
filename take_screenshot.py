"""Run the app for 3 seconds, grab the window, save it, then exit."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QScreen

from detector import detect_gpus
from ui.main_window import MainWindow

OUTPUT = os.path.join(os.path.dirname(__file__), "screenshot.png")

app = QApplication(sys.argv)
app.setStyle("Fusion")

DARK_STYLE = """
QWidget { font-family: "Inter", "Segoe UI", "Ubuntu", sans-serif; }
QScrollArea { border: none; }
QToolTip {
    background-color: #1e293b; color: #f1f5f9;
    border: 1px solid #475569; border-radius: 4px; padding: 4px 8px; font-size: 11px;
}
"""
app.setStyleSheet(DARK_STYLE)

backends = detect_gpus()
window = MainWindow(backends)
window.resize(900, 700)
window.show()

# Let the app paint 2 ticks so the graph has some data
def save_and_quit():
    # QWidget.grab() captures the widget's own rendered content regardless
    # of whether it is composited on screen — more reliable than grabWindow.
    pixmap = window.grab()
    ok = pixmap.save(OUTPUT, "PNG")
    if ok:
        print(f"Screenshot saved to {OUTPUT}  ({pixmap.width()}x{pixmap.height()})")
    else:
        print(f"ERROR: pixmap.save() failed. Pixmap size: {pixmap.size()}", file=sys.stderr)
    app.quit()

QTimer.singleShot(2500, save_and_quit)
sys.exit(app.exec())
