from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from audioforge.app.models.audio_project import AudioProject
from audioforge.app.utils.icons import load_app_icon, load_event_icon
from audioforge.app.utils.token_codec import (
    SOURCE_BINDING_TOKEN_SEPARATOR,
    decode_source_binding_token,
    encode_source_binding_token,
)
from audioforge.app.widgets.source_tree import SOURCE_ASSET_MIME_TYPE


# SOURCE_BINDING_TOKEN_SEPARATOR 和 encode/decode 函数
# 已移至 utils/token_codec.py，此处通过导入使用


class EventTreeWidget(QTreeWidget):
    eventSelected = Signal(str)
    nodeSelected = Signal(str, str)
    nodesSelectionChanged = Signal(list)
    nodeMoved = Signal(str, str, object, int)
    audioFilesDropped = Signal(list, object)
    sourceAssetsDroppedToAudio = Signal(list, str)
    eventAudioRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._analysis_status: dict[str, dict[str, str]] = {}
        self._experiment_origin_labels: dict[str, str] = {}
        self._suppress_audio_bindings_popup = False
        self.setColumnCount(3)
        self.setHeaderLabels(["名称", "类型", "内容"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setAcceptDrops(True)
        self.itemSelectionChanged.connect(self._emit_selected_event)
        self.itemExpanded.connect(self._handle_item_expanded)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._extract_source_asset_paths(event):
            event.acceptProposedAction()
            return
        if self._extract_import_paths(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._extract_source_asset_paths(event):
            if self._resolve_drop_target_event_id(self._event_position_point(event)) is not None:
                event.acceptProposedAction()
            else:
                event.ignore()
            return
        if self._extract_import_paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def rebuild(self, project: AudioProject) -> None:
        self._suppress_audio_bindings_popup = True
        signal_blocker = QSignalBlocker(self)
        self.clear()
        for folder_id in project.root_folder_ids:
            folder_item = self._build_folder_item(project, folder_id, is_root=True)
            self.addTopLevelItem(folder_item)
        self._expand_folder_items()
        del signal_blocker
        self._suppress_audio_bindings_popup = False

    def set_analysis_status(self, status_map: dict[str, dict[str, str]]) -> None:
        self._analysis_status = dict(status_map)
        for root_index in range(self.topLevelItemCount()):
            self._apply_status_recursive(self.topLevelItem(root_index))

    def set_experiment_origin_labels(self, origin_map: dict[str, str]) -> None:
        self._experiment_origin_labels = dict(origin_map)
        for root_index in range(self.topLevelItemCount()):
            self._apply_status_recursive(self.topLevelItem(root_index))

    def select_node(self, node_type: str, node_id: str, *, emit_signal: bool = True) -> None:
        self.select_nodes([(node_type, node_id)], current_node=(node_type, node_id), emit_signal=emit_signal)

    def select_nodes(self, nodes: list[tuple[str, str]], current_node: tuple[str, str] | None = None, *, emit_signal: bool = True) -> None:
        resolved_items: list[QTreeWidgetItem] = []
        seen: set[tuple[str, str]] = set()
        for node_type, node_id in nodes:
            payload = (str(node_type), str(node_id))
            if payload in seen:
                continue
            item = self._find_item(payload[0], payload[1])
            if item is None:
                continue
            seen.add(payload)
            resolved_items.append(item)

        self.blockSignals(True)
        self.clearSelection()
        if not resolved_items:
            self.setCurrentItem(None)
            self.blockSignals(False)
            self.nodesSelectionChanged.emit([])
            return

        current_item = None
        if current_node is not None:
            current_item = self._find_item(current_node[0], current_node[1])
        if current_item is None:
            current_item = resolved_items[0]

        self.setCurrentItem(current_item)
        for item in resolved_items:
            item.setSelected(True)
        self.scrollToItem(current_item)
        self.blockSignals(False)
        if emit_signal:
            self._emit_selected_event()

    def rename_node_label(self, node_type: str, node_id: str, new_label: str) -> None:
        item = self._find_item(node_type, node_id)
        if item is not None:
            item.setText(0, new_label)

    def apply_filter(self, query: str) -> None:
        normalized = query.strip().lower()
        for root_index in range(self.topLevelItemCount()):
            item = self.topLevelItem(root_index)
            self._apply_filter_recursive(item, normalized)

        if normalized:
            self._suppress_audio_bindings_popup = True
            self._expand_folder_items()
            self._suppress_audio_bindings_popup = False

    def selected_payloads(self) -> list[tuple[str, str]]:
        payloads: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in self.selectedItems():
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if payload is None:
                continue
            typed_payload = (str(payload[0]), str(payload[1]))
            if typed_payload in seen:
                continue
            seen.add(typed_payload)
            payloads.append(typed_payload)
        return payloads

    def selected_event_ids(self) -> list[str]:
        event_ids: list[str] = []
        seen: set[str] = set()
        for item in self.selectedItems():
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if payload is None:
                continue
            node_type = str(payload[0])
            if node_type == "event":
                event_id = str(payload[1])
            else:
                continue
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            event_ids.append(event_id)
        return event_ids

    def select_next_matching_event(self, query: str) -> str | None:
        normalized = query.strip().lower()
        if not normalized:
            return None
        matching_items = self._visible_matching_event_items(normalized)
        if not matching_items:
            return None

        current_event_id = None
        current_item = self.currentItem()
        if current_item is not None:
            payload = current_item.data(0, Qt.ItemDataRole.UserRole)
            if payload is not None and payload[0] == "event":
                current_event_id = str(payload[1])

        target_index = 0
        if current_event_id is not None:
            for index, item in enumerate(matching_items):
                payload = item.data(0, Qt.ItemDataRole.UserRole)
                if payload is not None and str(payload[1]) == current_event_id:
                    target_index = (index + 1) % len(matching_items)
                    break

        target_item = matching_items[target_index]
        payload = target_item.data(0, Qt.ItemDataRole.UserRole)
        if payload is None:
            return None
        self.select_nodes([("event", str(payload[1]))], current_node=("event", str(payload[1])))
        return str(payload[1])

    def _build_folder_item(self, project: AudioProject, folder_id: str, is_root: bool = False) -> QTreeWidgetItem:
        folder = project.folders[folder_id]
        item = QTreeWidgetItem([folder.name, "Work Unit" if is_root else "Folder", f"子文件夹 {len(folder.child_folder_ids)} / 事件 {len(folder.child_event_ids)}"])
        item.setData(0, Qt.ItemDataRole.UserRole, ("folder", folder.id))
        item.setIcon(0, load_app_icon("folder"))
        self._configure_item_flags(item, "folder")

        for child_folder_id in folder.child_folder_ids:
            item.addChild(self._build_folder_item(project, child_folder_id))
        for event_id in folder.child_event_ids:
            event = project.events[event_id]
            event_item = QTreeWidgetItem([event.display_name or event_id, "Event", event_id])
            event_item.setData(0, Qt.ItemDataRole.UserRole, ("event", event_id))
            event_item.setIcon(0, load_event_icon(event.play_mode))
            event_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self._configure_item_flags(event_item, "event")
            self._apply_status_to_item(event_item, event_id)
            item.addChild(event_item)
        return item

    def _handle_item_expanded(self, item: QTreeWidgetItem) -> None:
        if self._suppress_audio_bindings_popup:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is None or str(payload[0]) != "event":
            return

        self._suppress_audio_bindings_popup = True
        self.collapseItem(item)
        self._suppress_audio_bindings_popup = False
        event_id = str(payload[1])
        self.eventAudioRequested.emit(event_id)

    def _apply_status_recursive(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is not None and payload[0] == "event":
            self._apply_status_to_item(item, payload[1])
        for child_index in range(item.childCount()):
            self._apply_status_recursive(item.child(child_index))

    def _expand_folder_items(self) -> None:
        for root_index in range(self.topLevelItemCount()):
            self._expand_folder_items_recursive(self.topLevelItem(root_index))

    def _expand_folder_items_recursive(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is not None and payload[0] == "folder":
            self.expandItem(item)
        for child_index in range(item.childCount()):
            self._expand_folder_items_recursive(item.child(child_index))

    def _apply_status_to_item(self, item: QTreeWidgetItem, event_id: str) -> None:
        status = self._analysis_status.get(event_id)
        origin_label = self._experiment_origin_labels.get(str(event_id), "")
        if not status:
            item.setText(2, origin_label or event_id)
            self._apply_origin_highlight(item, origin_label)
            item.setToolTip(0, origin_label)
            return
        level = status.get("level", "warning")
        summary = status.get("summary", "")
        if origin_label:
            summary = f"{summary} | {origin_label}" if summary else origin_label
        item.setText(2, summary)
        item.setToolTip(0, summary)
        color = Qt.GlobalColor.red if level == "error" else Qt.GlobalColor.yellow
        item.setForeground(0, color)

    def _apply_origin_highlight(self, item: QTreeWidgetItem, origin_label: str) -> None:
        colors = {
            "实验新增": QColor(34, 139, 34),
            "实验修改": QColor(214, 121, 32),
            "底板继承": QColor(130, 130, 130),
        }
        color = colors.get(origin_label, Qt.GlobalColor.white)
        for column in range(self.columnCount()):
            item.setForeground(column, color)

    def _emit_selected_event(self) -> None:
        payloads = self.selected_payloads()
        self.nodesSelectionChanged.emit(payloads)
        if len(payloads) != 1:
            return

        current_payload = None
        current_item = self.currentItem()
        if current_item is not None:
            payload = current_item.data(0, Qt.ItemDataRole.UserRole)
            if payload is not None:
                current_payload = (str(payload[0]), str(payload[1]))
        node_type, node_id = current_payload or payloads[0]
        self.nodeSelected.emit(node_type, node_id)
        if node_type == "event":
            self.eventSelected.emit(node_id)

    def dropEvent(self, event: QDropEvent) -> None:
        source_asset_paths = self._extract_source_asset_paths(event)
        if source_asset_paths:
            target_event_id = self._resolve_drop_target_event_id(self._event_position_point(event))
            if target_event_id is not None:
                self.sourceAssetsDroppedToAudio.emit(source_asset_paths, target_event_id)
                event.acceptProposedAction()
            return

        dropped_paths = self._extract_import_paths(event)
        if dropped_paths:
            target_folder_id = self._resolve_drop_target_folder_id(self._event_position_point(event))
            self.audioFilesDropped.emit(dropped_paths, target_folder_id)
            event.acceptProposedAction()
            return

        moved_item = self.currentItem()
        if moved_item is None:
            super().dropEvent(event)
            return

        node_type, node_id = moved_item.data(0, Qt.ItemDataRole.UserRole)
        if str(node_type) == "source_binding":
            event.ignore()
            return
        super().dropEvent(event)

        moved_item = self._find_item(node_type, node_id)
        if moved_item is None:
            return

        parent_item = moved_item.parent()
        parent_payload = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item is not None else None
        if parent_payload is not None and str(parent_payload[0]) != "folder":
            return
        parent_folder_id = None if parent_payload is None else parent_payload[1]
        index = self.indexOfTopLevelItem(moved_item) if parent_item is None else parent_item.indexOfChild(moved_item)
        self.nodeMoved.emit(node_type, node_id, parent_folder_id, index)

    def _configure_item_flags(self, item: QTreeWidgetItem, node_type: str) -> None:
        flags = item.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if node_type in {"folder", "event"}:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        if node_type == "folder":
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        item.setFlags(flags)

    def _event_position_point(self, event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _extract_source_asset_paths(self, event) -> list[str]:
        mime_data = event.mimeData()
        if not mime_data.hasFormat(SOURCE_ASSET_MIME_TYPE):
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
        if not mime_data.hasUrls():
            return []
        import_paths: list[str] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_path = Path(url.toLocalFile())
            if local_path.is_dir():
                import_paths.append(str(local_path))
                continue
            if local_path.suffix.lower() not in {".wav", ".ogg"}:
                continue
            import_paths.append(str(local_path))
        return import_paths

    def _resolve_drop_target_folder_id(self, position: QPoint):
        item = self.itemAt(position)
        if item is None:
            current_item = self.currentItem()
            if current_item is not None:
                item = current_item
        if item is None:
            return None

        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is None:
            return None
        node_type, node_id = payload
        if node_type == "folder":
            return node_id
        parent_payload = self._nearest_ancestor_payload(item.parent(), "folder")
        return None if parent_payload is None else parent_payload[1]

    def _resolve_drop_target_event_id(self, position: QPoint) -> str | None:
        item = self.itemAt(position)
        if item is None:
            current_item = self.currentItem()
            if current_item is not None:
                item = current_item
        if item is None:
            return None

        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is None:
            return None
        node_type, node_id = payload
        if node_type == "event":
            return str(node_id)
        return None

    def _nearest_ancestor_payload(self, item: QTreeWidgetItem | None, expected_type: str) -> tuple[str, str] | None:
        current_item = item
        while current_item is not None:
            payload = current_item.data(0, Qt.ItemDataRole.UserRole)
            if payload is not None and str(payload[0]) == expected_type:
                return str(payload[0]), str(payload[1])
            current_item = current_item.parent()
        return None

    def _find_item(self, node_type: str, node_id: str) -> QTreeWidgetItem | None:
        for root_index in range(self.topLevelItemCount()):
            found = self._find_item_recursive(self.topLevelItem(root_index), node_type, node_id)
            if found is not None:
                return found
        return None

    def _find_item_recursive(self, item: QTreeWidgetItem, node_type: str, node_id: str) -> QTreeWidgetItem | None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload == (node_type, node_id):
            return item
        for child_index in range(item.childCount()):
            found = self._find_item_recursive(item.child(child_index), node_type, node_id)
            if found is not None:
                return found
        return None

    def _apply_filter_recursive(self, item: QTreeWidgetItem, query: str) -> bool:
        own_match = not query or any(query in item.text(column).lower() for column in range(self.columnCount()))
        child_match = False
        for child_index in range(item.childCount()):
            child_match = self._apply_filter_recursive(item.child(child_index), query) or child_match

        visible = own_match or child_match
        item.setHidden(not visible)
        return visible

    def _visible_matching_event_items(self, query: str) -> list[QTreeWidgetItem]:
        matches: list[QTreeWidgetItem] = []
        for root_index in range(self.topLevelItemCount()):
            self._collect_visible_matching_events(self.topLevelItem(root_index), query, matches)
        return matches

    def _collect_visible_matching_events(self, item: QTreeWidgetItem, query: str, matches: list[QTreeWidgetItem]) -> None:
        if item.isHidden():
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is not None and payload[0] == "event":
            if self._item_or_descendant_matches(item, query):
                matches.append(item)
        for child_index in range(item.childCount()):
            self._collect_visible_matching_events(item.child(child_index), query, matches)

    def _item_or_descendant_matches(self, item: QTreeWidgetItem, query: str) -> bool:
        if any(query in item.text(column).lower() for column in range(self.columnCount())):
            return True
        for child_index in range(item.childCount()):
            if self._item_or_descendant_matches(item.child(child_index), query):
                return True
        return False