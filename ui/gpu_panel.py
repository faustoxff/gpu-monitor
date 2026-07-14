"""Per-GPU panel widget.

Shows a header with vendor badge + GPU name, a metrics grid, and a
60-second history graph.  If get_stats() raises or returns corrupt data
the panel switches to an error state without taking down the rest of the
app.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from backends.base import GPUBackend, GPUStats
from ui.graph_widget import GraphWidget

# Vendor accent colours
_VENDOR_COLORS = {
    "AMD":    "#ef4444",   # red-500
    "NVIDIA": "#22c55e",   # green-500
    "Intel":  "#3b82f6",   # blue-500
}
_DEFAULT_VENDOR_COLOR = "#a855f7"  # purple-500

_COLOR_BG_PANEL  = "#1e293b"   # slate-800
_COLOR_BG_HEADER = "#0f172a"   # slate-950
_COLOR_TEXT      = "#f1f5f9"   # slate-100
_COLOR_MUTED     = "#94a3b8"   # slate-400
_COLOR_ERROR     = "#f87171"   # red-400
_COLOR_OK        = "#4ade80"   # green-400


class MetricRow(QWidget):
    """A single label + value pair in the metrics grid."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {_COLOR_MUTED}; font-size: 11px;")
        lbl.setFixedWidth(90)
        layout.addWidget(lbl)

        self._val = QLabel("—")
        self._val.setStyleSheet(f"color: {_COLOR_TEXT}; font-size: 12px; font-weight: bold;")
        layout.addWidget(self._val)

    def set_value(self, text: str, color: Optional[str] = None) -> None:
        self._val.setText(text)
        style = f"font-size: 12px; font-weight: bold; color: {color or _COLOR_TEXT};"
        self._val.setStyleSheet(style)

    def clear(self) -> None:
        self.set_value("—")


class GPUPanel(QFrame):
    """Card-style widget showing all metrics for one GPU."""

    def __init__(self, backend: GPUBackend, parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._vendor  = backend.get_vendor()
        self._error_state = False

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            f"""
            GPUPanel {{
                background-color: {_COLOR_BG_PANEL};
                border-radius: 10px;
                border: 1px solid #334155;
            }}
            """
        )

        self._build_ui()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        try:
            stats = self._backend.get_stats()
            self._apply_stats(stats)
            self._set_error(None)
        except Exception as exc:  # noqa: BLE001
            self._set_error(str(exc))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 10)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addSpacing(8)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 0, 14, 0)
        body_layout.setSpacing(4)

        self._status_label = QLabel()
        self._status_label.setStyleSheet(f"color: {_COLOR_OK}; font-size: 11px;")
        body_layout.addWidget(self._status_label)

        self._error_label = QLabel()
        self._error_label.setStyleSheet(f"color: {_COLOR_ERROR}; font-size: 11px;")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        body_layout.addWidget(self._error_label)

        body_layout.addSpacing(4)
        body_layout.addLayout(self._build_metrics_grid())
        body_layout.addSpacing(8)

        self._graph = GraphWidget()
        body_layout.addWidget(self._graph)

        root.addWidget(body)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setStyleSheet(
            f"background-color: {_COLOR_BG_HEADER}; border-radius: 10px 10px 0px 0px;"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 10, 14, 10)

        accent = _VENDOR_COLORS.get(self._vendor, _DEFAULT_VENDOR_COLOR)

        badge = QLabel(self._vendor)
        badge.setStyleSheet(
            f"""
            background-color: {accent};
            color: #0f172a;
            font-weight: bold;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            """
        )
        layout.addWidget(badge)
        layout.addSpacing(10)

        name_label = QLabel(self._backend.get_name())
        name_label.setStyleSheet(f"color: {_COLOR_TEXT}; font-size: 13px; font-weight: bold;")
        name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(name_label)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {_COLOR_OK}; font-size: 14px;")
        layout.addWidget(self._dot)

        return header

    def _build_metrics_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(2)

        self._m_temp   = MetricRow("Temperature")
        self._m_usage  = MetricRow("GPU Usage")
        self._m_vram   = MetricRow("VRAM")
        self._m_clock  = MetricRow("Core Clock")
        self._m_power  = MetricRow("Power Draw")

        rows = [self._m_temp, self._m_usage, self._m_vram, self._m_clock, self._m_power]
        col_size = (len(rows) + 1) // 2
        for i, row in enumerate(rows):
            grid.addWidget(row, i % col_size, i // col_size)

        return grid

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _apply_stats(self, s: GPUStats) -> None:
        # Temperature
        if s["temp_c"] is not None:
            temp = s["temp_c"]
            color = _temp_color(temp)
            self._m_temp.set_value(f"{temp:.1f} °C", color)
        else:
            self._m_temp.clear()

        # Usage
        if s["usage_pct"] is not None:
            pct = s["usage_pct"]
            self._m_usage.set_value(f"{pct:.1f} %", _usage_color(pct))
        else:
            self._m_usage.clear()

        # VRAM
        if s["vram_used_mb"] is not None and s["vram_total_mb"] is not None:
            used  = s["vram_used_mb"]
            total = s["vram_total_mb"]
            ratio = used / total if total else 0
            self._m_vram.set_value(
                f"{_fmt_mb(used)} / {_fmt_mb(total)}",
                _usage_color(ratio * 100),
            )
        elif s["vram_total_mb"] is not None:
            self._m_vram.set_value(f"? / {_fmt_mb(s['vram_total_mb'])}")
        else:
            self._m_vram.clear()

        # Clock
        if s["clock_mhz"] is not None:
            mhz = s["clock_mhz"]
            txt = f"{mhz / 1000:.2f} GHz" if mhz >= 1000 else f"{mhz:.0f} MHz"
            self._m_clock.set_value(txt)
        else:
            self._m_clock.clear()

        # Power
        if s["power_w"] is not None:
            self._m_power.set_value(f"{s['power_w']:.1f} W")
        else:
            self._m_power.clear()

        # Feed history graph
        self._graph.push(s["usage_pct"], s["temp_c"])

        self._status_label.setText("Live")
        self._status_label.show()

    def _set_error(self, msg: Optional[str]) -> None:
        if msg:
            self._error_state = True
            self._dot.setStyleSheet(f"color: {_COLOR_ERROR}; font-size: 14px;")
            self._error_label.setText(f"Error: {msg}")
            self._error_label.show()
            self._status_label.hide()
            self._graph.push(None, None)
        else:
            if self._error_state:
                self._dot.setStyleSheet(f"color: {_COLOR_OK}; font-size: 14px;")
                self._error_label.hide()
                self._error_state = False


# ------------------------------------------------------------------
# Colour helpers
# ------------------------------------------------------------------

def _temp_color(t: float) -> str:
    if t >= 90:
        return "#ef4444"   # red
    if t >= 75:
        return "#fb923c"   # orange
    if t >= 60:
        return "#facc15"   # yellow
    return "#4ade80"       # green

def _usage_color(pct: float) -> str:
    if pct >= 90:
        return "#ef4444"
    if pct >= 70:
        return "#fb923c"
    return "#4ade80"

def _fmt_mb(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.1f} GiB"
    return f"{mb:.0f} MiB"
