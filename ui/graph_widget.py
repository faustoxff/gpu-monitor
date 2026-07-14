"""60-second history graph drawn with QPainter.

Renders two series on the same canvas:
  • GPU usage %  (green,  left Y-axis  0–100)
  • Temperature °C (orange, right Y-axis 0–120)

None values are rendered as gaps in the line.
"""

from collections import deque
from typing import Deque, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

_MAX_SAMPLES = 60

_COLOR_USAGE = QColor("#4ade80")   # green-400
_COLOR_TEMP  = QColor("#fb923c")   # orange-400
_COLOR_GRID  = QColor("#334155")   # slate-700
_COLOR_BG    = QColor("#0f172a")   # slate-950
_COLOR_LABEL = QColor("#94a3b8")   # slate-400

_TEMP_MAX = 120.0   # °C ceiling for the chart
_USAGE_MAX = 100.0


class GraphWidget(QWidget):
    """Rolling 60-second dual-series history chart."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._usage: Deque[Optional[float]] = deque(maxlen=_MAX_SAMPLES)
        self._temp:  Deque[Optional[float]] = deque(maxlen=_MAX_SAMPLES)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("Green: GPU usage %   Orange: Temperature °C")

    def push(self, usage_pct: Optional[float], temp_c: Optional[float]) -> None:
        self._usage.append(usage_pct)
        self._temp.append(temp_c)
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        pad_l, pad_r, pad_t, pad_b = 38, 38, 8, 20
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        # Background
        painter.fillRect(0, 0, w, h, _COLOR_BG)

        # Grid lines (5 horizontal)
        pen = QPen(_COLOR_GRID)
        pen.setWidth(1)
        pen.setStyle(Qt.DotLine)
        painter.setPen(pen)
        for i in range(5 + 1):
            y = pad_t + int(i * plot_h / 5)
            painter.drawLine(pad_l, y, pad_l + plot_w, y)

        # Axis labels
        font = QFont("Monospace", 7)
        painter.setFont(font)
        painter.setPen(_COLOR_LABEL)

        # Left axis: usage %
        for i in range(5 + 1):
            pct = int((1 - i / 5) * 100)
            y = pad_t + int(i * plot_h / 5)
            painter.drawText(0, y - 6, pad_l - 4, 14, Qt.AlignRight | Qt.AlignVCenter, f"{pct}%")

        # Right axis: temperature °C
        for i in range(5 + 1):
            temp = int((1 - i / 5) * _TEMP_MAX)
            y = pad_t + int(i * plot_h / 5)
            painter.drawText(pad_l + plot_w + 4, y - 6, pad_r - 4, 14, Qt.AlignLeft | Qt.AlignVCenter, f"{temp}°")

        # Clip to plot area
        painter.setClipRect(pad_l, pad_t, plot_w, plot_h)

        self._draw_series(painter, self._usage, _USAGE_MAX, _COLOR_USAGE, pad_l, pad_t, plot_w, plot_h)
        self._draw_series(painter, self._temp,  _TEMP_MAX,  _COLOR_TEMP,  pad_l, pad_t, plot_w, plot_h)

        painter.setClipping(False)

        # Legend
        lx = pad_l + 4
        ly = pad_t + 4
        for color, label in ((_COLOR_USAGE, "Usage %"), (_COLOR_TEMP, "Temp °C")):
            pen2 = QPen(color, 2)
            painter.setPen(pen2)
            painter.drawLine(lx, ly + 5, lx + 16, ly + 5)
            painter.setPen(_COLOR_LABEL)
            painter.drawText(lx + 20, ly, 60, 12, Qt.AlignLeft | Qt.AlignVCenter, label)
            lx += 88

        painter.end()

    @staticmethod
    def _draw_series(
        painter: QPainter,
        data: Deque[Optional[float]],
        y_max: float,
        color: QColor,
        pad_l: int,
        pad_t: int,
        plot_w: int,
        plot_h: int,
    ) -> None:
        samples = list(data)
        n = len(samples)
        if n == 0:
            return

        pen = QPen(color, 1.5)
        painter.setPen(pen)

        path = QPainterPath()
        in_segment = False

        for i, val in enumerate(samples):
            if val is None:
                in_segment = False
                continue
            # x maps newest sample to right edge
            x = pad_l + (i / (_MAX_SAMPLES - 1)) * plot_w if _MAX_SAMPLES > 1 else pad_l + plot_w
            clamped = max(0.0, min(float(val), y_max))
            y = pad_t + plot_h - (clamped / y_max) * plot_h

            if not in_segment:
                path.moveTo(x, y)
                in_segment = True
            else:
                path.lineTo(x, y)

        painter.drawPath(path)
