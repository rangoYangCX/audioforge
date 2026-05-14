from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication, QAbstractItemView

from audioforge.app.models.audio_project import AudioProject, ClipModel, EventModel
from audioforge.app.widgets.audio_tree import AudioTreeWidget
from audioforge.app.widgets.event_tree import EventTreeWidget
from audioforge.app.widgets.source_tree import SOURCE_ASSET_MIME_TYPE, SourceTreeWidget


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


def test_event_tree_rebuild_keeps_event_as_audio_navigation_entry(tmp_path: Path) -> None:
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


def test_event_tree_expand_emits_audio_navigation_request(tmp_path: Path) -> None:
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
    tree.eventAudioRequested.connect(lambda event_id: emitted.append(event_id))
    tree.show()
    QApplication.processEvents()

    event_item = tree._find_item("event", event.id)
    assert event_item is not None

    tree.expandItem(event_item)
    QApplication.processEvents()

    assert emitted == [event.id]
    assert event_item.isExpanded() is False


def test_event_tree_drop_source_assets_emits_target_audio_signal(monkeypatch, tmp_path: Path) -> None:
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
    tree.sourceAssetsDroppedToAudio.connect(lambda paths, event_id: emitted.append((list(paths), event_id)))
    monkeypatch.setattr(tree, "_resolve_drop_target_event_id", lambda position: "UI_Click_Normal")

    drop_event = _DropEventStub(mime_data)
    tree.dropEvent(drop_event)

    assert drop_event.accepted is True
    assert emitted == [([str(source_path)], "UI_Click_Normal")]


def test_source_tree_mime_data_includes_full_multi_selection_when_drag_starts_from_one_item(tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    source_a = tmp_path / "ui" / "drag_a.wav"
    source_b = tmp_path / "ui" / "drag_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF")

    tree = SourceTreeWidget(selection_mode=QAbstractItemView.SelectionMode.MultiSelection)
    tree.rebuild(
        [
            {"source_path": str(source_a), "event_ids": [], "asset_keys": [], "reference_count": 0, "missing": False, "unreferenced": True},
            {"source_path": str(source_b), "event_ids": [], "asset_keys": [], "reference_count": 0, "missing": False, "unreferenced": True},
        ]
    )
    tree.set_selected_source_paths([str(source_a), str(source_b)])

    mime_data = tree.mimeData([tree.currentItem()])
    payload = bytes(mime_data.data(SOURCE_ASSET_MIME_TYPE)).decode("utf-8", errors="ignore").splitlines()

    assert payload == [str(source_a), str(source_b)]


def test_audio_tree_programmatic_sync_does_not_emit_selection_signal() -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    tree = AudioTreeWidget()
    emitted: list[str] = []
    tree.audioSelected.connect(emitted.append)
    tree.rebuild(
        [
            {
                "audio_id": "audio_ui_click",
                "display_name": "UI Click Audio",
                "play_mode": "OneShot",
                "clip_count": 1,
                "event_count": 1,
                "event_ids": ["UI_Click_Normal"],
            },
            {
                "audio_id": "audio_ui_hover",
                "display_name": "UI Hover Audio",
                "play_mode": "Random",
                "clip_count": 2,
                "event_count": 1,
                "event_ids": ["UI_Hover"],
            },
        ]
    )
    tree.select_audio_id("audio_ui_hover")

    assert tree.current_audio_id() == "audio_ui_hover"
    assert emitted == []


def test_audio_tree_drop_external_files_emits_import_request(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    bundle_dir = tmp_path / "Ambience"
    bundle_dir.mkdir()
    audio_path = tmp_path / "Click.wav"
    audio_path.write_bytes(b"RIFF")

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(bundle_dir)), QUrl.fromLocalFile(str(audio_path))])

    tree = AudioTreeWidget()
    emitted: list[tuple[list[str], str | None]] = []
    tree.audioFilesDropped.connect(lambda paths, audio_id: emitted.append((list(paths), audio_id)))
    monkeypatch.setattr(tree, "_resolve_drop_target_audio_id", lambda position: None)

    drop_event = _DropEventStub(mime_data)
    tree.dropEvent(drop_event)

    assert drop_event.accepted is True
    assert emitted == [([str(bundle_dir), str(audio_path)], None)]


def test_audio_tree_drop_source_assets_emits_target_audio_signal(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    source_path = tmp_path / "ui" / "drag.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"RIFF")

    mime_data = QMimeData()
    mime_data.setData(SOURCE_ASSET_MIME_TYPE, str(source_path).encode("utf-8"))

    tree = AudioTreeWidget()
    emitted: list[tuple[list[str], str]] = []
    tree.sourceAssetsDroppedToAudio.connect(lambda paths, audio_id: emitted.append((list(paths), audio_id)))
    monkeypatch.setattr(tree, "_resolve_drop_target_audio_id", lambda position: "audio_ui_click")

    drop_event = _DropEventStub(mime_data)
    tree.dropEvent(drop_event)

    assert drop_event.accepted is True
    assert emitted == [([str(source_path)], "audio_ui_click")]


def test_source_tree_drop_external_files_emits_import_request(tmp_path: Path) -> None:
    app = QApplication.instance()
    if app is None:
        QApplication([])

    bundle_dir = tmp_path / "Library"
    bundle_dir.mkdir()
    audio_path = tmp_path / "LibraryClick.wav"
    audio_path.write_bytes(b"RIFF")

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(bundle_dir)), QUrl.fromLocalFile(str(audio_path))])

    tree = SourceTreeWidget()
    emitted: list[list[str]] = []
    tree.importFilesDropped.connect(lambda paths: emitted.append(list(paths)))

    drop_event = _DropEventStub(mime_data)
    tree.dropEvent(drop_event)

    assert drop_event.accepted is True
    assert emitted == [[str(bundle_dir), str(audio_path)]]