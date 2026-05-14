from __future__ import annotations

from pathlib import Path

try:
    import numpy as np
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    np = None
    sf = None

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class ClipWaveformEditor(QWidget):
    selectionChanged = Signal(int, int, int, int)
    loopChanged = Signal(int, int)
    playheadChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(196)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("拖动左右边界设置裁剪范围，拖动内部手柄设置淡入与淡出。")
        self._source_path = ""
        self._duration_ms = 0
        self._trim_start_ms = 0
        self._trim_end_ms = 0
        self._fade_in_ms = 0
        self._fade_out_ms = 0
        self._loop_start_ms = 0
        self._loop_end_ms = 0
        self._playhead_ms = 0
        self._zoom_factor = 1.0
        self._view_start_ms = 0
        self._amplitudes: list[float] = []
        self._status_text = "选择片段后，可直接在这里编辑裁剪与淡入淡出。"
        self._drag_handle: str | None = None
        self._handle_hit_radius = 16.0

    def sizeHint(self) -> QSize:
        return QSize(520, 248)

    def minimumSizeHint(self) -> QSize:
        return QSize(320, 196)

    def clear(self) -> None:
        self._source_path = ""
        self._duration_ms = 0
        self._trim_start_ms = 0
        self._trim_end_ms = 0
        self._fade_in_ms = 0
        self._fade_out_ms = 0
        self._loop_start_ms = 0
        self._loop_end_ms = 0
        self._playhead_ms = 0
        self._zoom_factor = 1.0
        self._view_start_ms = 0
        self._amplitudes = []
        self._status_text = "选择片段后，可直接在这里编辑裁剪与淡入淡出。"
        self._drag_handle = None
        self.update()

    def set_clip(
        self,
        source_path: str,
        *,
        trim_start_ms: int = 0,
        trim_end_ms: int = 0,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
        loop_start_ms: int = 0,
        loop_end_ms: int = 0,
    ) -> None:
        reload_waveform = source_path != self._source_path
        self._source_path = source_path
        if reload_waveform:
            self._load_waveform(source_path)
            self.reset_view()
        self.set_selection(trim_start_ms, trim_end_ms, fade_in_ms, fade_out_ms, emit_signal=False)
        self.set_loop(loop_start_ms, loop_end_ms, emit_signal=False)
        self.set_playhead_ms(trim_start_ms, emit_signal=False)

    def set_selection(
        self,
        trim_start_ms: int,
        trim_end_ms: int,
        fade_in_ms: int,
        fade_out_ms: int,
        *,
        emit_signal: bool = False,
        preferred_handle: str | None = None,
    ) -> None:
        trim_start_ms, trim_end_ms, fade_in_ms, fade_out_ms = self._sanitize_values(
            trim_start_ms,
            trim_end_ms,
            fade_in_ms,
            fade_out_ms,
            preferred_handle=preferred_handle,
        )
        changed = (
            trim_start_ms != self._trim_start_ms
            or trim_end_ms != self._trim_end_ms
            or fade_in_ms != self._fade_in_ms
            or fade_out_ms != self._fade_out_ms
        )
        self._trim_start_ms = trim_start_ms
        self._trim_end_ms = trim_end_ms
        self._fade_in_ms = fade_in_ms
        self._fade_out_ms = fade_out_ms
        self._ensure_range_visible(trim_start_ms, self._effective_trim_end_ms())
        self.update()
        if emit_signal and changed:
            self.selectionChanged.emit(trim_start_ms, trim_end_ms, fade_in_ms, fade_out_ms)

    def duration_ms(self) -> int:
        return self._duration_ms

    def set_loop(self, loop_start_ms: int, loop_end_ms: int, *, emit_signal: bool = True) -> None:
        loop_start_ms, loop_end_ms = self._sanitize_loop(loop_start_ms, loop_end_ms)
        changed = loop_start_ms != self._loop_start_ms or loop_end_ms != self._loop_end_ms
        self._loop_start_ms = loop_start_ms
        self._loop_end_ms = loop_end_ms
        if loop_end_ms > loop_start_ms:
            self._ensure_range_visible(loop_start_ms, loop_end_ms)
        self.update()
        if emit_signal and changed:
            self.loopChanged.emit(loop_start_ms, loop_end_ms)

    def playhead_ms(self) -> int:
        return self._playhead_ms

    def set_playhead_ms(self, value_ms: int, *, emit_signal: bool = True) -> None:
        if self._duration_ms > 0:
            value_ms = max(0, min(self._duration_ms, value_ms))
        else:
            value_ms = max(0, value_ms)
        changed = value_ms != self._playhead_ms
        self._playhead_ms = value_ms
        self._ensure_range_visible(value_ms, value_ms)
        self.update()
        if emit_signal and changed:
            self.playheadChanged.emit(value_ms)

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom_factor * 1.5)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom_factor / 1.5)

    def reset_view(self) -> None:
        self._zoom_factor = 1.0
        self._view_start_ms = 0
        self.update()

    def frame_selection(self) -> None:
        if self._duration_ms <= 0:
            return
        selection_start = self._trim_start_ms
        selection_end = self._effective_trim_end_ms()
        selection_length = max(1, selection_end - selection_start)
        desired_visible = min(self._duration_ms, max(selection_length * 1.35, 60))
        self._zoom_factor = max(1.0, min(64.0, self._duration_ms / desired_visible))
        centered_start = int(round(selection_start - (desired_visible - selection_length) / 2.0))
        self._view_start_ms = self._clamp_view_start(centered_start)
        self.update()

    def _load_waveform(self, source_path: str) -> None:
        self._amplitudes = []
        self._duration_ms = 0
        if not source_path:
            self._status_text = "当前片段还没有源文件。"
            self.update()
            return
        if sf is None or np is None:
            self._status_text = "soundfile 或 numpy 不可用，无法显示波形。"
            self.update()
            return
        source = Path(source_path)
        if not source.exists():
            self._status_text = f"源文件不存在：{source.name}"
            self.update()
            return
        try:
            info = sf.info(str(source))
            if info.samplerate > 0:
                self._duration_ms = max(1, int(round(info.frames * 1000.0 / info.samplerate)))
            audio_data, _ = sf.read(str(source), always_2d=True)
        except Exception:
            self._status_text = "波形读取失败，请检查源文件格式。"
            self.update()
            return
        if audio_data.size == 0:
            self._status_text = "音频文件为空，无法绘制波形。"
            self.update()
            return
        mono = np.mean(np.abs(audio_data.astype(np.float32, copy=False)), axis=1)
        target_bins = 512
        if mono.shape[0] > target_bins:
            bin_size = int(np.ceil(mono.shape[0] / target_bins))
            padded_length = bin_size * target_bins
            if padded_length != mono.shape[0]:
                mono = np.pad(mono, (0, padded_length - mono.shape[0]), mode="constant")
            mono = mono.reshape(target_bins, bin_size).max(axis=1)
        peak = float(mono.max()) if mono.size else 0.0
        if peak > 0.0:
            mono = mono / peak
        self._amplitudes = [float(value) for value in mono.tolist()]
        self._status_text = f"{source.name} | {self._duration_ms} ms"
        self.update()

    def _timeline_rect(self) -> QRectF:
        return QRectF(14.0, 32.0, max(80.0, self.width() - 28.0), max(84.0, self.height() - 52.0))

    def _visible_duration_ms(self) -> int:
        if self._duration_ms <= 0:
            return 1
        return max(1, int(round(self._duration_ms / max(1.0, self._zoom_factor))))

    def _view_end_ms(self) -> int:
        return min(self._duration_ms, self._view_start_ms + self._visible_duration_ms())

    def _effective_trim_end_ms(self) -> int:
        if self._duration_ms <= 0:
            return max(self._trim_start_ms, self._trim_end_ms)
        if self._trim_end_ms <= 0:
            return self._duration_ms
        return min(self._duration_ms, self._trim_end_ms)

    def _effective_loop_end_ms(self) -> int:
        if self._duration_ms <= 0:
            return max(self._loop_start_ms, self._loop_end_ms)
        if self._loop_end_ms <= 0:
            return 0
        return min(self._duration_ms, self._loop_end_ms)

    def _ms_to_x(self, value_ms: int, rect: QRectF) -> float:
        if self._duration_ms <= 0:
            return rect.left()
        visible_duration = max(1, self._visible_duration_ms())
        ratio = max(0.0, min(1.0, (value_ms - self._view_start_ms) / visible_duration))
        return rect.left() + ratio * rect.width()

    def _x_to_ms(self, x: float, rect: QRectF) -> int:
        if rect.width() <= 0 or self._duration_ms <= 0:
            return 0
        ratio = (x - rect.left()) / rect.width()
        ratio = max(0.0, min(1.0, ratio))
        return int(round(self._view_start_ms + self._visible_duration_ms() * ratio))

    def _clamp_view_start(self, proposed_start_ms: int) -> int:
        if self._duration_ms <= 0:
            return 0
        maximum_start = max(0, self._duration_ms - self._visible_duration_ms())
        return max(0, min(maximum_start, proposed_start_ms))

    def _ensure_range_visible(self, start_ms: int, end_ms: int) -> None:
        if self._duration_ms <= 0:
            return
        visible_duration = self._visible_duration_ms()
        if start_ms < self._view_start_ms:
            self._view_start_ms = self._clamp_view_start(start_ms)
        elif end_ms > self._view_start_ms + visible_duration:
            self._view_start_ms = self._clamp_view_start(end_ms - visible_duration)

    def _set_zoom(self, new_zoom: float, *, anchor_ms: int | None = None, anchor_ratio: float = 0.5) -> None:
        if self._duration_ms <= 0:
            return
        clamped_zoom = max(1.0, min(64.0, new_zoom))
        if abs(clamped_zoom - self._zoom_factor) < 0.001:
            return
        if anchor_ms is None:
            anchor_ms = self._playhead_ms
        self._zoom_factor = clamped_zoom
        new_visible = self._visible_duration_ms()
        centered_start = int(round(anchor_ms - new_visible * anchor_ratio))
        self._view_start_ms = self._clamp_view_start(centered_start)
        self.update()

    def _ruler_step_ms(self) -> int:
        visible_duration = self._visible_duration_ms()
        raw_step = max(10, visible_duration // 6)
        candidates = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000]
        for candidate in candidates:
            if raw_step <= candidate:
                return candidate
        return candidates[-1]

    def _format_time_ms(self, value_ms: int) -> str:
        if value_ms >= 1000:
            return f"{value_ms / 1000.0:.2f}s"
        return f"{value_ms}ms"

    def _sanitize_values(
        self,
        trim_start_ms: int,
        trim_end_ms: int,
        fade_in_ms: int,
        fade_out_ms: int,
        *,
        preferred_handle: str | None = None,
    ) -> tuple[int, int, int, int]:
        duration = max(0, self._duration_ms)
        if duration <= 0:
            return max(0, trim_start_ms), max(0, trim_end_ms), max(0, fade_in_ms), max(0, fade_out_ms)
        trim_start_ms = max(0, min(duration, trim_start_ms))
        effective_end = duration if trim_end_ms <= 0 else max(0, min(duration, trim_end_ms))
        if effective_end <= trim_start_ms:
            effective_end = min(duration, trim_start_ms + 1)
            trim_start_ms = max(0, effective_end - 1)
        selection_length = max(1, effective_end - trim_start_ms)
        fade_in_ms = max(0, min(selection_length, fade_in_ms))
        fade_out_ms = max(0, min(selection_length, fade_out_ms))
        if fade_in_ms + fade_out_ms > selection_length:
            if preferred_handle == "fade_in":
                fade_out_ms = max(0, selection_length - fade_in_ms)
            elif preferred_handle == "fade_out":
                fade_in_ms = max(0, selection_length - fade_out_ms)
            else:
                fade_out_ms = max(0, selection_length - fade_in_ms)
        stored_end = 0 if effective_end >= duration else effective_end
        return trim_start_ms, stored_end, fade_in_ms, fade_out_ms

    def _sanitize_loop(self, loop_start_ms: int, loop_end_ms: int) -> tuple[int, int]:
        duration = max(0, self._duration_ms)
        if duration <= 0:
            return max(0, loop_start_ms), max(0, loop_end_ms)
        if loop_start_ms <= 0 and loop_end_ms <= 0:
            return 0, 0
        loop_start_ms = max(0, min(duration - 1, loop_start_ms))
        effective_end = duration if loop_end_ms <= 0 else max(0, min(duration, loop_end_ms))
        if effective_end <= loop_start_ms:
            effective_end = min(duration, loop_start_ms + 1)
        stored_end = 0 if effective_end >= duration else effective_end
        return loop_start_ms, stored_end

    def _handle_positions(self, rect: QRectF) -> dict[str, float]:
        trim_start_x = self._ms_to_x(self._trim_start_ms, rect)
        trim_end_x = self._ms_to_x(self._effective_trim_end_ms(), rect)
        fade_in_x = self._ms_to_x(self._trim_start_ms + self._fade_in_ms, rect)
        fade_out_x = self._ms_to_x(max(self._trim_start_ms, self._effective_trim_end_ms() - self._fade_out_ms), rect)
        positions = {
            "trim_start": trim_start_x,
            "trim_end": trim_end_x,
            "fade_in": fade_in_x,
            "fade_out": fade_out_x,
        }
        if self._effective_loop_end_ms() > self._loop_start_ms:
            positions["loop_start"] = self._ms_to_x(self._loop_start_ms, rect)
            positions["loop_end"] = self._ms_to_x(self._effective_loop_end_ms(), rect)
        return positions

    def _interactive_positions(self, rect: QRectF) -> dict[str, float]:
        positions = self._handle_positions(rect)
        positions["playhead"] = self._ms_to_x(self._playhead_ms, rect)
        return positions

    def _closest_handle(self, x: float, rect: QRectF) -> str | None:
        handle_positions = self._interactive_positions(rect)
        closest_name: str | None = None
        closest_distance = self._handle_hit_radius
        for name, handle_x in handle_positions.items():
            distance = abs(handle_x - x)
            if distance <= closest_distance:
                closest_name = name
                closest_distance = distance
        return closest_name

    def _update_cursor(self, x: float, rect: QRectF) -> None:
        handle = self._closest_handle(x, rect)
        if handle in {"trim_start", "trim_end", "fade_in", "fade_out", "loop_start", "loop_end", "playhead"}:
            self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mousePressEvent(self, event) -> None:
        rect = self._timeline_rect()
        if rect.contains(event.position()):
            self._drag_handle = self._closest_handle(event.position().x(), rect)
            if self._drag_handle is None:
                self.set_playhead_ms(self._x_to_ms(event.position().x(), rect))
                self._drag_handle = "playhead"
        else:
            self._drag_handle = None
        self._update_cursor(event.position().x(), rect)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._timeline_rect().contains(event.position()):
            self.frame_selection()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        rect = self._timeline_rect()
        if self._drag_handle is None or self._duration_ms <= 0:
            self._update_cursor(event.position().x(), rect)
            super().mouseMoveEvent(event)
            return
        current_ms = self._x_to_ms(event.position().x(), rect)
        trim_start_ms = self._trim_start_ms
        trim_end_ms = self._effective_trim_end_ms()
        fade_in_ms = self._fade_in_ms
        fade_out_ms = self._fade_out_ms
        loop_start_ms = self._loop_start_ms
        loop_end_ms = self._effective_loop_end_ms()
        if self._drag_handle == "trim_start":
            trim_start_ms = max(0, min(trim_end_ms - 1, current_ms))
        elif self._drag_handle == "trim_end":
            trim_end_ms = max(trim_start_ms + 1, min(self._duration_ms, current_ms))
        elif self._drag_handle == "fade_in":
            fade_in_ms = max(0, min(trim_end_ms - trim_start_ms, current_ms - trim_start_ms))
        elif self._drag_handle == "fade_out":
            fade_out_ms = max(0, min(trim_end_ms - trim_start_ms, trim_end_ms - current_ms))
        elif self._drag_handle == "loop_start":
            loop_start_ms = max(0, min(loop_end_ms - 1, current_ms))
        elif self._drag_handle == "loop_end":
            loop_end_ms = max(loop_start_ms + 1, min(self._duration_ms, current_ms))
        elif self._drag_handle == "playhead":
            self.set_playhead_ms(current_ms, emit_signal=True)
            super().mouseMoveEvent(event)
            return
        stored_end = 0 if trim_end_ms >= self._duration_ms else trim_end_ms
        preferred_handle = "fade_in" if self._drag_handle == "fade_in" else "fade_out" if self._drag_handle == "fade_out" else None
        self.set_selection(trim_start_ms, stored_end, fade_in_ms, fade_out_ms, emit_signal=True, preferred_handle=preferred_handle)
        if self._drag_handle in {"loop_start", "loop_end"}:
            stored_loop_end = 0 if loop_end_ms >= self._duration_ms else loop_end_ms
            self.set_loop(loop_start_ms, stored_loop_end, emit_signal=True)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_handle = None
        self._update_cursor(event.position().x(), self._timeline_rect())
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._drag_handle is None:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        timeline_rect = self._timeline_rect()
        if not timeline_rect.contains(event.position()) or self._duration_ms <= 0:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        anchor_ratio = (event.position().x() - timeline_rect.left()) / max(1.0, timeline_rect.width())
        anchor_ratio = max(0.0, min(1.0, anchor_ratio))
        anchor_ms = self._x_to_ms(event.position().x(), timeline_rect)
        self._set_zoom(self._zoom_factor * (1.2 if delta > 0 else 1 / 1.2), anchor_ms=anchor_ms, anchor_ratio=anchor_ratio)
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer_rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QColor("#314055"))
        painter.setBrush(QColor("#111820"))
        painter.drawRoundedRect(outer_rect, 12, 12)

        title_rect = QRectF(16.0, 8.0, max(80.0, self.width() - 32.0), 18.0)
        painter.setPen(QColor("#dfe7f2"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "波形编辑")
        painter.setPen(QColor("#8ca0b8"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{self._status_text} | 缩放 {self._zoom_factor:.1f}x")

        timeline_rect = self._timeline_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#17212d"))
        painter.drawRoundedRect(timeline_rect, 10, 10)

        if not self._amplitudes or self._duration_ms <= 0:
            painter.setPen(QColor("#7a8ba1"))
            painter.drawText(timeline_rect, Qt.AlignmentFlag.AlignCenter, "没有可显示的波形")
            return

        ruler_step = self._ruler_step_ms()
        ruler_start = (self._view_start_ms // ruler_step) * ruler_step
        painter.setPen(QPen(QColor("#314a63"), 1.0))
        for tick_ms in range(ruler_start, self._view_end_ms() + ruler_step, ruler_step):
            x = self._ms_to_x(tick_ms, timeline_rect)
            painter.drawLine(QPointF(x, timeline_rect.top() + 4.0), QPointF(x, timeline_rect.top() + 14.0))
            painter.setPen(QColor("#7f91a6"))
            painter.drawText(QRectF(x + 3.0, timeline_rect.top() + 2.0, 70.0, 14.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._format_time_ms(tick_ms))
            painter.setPen(QPen(QColor("#314a63"), 1.0))

        selection_start_x = self._ms_to_x(self._trim_start_ms, timeline_rect)
        selection_end_x = self._ms_to_x(self._effective_trim_end_ms(), timeline_rect)
        selection_rect = QRectF(selection_start_x, timeline_rect.top(), max(2.0, selection_end_x - selection_start_x), timeline_rect.height())
        painter.setBrush(QColor("#0b1219"))
        if selection_start_x > timeline_rect.left():
            painter.drawRect(QRectF(timeline_rect.left(), timeline_rect.top(), selection_start_x - timeline_rect.left(), timeline_rect.height()))
        if selection_end_x < timeline_rect.right():
            painter.drawRect(QRectF(selection_end_x, timeline_rect.top(), timeline_rect.right() - selection_end_x, timeline_rect.height()))
        painter.setBrush(QColor("#1d3550"))
        painter.drawRoundedRect(selection_rect, 8, 8)

        loop_end_ms = self._effective_loop_end_ms()
        if loop_end_ms > self._loop_start_ms:
            loop_start_x = self._ms_to_x(self._loop_start_ms, timeline_rect)
            loop_end_x = self._ms_to_x(loop_end_ms, timeline_rect)
            loop_rect = QRectF(loop_start_x, timeline_rect.top() + 22.0, max(2.0, loop_end_x - loop_start_x), max(16.0, timeline_rect.height() - 44.0))
            painter.setPen(QPen(QColor("#f081ff"), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(240, 129, 255, 45))
            painter.drawRoundedRect(loop_rect, 6, 6)

        center_y = timeline_rect.center().y()
        waveform_path = QPainterPath()
        top_points: list[QPointF] = []
        bottom_points: list[QPointF] = []
        sample_count = len(self._amplitudes)
        for index, amplitude in enumerate(self._amplitudes):
            x = timeline_rect.left() + (timeline_rect.width() * index / max(1, sample_count - 1))
            magnitude = amplitude * (timeline_rect.height() * 0.42)
            top_points.append(QPointF(x, center_y - magnitude))
            bottom_points.append(QPointF(x, center_y + magnitude))
        if top_points:
            waveform_path.moveTo(top_points[0])
            for point in top_points[1:]:
                waveform_path.lineTo(point)
            for point in reversed(bottom_points):
                waveform_path.lineTo(point)
            waveform_path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#5fa4ff"))
            painter.drawPath(waveform_path)

        painter.setPen(QPen(QColor("#d9ecff"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(timeline_rect.left(), center_y), QPointF(timeline_rect.right(), center_y))

        playhead_x = self._ms_to_x(self._playhead_ms, timeline_rect)
        painter.setPen(QPen(QColor("#ff8d5a"), 2.0))
        painter.drawLine(QPointF(playhead_x, timeline_rect.top() + 2.0), QPointF(playhead_x, timeline_rect.bottom() - 2.0))

        handle_positions = self._handle_positions(timeline_rect)
        trim_pen = QPen(QColor("#f7f0a3"), 2.0)
        fade_pen = QPen(QColor("#77f0c0"), 2.0)
        loop_pen = QPen(QColor("#f081ff"), 2.0)
        for name in ("trim_start", "trim_end"):
            painter.setPen(trim_pen)
            x = handle_positions[name]
            painter.drawLine(QPointF(x, timeline_rect.top() + 4.0), QPointF(x, timeline_rect.bottom() - 4.0))
        if self._fade_in_ms > 0:
            painter.setPen(fade_pen)
            painter.drawLine(
                QPointF(handle_positions["trim_start"], timeline_rect.bottom() - 8.0),
                QPointF(handle_positions["fade_in"], timeline_rect.top() + 8.0),
            )
        if self._fade_out_ms > 0:
            painter.setPen(fade_pen)
            painter.drawLine(
                QPointF(handle_positions["fade_out"], timeline_rect.top() + 8.0),
                QPointF(handle_positions["trim_end"], timeline_rect.bottom() - 8.0),
            )
        for name in ("loop_start", "loop_end"):
            if name in handle_positions:
                painter.setPen(loop_pen)
                x = handle_positions[name]
                painter.drawLine(QPointF(x, timeline_rect.top() + 18.0), QPointF(x, timeline_rect.bottom() - 18.0))

        for name, x in handle_positions.items():
            if name.startswith("trim"):
                color = QColor("#f7f0a3")
            elif name.startswith("loop"):
                color = QColor("#f081ff")
            else:
                color = QColor("#77f0c0")
            painter.setPen(QColor("#0e141c"))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, timeline_rect.bottom() - 8.0), 4.0, 4.0)