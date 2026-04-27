from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class LoudnessHistoryPlot(QWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._source_series: list[float] = []
        self._processed_series: list[float] = []
        self.setMinimumHeight(140)

    def set_series(self, source_series: list[float], processed_series: list[float]) -> None:
        self._source_series = list(source_series)
        self._processed_series = list(processed_series)
        self.update()

    def clear(self) -> None:
        self.set_series([], [])

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#171a1f"))

        bounds = self.rect().adjusted(12, 12, -12, -12)
        painter.setPen(QPen(QColor("#3f4854"), 1))
        painter.drawRoundedRect(bounds, 8, 8)
        painter.setPen(QColor("#c8d0da"))
        painter.drawText(bounds.adjusted(10, 6, -10, -6), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, self._title)

        plot_area = bounds.adjusted(10, 28, -10, -12)
        self._draw_grid(painter, plot_area)
        self._draw_series(painter, plot_area, self._source_series, QColor("#6f7a86"), 1.5)
        self._draw_series(painter, plot_area, self._processed_series, QColor("#49d17d"), 2.0)

    def _draw_grid(self, painter: QPainter, rect) -> None:
        painter.setPen(QPen(QColor("#26313c"), 1, Qt.PenStyle.DashLine))
        for ratio in (0.25, 0.5, 0.75):
            y = rect.top() + rect.height() * ratio
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))

    def _draw_series(self, painter: QPainter, rect, series: list[float], color: QColor, width: float) -> None:
        finite_values = [value for value in series if value != float("-inf")]
        if len(finite_values) < 2:
            return
        minimum = min(finite_values)
        maximum = max(finite_values)
        if maximum - minimum < 1e-6:
            minimum -= 1.0
            maximum += 1.0

        path = QPainterPath()
        for index, value in enumerate(series):
            if value == float("-inf"):
                continue
            x_ratio = index / max(1, len(series) - 1)
            y_ratio = (value - minimum) / (maximum - minimum)
            point = QPointF(rect.left() + rect.width() * x_ratio, rect.bottom() - rect.height() * y_ratio)
            if path.isEmpty():
                path.moveTo(point)
            else:
                path.lineTo(point)

        painter.setPen(QPen(color, width))
        painter.drawPath(path)
