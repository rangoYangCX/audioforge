from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class RtpcCurveEditor(QWidget):
    pointsChanged = Signal()
    pointPreviewChanged = Signal()
    selectionChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(188)
        self.setMouseTracking(True)
        self.setToolTip("拖动曲线点直接调整 RTPC。双击空白处新增点。")
        self._points: list[dict[str, object]] = []
        self._selected_index = -1
        self._dragging_index = -1
        self._drag_moved = False
        self._hover_index = -1
        self._last_pointer_pos: QPointF | None = None
        self._handle_radius = 6.0
        self._snap_enabled = False
        self._snap_input_step = 1.0
        self._snap_output_step = 1.0
        self._x_axis_range: tuple[float, float] | None = None
        self._y_axis_range: tuple[float, float] | None = None
        self.set_points(
            [
                {"input_value": 0.0, "output_value": 0.0, "interpolation": "Linear"},
                {"input_value": 100.0, "output_value": 100.0, "interpolation": "Linear"},
            ]
        )

    def points(self) -> list[dict[str, object]]:
        return [dict(point) for point in self._points]

    def set_points(self, points: list[dict[str, object]] | None) -> None:
        normalized = []
        for point in points or []:
            if not isinstance(point, dict):
                continue
            normalized.append(
                {
                    "input_value": float(point.get("input_value", 0.0)),
                    "output_value": float(point.get("output_value", 0.0)),
                    "interpolation": "Constant" if str(point.get("interpolation", "Linear")) == "Constant" else "Linear",
                }
            )
        if not normalized:
            normalized = [
                {"input_value": 0.0, "output_value": 0.0, "interpolation": "Linear"},
                {"input_value": 100.0, "output_value": 100.0, "interpolation": "Linear"},
            ]
        normalized.sort(key=lambda point: float(point["input_value"]))
        self._points = normalized
        self._selected_index = min(max(self._selected_index, 0), len(self._points) - 1) if self._points else -1
        if self._selected_index < 0 and self._points:
            self._selected_index = 0
        self.update()
        self.selectionChanged.emit(self._selected_index)

    def selected_index(self) -> int:
        return self._selected_index

    def selected_interpolation(self) -> str:
        if 0 <= self._selected_index < len(self._points):
            return str(self._points[self._selected_index].get("interpolation", "Linear"))
        return "Linear"

    def selected_point(self) -> dict[str, object] | None:
        if 0 <= self._selected_index < len(self._points):
            return dict(self._points[self._selected_index])
        return None

    def set_snap_settings(self, enabled: bool, input_step: float, output_step: float) -> None:
        self._snap_enabled = bool(enabled)
        self._snap_input_step = max(0.01, float(input_step))
        self._snap_output_step = max(0.01, float(output_step))

    def set_axis_ranges(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        self._x_axis_range = self._normalize_axis_range(x_min, x_max)
        self._y_axis_range = self._normalize_axis_range(y_min, y_max)
        self.update()

    def update_selected_point(self, *, input_value: float | None = None, output_value: float | None = None) -> None:
        if not (0 <= self._selected_index < len(self._points)):
            return
        point = dict(self._points[self._selected_index])
        if input_value is not None:
            point["input_value"] = float(input_value)
        if output_value is not None:
            point["output_value"] = float(output_value)
        self._points[self._selected_index] = self._constrain_point(self._selected_index, point)
        self.update()
        self.pointPreviewChanged.emit()
        self.pointsChanged.emit()

    def set_selected_interpolation(self, interpolation: str) -> None:
        if not (0 <= self._selected_index < len(self._points)):
            return
        normalized = "Constant" if interpolation == "Constant" else "Linear"
        if self._points[self._selected_index].get("interpolation") == normalized:
            return
        self._points[self._selected_index]["interpolation"] = normalized
        self.update()
        self.pointPreviewChanged.emit()
        self.pointsChanged.emit()

    def append_point(self) -> None:
        if not self._points:
            self.set_points(None)
            self.pointsChanged.emit()
            return
        if 0 <= self._selected_index < len(self._points) - 1:
            left_point = self._points[self._selected_index]
            right_point = self._points[self._selected_index + 1]
            new_point = {
                "input_value": (float(left_point["input_value"]) + float(right_point["input_value"])) / 2.0,
                "output_value": (float(left_point["output_value"]) + float(right_point["output_value"])) / 2.0,
                "interpolation": "Linear",
            }
            insert_index = self._selected_index + 1
        else:
            last_point = self._points[-1]
            step = max(10.0, self._x_range()[1] - self._x_range()[0]) / max(1, len(self._points))
            new_point = {
                "input_value": float(last_point["input_value"]) + step,
                "output_value": float(last_point["output_value"]),
                "interpolation": "Linear",
            }
            insert_index = len(self._points)
        self._points.insert(insert_index, new_point)
        self._selected_index = insert_index
        self.update()
        self.selectionChanged.emit(self._selected_index)
        self.pointPreviewChanged.emit()
        self.pointsChanged.emit()

    def remove_selected_point(self) -> None:
        if not (0 <= self._selected_index < len(self._points)):
            return
        del self._points[self._selected_index]
        if len(self._points) < 2:
            self.set_points(None)
        else:
            self._selected_index = min(self._selected_index, len(self._points) - 1)
            self.update()
            self.selectionChanged.emit(self._selected_index)
        self.pointPreviewChanged.emit()
        self.pointsChanged.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#10151d"))
        rect = self._plot_rect()
        painter.fillRect(rect, QColor("#151c25"))
        painter.setPen(QPen(QColor("#1f2833"), 1))
        for ratio in (0.125, 0.375, 0.625, 0.875):
            x = rect.left() + rect.width() * ratio
            y = rect.top() + rect.height() * ratio
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(QPen(QColor("#2d3947"), 1))
        for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = rect.left() + rect.width() * ratio
            y = rect.top() + rect.height() * ratio
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(QPen(QColor("#6e7f92"), 1))
        painter.drawRect(rect)
        painter.setPen(QColor("#a9b6c7"))
        x_min, x_max = self._x_range()
        y_min, y_max = self._y_range()
        for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = rect.left() + rect.width() * ratio
            y = rect.bottom() - rect.height() * ratio
            x_value = x_min + (x_max - x_min) * ratio
            y_value = y_min + (y_max - y_min) * ratio
            painter.drawText(QRectF(x - 28.0, rect.bottom() + 6.0, 56.0, 18.0), Qt.AlignmentFlag.AlignCenter, f"{x_value:.1f}")
            painter.drawText(QRectF(4.0, y - 9.0, 46.0, 18.0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{y_value:.1f}")
        painter.drawText(QRectF(rect.left(), rect.bottom() + 24.0, rect.width(), 18.0), Qt.AlignmentFlag.AlignCenter, "输入值")
        painter.save()
        painter.translate(16.0, rect.center().y())
        painter.rotate(-90.0)
        painter.drawText(QRectF(-60.0, -22.0, 120.0, 18.0), Qt.AlignmentFlag.AlignCenter, "输出值")
        painter.restore()
        if self._snap_enabled:
            painter.setPen(QColor("#89a9c8"))
            painter.drawText(
                QRectF(rect.right() - 168.0, rect.top() + 6.0, 160.0, 18.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"吸附 X {self._snap_input_step:.2f} | Y {self._snap_output_step:.2f}",
            )
        if not self._points:
            return
        path = QPainterPath()
        first_point = self._point_to_pos(0)
        path.moveTo(first_point)
        for index in range(len(self._points) - 1):
            current = self._points[index]
            next_point = self._points[index + 1]
            current_pos = self._point_to_pos(index)
            next_pos = self._point_to_pos(index + 1)
            if str(current.get("interpolation", "Linear")) == "Constant":
                path.lineTo(QPointF(next_pos.x(), current_pos.y()))
                path.lineTo(next_pos)
            else:
                path.lineTo(next_pos)
        painter.setPen(QPen(QColor("#4ec3ff"), 2.0))
        painter.drawPath(path)
        for index, point in enumerate(self._points):
            pos = self._point_to_pos(index)
            selected = index == self._selected_index
            hovered = index == self._hover_index
            dragging = index == self._dragging_index
            if selected:
                painter.setPen(QPen(QColor("#324758"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(pos.x(), rect.top()), QPointF(pos.x(), rect.bottom()))
                painter.drawLine(QPointF(rect.left(), pos.y()), QPointF(rect.right(), pos.y()))
            if hovered or dragging:
                painter.setBrush(QColor(78, 195, 255, 48 if dragging else 28))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(pos, self._handle_radius + 6.0, self._handle_radius + 6.0)
            painter.setBrush(QColor("#ffbe55") if selected else QColor("#e6edf7"))
            painter.setPen(QPen(QColor("#0c1118"), 1.5))
            painter.drawEllipse(pos, self._handle_radius + (1.0 if selected else 0.0), self._handle_radius + (1.0 if selected else 0.0))
            if selected or dragging:
                self._draw_point_badge(
                    painter,
                    pos,
                    f"{float(point['input_value']):.1f} -> {float(point['output_value']):.1f}",
                    dragging=dragging,
                )

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._last_pointer_pos = event.position()
        index = self._point_at(event.position())
        if index >= 0:
            self._selected_index = index
            self._dragging_index = index
            self._drag_moved = False
            self._hover_index = index
            self.selectionChanged.emit(index)
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._last_pointer_pos = event.position()
        if self._dragging_index < 0 or self._dragging_index >= len(self._points):
            hover_index = self._point_at(event.position())
            if hover_index != self._hover_index:
                self._hover_index = hover_index
                self.update()
            super().mouseMoveEvent(event)
            return
        point = self._pos_to_point(event.position())
        previous = dict(self._points[self._dragging_index])
        self._points[self._dragging_index] = self._constrain_point(self._dragging_index, point)
        self._drag_moved = self._drag_moved or previous != self._points[self._dragging_index]
        self.update()
        self.pointPreviewChanged.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        moved = self._dragging_index >= 0 and self._drag_moved
        self._dragging_index = -1
        self._drag_moved = False
        self._hover_index = self._point_at(event.position())
        if moved:
            self.pointPreviewChanged.emit()
            self.pointsChanged.emit()
        self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._plot_rect().contains(event.position()):
            point = self._pos_to_point(event.position())
            insert_index = len(self._points)
            for index, existing in enumerate(self._points):
                if point["input_value"] < float(existing["input_value"]):
                    insert_index = index
                    break
            self._points.insert(insert_index, point)
            self._selected_index = insert_index
            self.update()
            self.selectionChanged.emit(insert_index)
            self.pointPreviewChanged.emit()
            self.pointsChanged.emit()
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_index = -1
        self._last_pointer_pos = None
        self.update()
        super().leaveEvent(event)

    def _plot_rect(self) -> QRectF:
        return QRectF(54.0, 18.0, max(120.0, self.width() - 74.0), max(120.0, self.height() - 66.0))

    def _x_range(self) -> tuple[float, float]:
        if self._x_axis_range is not None:
            return self._x_axis_range
        values = [float(point["input_value"]) for point in self._points] or [0.0, 100.0]
        minimum = min(values)
        maximum = max(values)
        if abs(maximum - minimum) < 0.001:
            maximum = minimum + 1.0
        padding = max(1.0, (maximum - minimum) * 0.08)
        return minimum - padding, maximum + padding

    def _y_range(self) -> tuple[float, float]:
        if self._y_axis_range is not None:
            return self._y_axis_range
        values = [float(point["output_value"]) for point in self._points] or [0.0, 100.0]
        minimum = min(values)
        maximum = max(values)
        if abs(maximum - minimum) < 0.001:
            maximum = minimum + 1.0
        padding = max(1.0, (maximum - minimum) * 0.1)
        return minimum - padding, maximum + padding

    def _point_to_pos(self, index: int) -> QPointF:
        rect = self._plot_rect()
        x_min, x_max = self._x_range()
        y_min, y_max = self._y_range()
        point = self._points[index]
        x_ratio = (float(point["input_value"]) - x_min) / max(0.001, x_max - x_min)
        y_ratio = (float(point["output_value"]) - y_min) / max(0.001, y_max - y_min)
        return QPointF(rect.left() + rect.width() * x_ratio, rect.bottom() - rect.height() * y_ratio)

    def _pos_to_point(self, position: QPointF) -> dict[str, object]:
        rect = self._plot_rect()
        bounded_x = max(rect.left(), min(rect.right(), position.x()))
        bounded_y = max(rect.top(), min(rect.bottom(), position.y()))
        x_min, x_max = self._x_range()
        y_min, y_max = self._y_range()
        x_ratio = 0.0 if rect.width() <= 0 else (bounded_x - rect.left()) / rect.width()
        y_ratio = 0.0 if rect.height() <= 0 else (rect.bottom() - bounded_y) / rect.height()
        input_value = x_min + (x_max - x_min) * x_ratio
        output_value = y_min + (y_max - y_min) * y_ratio
        if self._snap_enabled:
            input_value = self._snap_value(input_value, self._snap_input_step)
            output_value = self._snap_value(output_value, self._snap_output_step)
        return {
            "input_value": input_value,
            "output_value": output_value,
            "interpolation": "Linear",
        }

    def _point_at(self, position: QPointF) -> int:
        for index, _point in enumerate(self._points):
            point_pos = self._point_to_pos(index)
            if (point_pos - position).manhattanLength() <= self._handle_radius * 2.5:
                return index
        return -1

    def _constrain_point(self, index: int, point: dict[str, object]) -> dict[str, object]:
        constrained = dict(point)
        input_value = float(constrained.get("input_value", 0.0))
        output_value = float(constrained.get("output_value", 0.0))
        if self._snap_enabled:
            input_value = self._snap_value(input_value, self._snap_input_step)
            output_value = self._snap_value(output_value, self._snap_output_step)
        if index > 0:
            input_value = max(float(self._points[index - 1]["input_value"]) + 0.01, input_value)
        if index < len(self._points) - 1:
            input_value = min(float(self._points[index + 1]["input_value"]) - 0.01, input_value)
        constrained["input_value"] = input_value
        constrained["output_value"] = output_value
        constrained["interpolation"] = "Constant" if str(constrained.get("interpolation", "Linear")) == "Constant" else "Linear"
        return constrained

    def _snap_value(self, value: float, step: float) -> float:
        return round(value / step) * step if step > 0 else value

    def _draw_point_badge(self, painter: QPainter, pos: QPointF, text: str, *, dragging: bool) -> None:
        badge_rect = QRectF(pos.x() + 10.0, pos.y() - 24.0, 138.0, 20.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(14, 21, 31, 232 if dragging else 214))
        painter.drawRoundedRect(badge_rect, 8.0, 8.0)
        painter.setPen(QColor("#ffcf7d") if dragging else QColor("#f2f7ff"))
        painter.drawText(badge_rect.adjusted(8.0, 0.0, -8.0, 0.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _normalize_axis_range(self, minimum: float, maximum: float) -> tuple[float, float]:
        minimum_value = float(minimum)
        maximum_value = float(maximum)
        if maximum_value < minimum_value:
            minimum_value, maximum_value = maximum_value, minimum_value
        if abs(maximum_value - minimum_value) < 0.001:
            maximum_value = minimum_value + 1.0
        return minimum_value, maximum_value
