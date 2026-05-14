from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from audioforge.app.utils.icons import load_app_icon, load_event_icon
from audioforge.app.widgets.source_tree import SOURCE_ASSET_MIME_TYPE


class AudioTreeWidget(QTreeWidget):
    audioSelected = Signal(str)
    audioActivated = Signal(str)
    audioFilesDropped = Signal(list, object)
    sourceAssetsDroppedToAudio = Signal(list, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Audio", "模式", "内容"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.itemSelectionChanged.connect(self._emit_current_audio)
        self.itemDoubleClicked.connect(self._emit_activated_audio)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._extract_import_paths(event):
            event.acceptProposedAction()
            return
        if self._extract_source_asset_paths(event) and self._resolve_drop_target_audio_id(self._event_position_point(event)) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._extract_import_paths(event):
            event.acceptProposedAction()
            return
        if self._extract_source_asset_paths(event):
            if self._resolve_drop_target_audio_id(self._event_position_point(event)) is not None:
                event.acceptProposedAction()
            else:
                event.ignore()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        source_asset_paths = self._extract_source_asset_paths(event)
        if source_asset_paths:
            target_audio_id = self._resolve_drop_target_audio_id(self._event_position_point(event))
            if target_audio_id is not None:
                self.sourceAssetsDroppedToAudio.emit(source_asset_paths, target_audio_id)
                event.acceptProposedAction()
            return

        import_paths = self._extract_import_paths(event)
        if import_paths:
            target_audio_id = self._resolve_drop_target_audio_id(self._event_position_point(event))
            self.audioFilesDropped.emit(import_paths, target_audio_id)
            event.acceptProposedAction()
            return

        super().dropEvent(event)

    def rebuild(self, entries: list[dict[str, object]]) -> None:
        current_audio_id = self.current_audio_id()
        self.blockSignals(True)
        self.clear()
        for entry in entries:
            audio_id = str(entry.get("audio_id", "")).strip()
            if not audio_id:
                continue
            display_name = str(entry.get("display_name", "")).strip() or audio_id
            play_mode = str(entry.get("play_mode", "")).strip() or "-"
            clip_count = int(entry.get("clip_count", 0))
            event_count = int(entry.get("event_count", 0))
            item = QTreeWidgetItem([display_name, play_mode, f"片段 {clip_count} / Event {event_count}"])
            item.setData(0, Qt.ItemDataRole.UserRole, audio_id)
            item.setToolTip(0, audio_id)
            item.setToolTip(2, "、".join(str(value) for value in entry.get("event_ids", []) if str(value).strip()) or "当前没有引用 Event")
            icon_name = "audio"
            if play_mode in {"OneShot", "Random", "Sequence", "Combo"}:
                item.setIcon(0, load_event_icon(play_mode))
            else:
                item.setIcon(0, load_app_icon(icon_name))
            self.addTopLevelItem(item)
        if current_audio_id:
            for index in range(self.topLevelItemCount()):
                item = self.topLevelItem(index)
                if str(item.data(0, Qt.ItemDataRole.UserRole) or "") != current_audio_id:
                    continue
                self.setCurrentItem(item)
                item.setSelected(True)
                break
        elif self.topLevelItemCount() > 0:
            self.setCurrentItem(self.topLevelItem(0))
        self.blockSignals(False)

    def apply_filter(self, query: str) -> None:
        normalized = query.strip().lower()
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            audio_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            haystacks = [item.text(0), item.text(1), item.text(2), audio_id]
            visible = not normalized or any(normalized in value.lower() for value in haystacks)
            item.setHidden(not visible)

    def current_audio_id(self) -> str | None:
        item = self.currentItem()
        if item is None:
            return None
        audio_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        return audio_id or None

    def select_audio_id(self, audio_id: str | None, *, emit_signal: bool = True) -> None:
        target_id = str(audio_id or "").strip()
        self.blockSignals(True)
        self.clearSelection()
        if not target_id:
            self.setCurrentItem(None)
            self.blockSignals(False)
            return
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "") != target_id:
                continue
            if item.isHidden():
                item.setHidden(False)
            self.setCurrentItem(item)
            item.setSelected(True)
            self.scrollToItem(item)
            self.blockSignals(False)
            return
        self.setCurrentItem(None)
        self.blockSignals(False)

    def select_next_matching_audio(self, query: str) -> str | None:
        normalized = query.strip().lower()
        if not normalized:
            return None
        matching_items = [
            self.topLevelItem(index)
            for index in range(self.topLevelItemCount())
            if not self.topLevelItem(index).isHidden()
            and any(
                normalized in value.lower()
                for value in [
                    self.topLevelItem(index).text(0),
                    self.topLevelItem(index).text(1),
                    self.topLevelItem(index).text(2),
                    str(self.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole) or ""),
                ]
            )
        ]
        if not matching_items:
            return None

        current_audio_id = self.current_audio_id()
        target_index = 0
        if current_audio_id is not None:
            for index, item in enumerate(matching_items):
                if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == current_audio_id:
                    target_index = (index + 1) % len(matching_items)
                    break

        target_item = matching_items[target_index]
        audio_id = str(target_item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if not audio_id:
            return None
        self.select_audio_id(audio_id)
        return audio_id

    def _emit_current_audio(self) -> None:
        audio_id = self.current_audio_id()
        if audio_id:
            self.audioSelected.emit(audio_id)

    def _emit_activated_audio(self, item: QTreeWidgetItem, _column: int) -> None:
        audio_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if audio_id:
            self.audioActivated.emit(audio_id)

    def _resolve_drop_target_audio_id(self, position) -> str | None:
        item = self.itemAt(position)
        if item is None:
            return None
        audio_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        return audio_id or None

    def _event_position_point(self, event) -> object:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _extract_source_asset_paths(self, event) -> list[str]:
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasFormat(SOURCE_ASSET_MIME_TYPE):
            return []
        raw_payload = bytes(mime_data.data(SOURCE_ASSET_MIME_TYPE)).decode("utf-8", errors="ignore")
        source_paths: list[str] = []
        seen_paths: set[str] = set()
        for line in raw_payload.splitlines():
            source_path = line.strip()
            if not source_path or source_path in seen_paths:
                continue
            source_paths.append(source_path)
            seen_paths.add(source_path)
        return source_paths

    def _extract_import_paths(self, event) -> list[str]:
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return []
        supported_paths: list[str] = []
        seen_paths: set[str] = set()
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile().strip()
            if not local_path:
                continue
            path = Path(local_path)
            if not path.exists():
                continue
            if path.is_dir() or path.suffix.lower() in {".wav", ".ogg", ".mp3", ".flac"}:
                normalized_path = str(path)
                path_key = normalized_path.casefold()
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                supported_paths.append(normalized_path)
        return supported_paths