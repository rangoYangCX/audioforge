from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from audioforge.app.utils.icons import load_app_icon


SOURCE_ASSET_MIME_TYPE = "application/x-audioforge-source-asset-paths"


class SourceTreeWidget(QTreeWidget):
    sourceSelected = Signal(str)
    sourceActivated = Signal(str)
    importFilesDropped = Signal(list)

    def __init__(self, parent=None, *, selection_mode: QAbstractItemView.SelectionMode = QAbstractItemView.SelectionMode.SingleSelection) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["名称", "类型", "引用"])
        self.setSelectionMode(selection_mode)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.itemSelectionChanged.connect(self._emit_selected_source)
        self.itemDoubleClicked.connect(lambda _item, _column: self._emit_activated_source())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._extract_import_paths(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._extract_import_paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        import_paths = self._extract_import_paths(event)
        if import_paths:
            self.importFilesDropped.emit(import_paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def mimeTypes(self) -> list[str]:
        return [SOURCE_ASSET_MIME_TYPE]

    def mimeData(self, items: list[QTreeWidgetItem]) -> QMimeData:
        mime_data = QMimeData()
        drag_items: list[QTreeWidgetItem] = []
        seen_item_ids: set[int] = set()
        for candidate in [*items, *self.selectedItems(), self.currentItem()]:
            if candidate is None:
                continue
            candidate_id = id(candidate)
            if candidate_id in seen_item_ids:
                continue
            seen_item_ids.add(candidate_id)
            drag_items.append(candidate)
        source_paths: list[str] = []
        seen_paths: set[str] = set()
        for item in drag_items:
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(entry, dict):
                continue
            source_path = str(entry.get("source_path", "")).strip()
            if not source_path or source_path in seen_paths:
                continue
            source_paths.append(source_path)
            seen_paths.add(source_path)
        if source_paths:
            mime_data.setData(SOURCE_ASSET_MIME_TYPE, "\n".join(source_paths).encode("utf-8"))
        return mime_data

    def _extract_import_paths(self, event) -> list[str]:
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return []
        import_paths: list[str] = []
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
                normalized = str(path)
                path_key = normalized.casefold()
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                import_paths.append(normalized)
        return import_paths

    def rebuild(self, entries: list[dict[str, object]]) -> None:
        selected_source_paths = self.selected_source_paths()
        current_source_path = self.current_source_path()
        self.blockSignals(True)
        self.clear()

        normalized_entries = [self._normalize_entry(entry) for entry in entries if str(entry.get("source_path", "")).strip()]
        paths = [Path(str(entry["source_path"])) for entry in normalized_entries]
        common_root = self._resolve_common_root(paths)
        folder_items: dict[tuple[str, ...], QTreeWidgetItem] = {}

        for entry in normalized_entries:
            source_path = Path(str(entry["source_path"]))
            display_parts = self._display_parts(source_path, common_root)
            parent_item = None
            partial_parts: list[str] = []
            for folder_name in display_parts[:-1]:
                partial_parts.append(folder_name)
                folder_key = tuple(partial_parts)
                folder_item = folder_items.get(folder_key)
                if folder_item is None:
                    folder_item = QTreeWidgetItem([folder_name, "Folder", ""])
                    folder_item.setIcon(0, load_app_icon("folder"))
                    if parent_item is None:
                        self.addTopLevelItem(folder_item)
                    else:
                        parent_item.addChild(folder_item)
                    folder_items[folder_key] = folder_item
                parent_item = folder_item

            source_item = QTreeWidgetItem([
                display_parts[-1],
                "Source",
                self._reference_summary(entry),
            ])
            source_item.setIcon(0, load_app_icon("audio"))
            source_item.setData(0, Qt.ItemDataRole.UserRole, entry)
            tooltip = self._entry_tooltip(entry)
            source_item.setToolTip(0, tooltip)
            source_item.setToolTip(2, tooltip)
            if bool(entry.get("missing", False)):
                source_item.setForeground(0, Qt.GlobalColor.red)
                source_item.setForeground(2, Qt.GlobalColor.red)
            elif bool(entry.get("unreferenced", False)):
                source_item.setForeground(0, Qt.GlobalColor.yellow)
                source_item.setForeground(2, Qt.GlobalColor.yellow)
            if parent_item is None:
                self.addTopLevelItem(source_item)
            else:
                parent_item.addChild(source_item)

        self.expandToDepth(1)
        self.blockSignals(False)

        if selected_source_paths:
            self.set_selected_source_paths(selected_source_paths)
        elif current_source_path:
            self.select_source_path(current_source_path)
        else:
            self._emit_selected_source()

    def apply_filter(self, query: str) -> None:
        normalized = query.strip().lower()
        for root_index in range(self.topLevelItemCount()):
            item = self.topLevelItem(root_index)
            self._apply_filter_recursive(item, normalized)
        if normalized:
            self.expandAll()

    def select_source_path(self, source_path: str) -> None:
        item = self._find_source_item(source_path)
        if item is None:
            self._emit_selected_source()
            return
        self.blockSignals(True)
        self.clearSelection()
        self.setCurrentItem(item)
        item.setSelected(True)
        self.scrollToItem(item)
        self.blockSignals(False)
        self._emit_selected_source()

    def set_selected_source_paths(self, source_paths: list[str]) -> None:
        normalized_paths = {str(value).strip() for value in source_paths if str(value).strip()}
        self.blockSignals(True)
        self.clearSelection()
        current_item = None
        pending = [self.topLevelItem(index) for index in range(self.topLevelItemCount())]
        while pending:
            item = pending.pop(0)
            if item is None:
                continue
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(entry, dict):
                source_path = str(entry.get("source_path", "")).strip()
                if source_path in normalized_paths:
                    item.setSelected(True)
                    if current_item is None:
                        current_item = item
            for child_index in range(item.childCount()):
                pending.append(item.child(child_index))
        if current_item is not None:
            self.setCurrentItem(current_item, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.scrollToItem(current_item)
        self.blockSignals(False)
        self._emit_selected_source()

    def select_next_matching_asset(self, query: str) -> str | None:
        normalized = query.strip().lower()
        if not normalized:
            return None
        matching_items = self._visible_matching_source_items(normalized)
        if not matching_items:
            return None

        current_source_path = self.current_source_path()
        target_index = 0
        if current_source_path:
            for index, item in enumerate(matching_items):
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(entry, dict) and str(entry.get("source_path", "")) == current_source_path:
                    target_index = (index + 1) % len(matching_items)
                    break

        target_item = matching_items[target_index]
        entry = target_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return None
        source_path = str(entry.get("source_path", "")).strip()
        if not source_path:
            return None
        self.select_source_path(source_path)
        return source_path

    def current_source_path(self) -> str:
        entry = self.current_source_entry()
        if not entry:
            return ""
        return str(entry.get("source_path", "")).strip()

    def current_source_entry(self) -> dict[str, object] | None:
        item = self.currentItem()
        if item is None:
            return None
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return None
        return entry

    def selected_source_paths(self) -> list[str]:
        paths: list[str] = []
        for entry in self.selected_source_entries():
            source_path = str(entry.get("source_path", "")).strip()
            if source_path:
                paths.append(source_path)
        return paths

    def selected_source_entries(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for item in self.selectedItems():
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(entry, dict):
                entries.append(entry)
        if not entries:
            current_entry = self.current_source_entry()
            if current_entry is not None:
                entries.append(current_entry)
        return entries

    def _normalize_entry(self, entry: dict[str, object]) -> dict[str, object]:
        source_path = str(entry.get("source_path", "")).strip()
        audio_ids = sorted({str(value) for value in entry.get("audio_ids", []) if str(value).strip()})
        event_ids = sorted({str(value) for value in entry.get("event_ids", []) if str(value).strip()})
        asset_keys = sorted({str(value) for value in entry.get("asset_keys", []) if str(value).strip()})
        return {
            "source_path": source_path,
            "audio_ids": audio_ids,
            "event_ids": event_ids,
            "asset_keys": asset_keys,
            "reference_count": int(entry.get("reference_count", len(audio_ids) or 0)),
            "missing": bool(entry.get("missing", False)),
            "unreferenced": bool(entry.get("unreferenced", False)),
        }

    def _resolve_common_root(self, paths: list[Path]) -> Path | None:
        if not paths:
            return None
        try:
            common_path = os.path.commonpath([str(path.parent if path.name else path) for path in paths])
        except ValueError:
            return None
        if not common_path or common_path == ".":
            return None
        return Path(common_path)

    def _display_parts(self, source_path: Path, common_root: Path | None) -> list[str]:
        if common_root is not None:
            try:
                relative_parts = list(source_path.relative_to(common_root).parts)
            except ValueError:
                relative_parts = list(source_path.parts)
        else:
            relative_parts = list(source_path.parts)

        if source_path.is_absolute() and common_root is None and relative_parts:
            anchor_label = source_path.drive or source_path.anchor.rstrip("\\/")
            if anchor_label:
                relative_parts[0] = anchor_label

        if not relative_parts:
            fallback_name = source_path.name or str(source_path)
            return [fallback_name]
        return [part for part in relative_parts if part]

    def _reference_summary(self, entry: dict[str, object]) -> str:
        fragments: list[str] = []
        reference_count = int(entry.get("reference_count", 0))
        if reference_count > 0:
            fragments.append(f"Audio {reference_count}")
        else:
            fragments.append("Audio 0")
        if bool(entry.get("missing", False)):
            fragments.append("缺失")
        elif bool(entry.get("unreferenced", False)):
            fragments.append("未引用")
        return " | ".join(fragments)

    def _entry_tooltip(self, entry: dict[str, object]) -> str:
        source_path = str(entry.get("source_path", "")).strip()
        audio_ids = [str(value) for value in entry.get("audio_ids", []) if str(value).strip()]
        event_ids = [str(value) for value in entry.get("event_ids", []) if str(value).strip()]
        asset_keys = [str(value) for value in entry.get("asset_keys", []) if str(value).strip()]
        state_fragments: list[str] = []
        if bool(entry.get("missing", False)):
            state_fragments.append("文件缺失")
        if bool(entry.get("unreferenced", False)):
            state_fragments.append("当前未被 Audio 引用")
        state_text = "、".join(state_fragments) if state_fragments else "状态正常"
        audio_preview = ", ".join(audio_ids[:6]) if audio_ids else "-"
        event_preview = ", ".join(event_ids[:6]) if event_ids else "-"
        asset_preview = ", ".join(asset_keys[:6]) if asset_keys else "-"
        return f"路径：{source_path}\n状态：{state_text}\nAudio：{audio_preview}\nEvent：{event_preview}\n资源键：{asset_preview}"

    def _apply_filter_recursive(self, item: QTreeWidgetItem, query: str) -> bool:
        child_visible = False
        for child_index in range(item.childCount()):
            if self._apply_filter_recursive(item.child(child_index), query):
                child_visible = True

        entry = item.data(0, Qt.ItemDataRole.UserRole)
        haystacks = [item.text(0).lower(), item.text(2).lower()]
        if isinstance(entry, dict):
            haystacks.append(str(entry.get("source_path", "")).lower())
            haystacks.extend(str(value).lower() for value in entry.get("audio_ids", []))
            haystacks.extend(str(value).lower() for value in entry.get("event_ids", []))
            haystacks.extend(str(value).lower() for value in entry.get("asset_keys", []))
        self_match = not query or any(query in haystack for haystack in haystacks)
        visible = self_match or child_visible
        item.setHidden(not visible)
        return visible

    def _find_source_item(self, source_path: str) -> QTreeWidgetItem | None:
        normalized = str(source_path).strip()
        if not normalized:
            return None
        pending = [self.topLevelItem(index) for index in range(self.topLevelItemCount())]
        while pending:
            item = pending.pop(0)
            if item is None:
                continue
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(entry, dict) and str(entry.get("source_path", "")).strip() == normalized:
                return item
            for child_index in range(item.childCount()):
                pending.append(item.child(child_index))
        return None

    def _visible_matching_source_items(self, query: str) -> list[QTreeWidgetItem]:
        matches: list[QTreeWidgetItem] = []
        pending = [self.topLevelItem(index) for index in range(self.topLevelItemCount())]
        while pending:
            item = pending.pop(0)
            if item is None:
                continue
            if not item.isHidden():
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(entry, dict):
                    source_path = str(entry.get("source_path", "")).lower()
                    if (
                        query in item.text(0).lower()
                        or query in source_path
                        or any(query in str(value).lower() for value in entry.get("audio_ids", []))
                        or any(query in str(value).lower() for value in entry.get("event_ids", []))
                    ):
                        matches.append(item)
            for child_index in range(item.childCount()):
                pending.append(item.child(child_index))
        return matches

    def _emit_selected_source(self) -> None:
        source_path = self.current_source_path()
        self.sourceSelected.emit(source_path)

    def _emit_activated_source(self) -> None:
        source_path = self.current_source_path()
        if source_path:
            self.sourceActivated.emit(source_path)