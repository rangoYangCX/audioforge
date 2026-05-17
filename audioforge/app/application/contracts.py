from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from audioforge.app.models.audio_project import AudioProject


NotificationLevel = Literal["info", "warning", "error"]
FileDialogMode = Literal["open_file", "save_file", "open_directory"]

T = TypeVar("T")


@dataclass(slots=True)
class UserNotification:
    level: NotificationLevel
    title: str
    message: str
    log_message: str | None = None


@dataclass(slots=True)
class ConfirmationRequest:
    title: str
    message: str
    default_accept: bool = False


@dataclass(slots=True)
class ChoiceOption:
    value: str
    label: str
    is_cancel: bool = False


@dataclass(slots=True)
class ChoiceRequest:
    title: str
    message: str
    informative_text: str = ""
    options: list[ChoiceOption] = field(default_factory=list)


@dataclass(slots=True)
class FileDialogRequest:
    mode: FileDialogMode
    title: str
    initial_path: str = ""
    file_filter: str = ""
    default_name: str = ""


@dataclass(slots=True)
class ProjectSessionState:
    project: AudioProject
    selected_event_id: str | None
    selected_event_ids: list[str]
    selected_folder_id: str | None
    selected_audio_id: str | None
    selected_source_binding_tokens: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AutosavePreferences:
    enabled: bool
    interval_minutes: int


@dataclass(slots=True)
class WorkflowResult(Generic[T]):
    success: bool
    value: T | None = None
    notifications: list[UserNotification] = field(default_factory=list)
    cancelled: bool = False