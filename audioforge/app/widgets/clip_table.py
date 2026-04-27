from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QTableWidget


class ClipTableWidget(QTableWidget):
    filesDropped = Signal(list)
    clipEdited = Signal(str, str, str)
    rowsReordered = Signal(list)

    def __init__(self, rows: int, columns: int, parent=None) -> None:
        super().__init__(rows, columns, parent)
        self._loading = False
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.itemChanged.connect(self._handle_item_changed)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            file_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if file_paths:
                self.filesDropped.emit(file_paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)
        if event.source() is self:
            self.rowsReordered.emit(self.row_clip_ids())

    def selected_clip_ids(self) -> list[str]:
        clip_ids: list[str] = []
        for row in sorted({index.row() for index in self.selectedIndexes()}):
            item = self.item(row, 0)
            if item is not None:
                clip_ids.append(item.text())
        return clip_ids

    def row_clip_ids(self) -> list[str]:
        clip_ids: list[str] = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None:
                clip_ids.append(item.text())
        return clip_ids

    def begin_loading(self) -> None:
        self._loading = True

    def end_loading(self) -> None:
        self._loading = False

    def _handle_item_changed(self, item) -> None:
        if self._loading:
            return
        clip_id_item = self.item(item.row(), 0)
        if clip_id_item is None:
            return
        field_by_column = {
            1: "source_path",
            2: "asset_key",
            3: "weight",
            4: "trim_start_ms",
            5: "trim_end_ms",
            6: "loop_start_ms",
            7: "loop_end_ms",
            8: "tags",
        }
        field_name = field_by_column.get(item.column())
        if field_name is None:
            return
        self.clipEdited.emit(clip_id_item.text(), field_name, item.text())