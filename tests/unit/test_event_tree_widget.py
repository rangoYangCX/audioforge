from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from audioforge.app.widgets.event_tree import EventTreeWidget


class _DropEventStub:
    def __init__(self, mime_data: QMimeData) -> None:
        self._mime_data = mime_data

    def mimeData(self) -> QMimeData:
        return self._mime_data


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