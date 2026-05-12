from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from audioforge.app.models.audio_project import AudioProject, ClipModel, EventModel
from audioforge.app.widgets.event_tree import EventTreeWidget
from audioforge.app.widgets.source_tree import SOURCE_ASSET_MIME_TYPE


class _DropEventStub:
    def __init__(self, mime_data: QMimeData) -> None:
        self._mime_data = mime_data
        self.accepted = False

    def mimeData(self) -> QMimeData:
        return self._mime_data

    class _Position:
        def toPoint(self):
            return None

    def position(self):
        return self._Position()

    def acceptProposedAction(self) -> None:
        self.accepted = True


def test_event_tree_extract_import_paths_accepts_directories_and_audio_files(tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    bundle_dir = tmp_path / "Ambience"
    bundle_dir.mkdir()
    audio_path = tmp_path / "Click.wav"
    unsupported_path = tmp_path / "Notes.txt"
    audio_path.write_bytes(b"RIFF")
    unsupported_path.write_text("skip", encoding="utf-8")

    mime_data = QMimeData()
    mime_data.setUrls(
        [
            QUrl.fromLocalFile(str(bundle_dir)),
            QUrl.fromLocalFile(str(audio_path)),
            QUrl.fromLocalFile(str(unsupported_path)),
        ]
    )

    tree = EventTreeWidget()
    import_paths = tree._extract_import_paths(_DropEventStub(mime_data))

    assert import_paths == [str(bundle_dir), str(audio_path)]


def test_event_tree_rebuild_uses_event_popup_instead_of_source_binding_children(tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    project = AudioProject.create_empty()
    root_folder_id = project.root_folder_ids[0]
    source_path = tmp_path / "ui" / "click.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"RIFF")
    event = EventModel(
        id="UI_Click_Normal",
        display_name="UI Click",
        clips=[ClipModel(id="click_main", source_path=str(source_path), export_path="ui/click_main", asset_key="ui/click_main")],
    )
    project.add_event(root_folder_id, event)

    tree = EventTreeWidget()
    tree.rebuild(project)

    event_item = tree._find_item("event", event.id)

    assert event_item is not None
    assert event_item.childCount() == 0
    assert event_item.childIndicatorPolicy() == event_item.ChildIndicatorPolicy.ShowIndicator
    assert event_item.icon(0).isNull() is False


def test_event_tree_expand_emits_bindings_popup_request(tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    project = AudioProject.create_empty()
    root_folder_id = project.root_folder_ids[0]
    source_path = tmp_path / "ui" / "click.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"RIFF")
    event = EventModel(
        id="UI_Click_Normal",
        display_name="UI Click",
        clips=[ClipModel(id="click_main", source_path=str(source_path), export_path="ui/click_main", asset_key="ui/click_main")],
    )
    project.add_event(root_folder_id, event)

    tree = EventTreeWidget()
    emitted: list[str] = []
    tree.rebuild(project)
    tree.eventBindingsPopupRequested.connect(lambda event_id, _pos: emitted.append(event_id))
    tree.show()
    QApplication.processEvents()

    event_item = tree._find_item("event", event.id)
    assert event_item is not None

    tree.expandItem(event_item)
    QApplication.processEvents()

    assert emitted == [event.id]
    assert event_item.isExpanded() is False


def test_event_tree_drop_source_assets_emits_target_event_signal(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    source_path = tmp_path / "ui" / "drag.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"RIFF")

    mime_data = QMimeData()
    mime_data.setData(SOURCE_ASSET_MIME_TYPE, str(source_path).encode("utf-8"))

    tree = EventTreeWidget()
    emitted: list[tuple[list[str], str]] = []
    tree.sourceAssetsDroppedToEvent.connect(lambda paths, event_id: emitted.append((list(paths), event_id)))
    monkeypatch.setattr(tree, "_resolve_drop_target_event_id", lambda position: "UI_Click_Normal")

    drop_event = _DropEventStub(mime_data)
    tree.dropEvent(drop_event)

    assert drop_event.accepted is True
    assert emitted == [([str(source_path)], "UI_Click_Normal")]