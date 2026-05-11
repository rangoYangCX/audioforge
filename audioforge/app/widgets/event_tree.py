from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from audioforge.app.models.audio_project import AudioProject
from audioforge.app.utils.icons import load_app_icon


class EventTreeWidget(QTreeWidget):
    eventSelected = Signal(str)
    nodeSelected = Signal(str, str)
    nodesSelectionChanged = Signal(list)
    nodeMoved = Signal(str, str, object, int)
    audioFilesDropped = Signal(list, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._analysis_status: dict[str, dict[str, str]] = {}
        self.setColumnCount(3)
        self.setHeaderLabels(["名称", "类型", "内容"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setAcceptDrops(True)
        self.itemSelectionChanged.connect(self._emit_selected_event)

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

    def rebuild(self, project: AudioProject) -> None:
        self.clear()
        for folder_id in project.root_folder_ids:
            folder_item = self._build_folder_item(project, folder_id, is_root=True)
            self.addTopLevelItem(folder_item)
        self.expandAll()

    def set_analysis_status(self, status_map: dict[str, dict[str, str]]) -> None:
        self._analysis_status = dict(status_map)
        for root_index in range(self.topLevelItemCount()):
            self._apply_status_recursive(self.topLevelItem(root_index))

    def select_node(self, node_type: str, node_id: str) -> None:
        self.select_nodes([(node_type, node_id)], current_node=(node_type, node_id))

    def select_nodes(self, nodes: list[tuple[str, str]], current_node: tuple[str, str] | None = None) -> None:
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
            self.expandAll()

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
        return [node_id for node_type, node_id in self.selected_payloads() if node_type == "event"]

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

        for child_folder_id in folder.child_folder_ids:
            item.addChild(self._build_folder_item(project, child_folder_id))
        for event_id in folder.child_event_ids:
            event = project.events[event_id]
            event_item = QTreeWidgetItem([event.display_name or event_id, "Event", event_id])
            event_item.setData(0, Qt.ItemDataRole.UserRole, ("event", event_id))
            event_item.setIcon(0, load_app_icon("event"))
            self._apply_status_to_item(event_item, event_id)
            item.addChild(event_item)
        return item

    def _apply_status_recursive(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is not None and payload[0] == "event":
            self._apply_status_to_item(item, payload[1])
        for child_index in range(item.childCount()):
            self._apply_status_recursive(item.child(child_index))

    def _apply_status_to_item(self, item: QTreeWidgetItem, event_id: str) -> None:
        status = self._analysis_status.get(event_id)
        if not status:
            item.setText(2, event_id)
            item.setForeground(0, Qt.GlobalColor.white)
            item.setToolTip(0, "")
            return
        level = status.get("level", "warning")
        summary = status.get("summary", "")
        item.setText(2, summary)
        item.setToolTip(0, summary)
        color = Qt.GlobalColor.red if level == "error" else Qt.GlobalColor.yellow
        item.setForeground(0, color)

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
        dropped_paths = self._extract_import_paths(event)
        if dropped_paths:
            target_folder_id = self._resolve_drop_target_folder_id(event.position().toPoint())
            self.audioFilesDropped.emit(dropped_paths, target_folder_id)
            event.acceptProposedAction()
            return

        moved_item = self.currentItem()
        if moved_item is None:
            super().dropEvent(event)
            return

        node_type, node_id = moved_item.data(0, Qt.ItemDataRole.UserRole)
        super().dropEvent(event)

        moved_item = self._find_item(node_type, node_id)
        if moved_item is None:
            return

        parent_item = moved_item.parent()
        parent_payload = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item is not None else None
        parent_folder_id = None if parent_payload is None else parent_payload[1]
        index = self.indexOfTopLevelItem(moved_item) if parent_item is None else parent_item.indexOfChild(moved_item)
        self.nodeMoved.emit(node_type, node_id, parent_folder_id, index)

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
        parent_item = item.parent()
        if parent_item is None:
            return None
        parent_payload = parent_item.data(0, Qt.ItemDataRole.UserRole)
        return None if parent_payload is None else parent_payload[1]

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
            if any(query in item.text(column).lower() for column in range(self.columnCount())):
                matches.append(item)
        for child_index in range(item.childCount()):
            self._collect_visible_matching_events(item.child(child_index), query, matches)