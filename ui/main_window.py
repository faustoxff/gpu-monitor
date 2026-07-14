"""Main application window.

Lays out one GPUPanel per detected GPU inside a scrollable area, and
drives a 1-second QTimer that refreshes every panel in sequence.
"""

from typing import List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from backends.base import GPUBackend
from ui.gpu_panel import GPUPanel

_COLOR_BG = "#0f172a"   # slate-950
_COLOR_ACCENT = "#7c3aed"   # violet-700


class MainWindow(QMainWindow):
    def __init__(self, backends: List[GPUBackend]) -> None:
        super().__init__()
        self._backends = backends
        self._panels: List[GPUPanel] = []

        self.setWindowTitle("GPU Monitor")
        self.setMinimumWidth(760)
        self.resize(900, 700)

        self._build_ui()
        self._start_timer()

        # Populate immediately so the UI is never blank on launch.
        self._tick()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet(f"background-color: {_COLOR_BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(12)

        root.addWidget(self._build_title_bar())

        if not self._backends:
            root.addWidget(self._build_no_gpu_label())
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.verticalScrollBar().setStyleSheet(
            """
            QScrollBar:vertical { width: 8px; background: #1e293b; }
            QScrollBar::handle:vertical { background: #475569; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        panel_layout = QVBoxLayout(container)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(14)

        for backend in self._backends:
            panel = GPUPanel(backend)
            self._panels.append(panel)
            panel_layout.addWidget(panel)

        panel_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll)

        self._status = QStatusBar()
        self._status.setStyleSheet("color: #64748b; font-size: 11px; background: transparent;")
        self.setStatusBar(self._status)
        self._status.showMessage("Refreshing every 1 s")

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        icon = QLabel("⬛")
        icon.setStyleSheet(f"color: {_COLOR_ACCENT}; font-size: 20px;")
        layout.addWidget(icon)

        title = QLabel("GPU Monitor")
        title.setStyleSheet("color: #f1f5f9; font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        gpu_count = QLabel(f"  {len(self._backends)} GPU(s) detected")
        gpu_count.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(gpu_count)

        layout.addStretch()

        self._tick_label = QLabel("●")
        self._tick_label.setStyleSheet("color: #4ade80; font-size: 16px;")
        layout.addWidget(self._tick_label)

        return bar

    @staticmethod
    def _build_no_gpu_label() -> QLabel:
        lbl = QLabel(
            "No GPUs detected.\n\n"
            "Make sure the GPU drivers are loaded and that\n"
            "/sys/class/drm/ is accessible."
        )
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #94a3b8; font-size: 14px;")
        return lbl

    # ------------------------------------------------------------------
    # Refresh loop
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Heartbeat blink
        self._blink_state = True

    def _tick(self) -> None:
        for panel in self._panels:
            panel.refresh()

        # Blink the dot in the title bar
        self._blink_state = not self._blink_state
        if hasattr(self, "_tick_label"):
            self._tick_label.setStyleSheet(
                f"color: {'#4ade80' if self._blink_state else '#166534'}; font-size: 16px;"
            )
