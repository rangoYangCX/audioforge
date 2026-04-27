from __future__ import annotations

import copy
from dataclasses import dataclass

from audioforge.app.models.audio_project import AudioProject


@dataclass(slots=True)
class EditorSnapshot:
    project: AudioProject
    selected_event_id: str | None
    selected_folder_id: str | None


@dataclass(slots=True)
class HistoryEntry:
    description: str
    before: EditorSnapshot
    after: EditorSnapshot
    merge_key: str | None = None


class CommandHistory:
    def __init__(self) -> None:
        self._undo_stack: list[HistoryEntry] = []
        self._redo_stack: list[HistoryEntry] = []

    def capture(self, project: AudioProject, selected_event_id: str | None, selected_folder_id: str | None) -> EditorSnapshot:
        return EditorSnapshot(
            project=copy.deepcopy(project),
            selected_event_id=selected_event_id,
            selected_folder_id=selected_folder_id,
        )

    def push(
        self,
        description: str,
        before: EditorSnapshot,
        after: EditorSnapshot,
        merge_key: str | None = None,
    ) -> bool:
        if before == after:
            return False
        if merge_key and self._undo_stack and self._undo_stack[-1].merge_key == merge_key:
            previous_entry = self._undo_stack[-1]
            self._undo_stack[-1] = HistoryEntry(
                description=description,
                before=previous_entry.before,
                after=after,
                merge_key=merge_key,
            )
        else:
            self._undo_stack.append(
                HistoryEntry(description=description, before=before, after=after, merge_key=merge_key)
            )
        self._redo_stack.clear()
        return True

    def undo(self) -> EditorSnapshot | None:
        if not self._undo_stack:
            return None
        entry = self._undo_stack.pop()
        self._redo_stack.append(entry)
        return copy.deepcopy(entry.before)

    def redo(self) -> EditorSnapshot | None:
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        self._undo_stack.append(entry)
        return copy.deepcopy(entry.after)

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)