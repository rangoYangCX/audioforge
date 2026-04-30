from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from audioforge.app.utils.constants import DEFAULT_BUSES, DEFAULT_PROJECT_NAME, PROJECT_VERSION

PlayMode = Literal["Random", "Sequence", "Combo"]
StealPolicy = Literal["RejectNew", "StopOldest", "StopQuietest"]
LoadPolicy = Literal["OnDemand", "Preload", "Stream"]
Severity = Literal["Error", "Warning", "Info"]
MASTER_BUS_NAME = "Master"


def normalize_bus_names(bus_names: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in bus_names or []:
        bus_name = str(raw_name).strip()
        if not bus_name:
            continue
        key = bus_name.casefold()
        if key in seen:
            continue
        normalized.append(bus_name)
        seen.add(key)
    return normalized or list(DEFAULT_BUSES)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


@dataclass(slots=True)
class ClipModel:
    id: str
    source_path: str
    export_path: str
    asset_key: str
    weight: int = 1
    trim_start_ms: int = 0
    trim_end_ms: int = 0
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    loop_start_ms: int = 0
    loop_end_ms: int = 0
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_path(cls, source_path: Path, asset_key: str) -> "ClipModel":
        return cls(
            id=source_path.stem,
            source_path=str(source_path),
            export_path=asset_key,
            asset_key=asset_key.replace("\\", "/"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AssetRegistryEntry:
    source_path: str
    discovered_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EventModel:
    id: str
    display_name: str = ""
    bus: str = "SFX"
    play_mode: PlayMode = "Random"
    avoid_immediate_repeat: bool = False
    volume_db: float = 0.0
    volume_rand_min_db: float = 0.0
    volume_rand_max_db: float = 0.0
    pitch_cents: int = 0
    pitch_rand_min_cents: int = 0
    pitch_rand_max_cents: int = 0
    max_instances: int = 0
    cooldown_seconds: float = 0.0
    steal_policy: StealPolicy = "RejectNew"
    combo_pitch_step_cents: int = 100
    combo_reset_seconds: float = 1.5
    combo_max_step: int = 0
    load_policy: LoadPolicy = "OnDemand"
    clips: list[ClipModel] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["clips"] = [clip.to_dict() for clip in self.clips]
        return payload


@dataclass(slots=True)
class FolderModel:
    id: str
    name: str
    child_folder_ids: list[str] = field(default_factory=list)
    child_event_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BusConfig:
    name: str
    parent_bus: str = MASTER_BUS_NAME
    volume_db: float = 0.0
    is_muted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "Name": self.name,
            "ParentBus": self.parent_bus,
            "VolumeDb": self.volume_db,
            "IsMuted": self.is_muted,
        }


def default_bus_configs() -> list[BusConfig]:
    return [BusConfig(name=MASTER_BUS_NAME)] + [BusConfig(name=bus_name) for bus_name in DEFAULT_BUSES]


def normalize_bus_configs(bus_configs: list[BusConfig] | None, fallback_bus_names: list[str] | None = None) -> list[BusConfig]:
    master_config = BusConfig(name=MASTER_BUS_NAME)
    normalized: list[BusConfig] = []
    seen: set[str] = set()
    source_configs = bus_configs or [BusConfig(name=bus_name) for bus_name in normalize_bus_names(fallback_bus_names)]
    for config in source_configs:
        bus_name = str(config.name).strip()
        if not bus_name:
            continue
        key = bus_name.casefold()
        if key in seen:
            continue
        if key == MASTER_BUS_NAME.casefold():
            master_config = BusConfig(
                name=MASTER_BUS_NAME,
                parent_bus=MASTER_BUS_NAME,
                volume_db=float(config.volume_db),
                is_muted=bool(config.is_muted),
            )
            seen.add(key)
            continue
        normalized.append(
            BusConfig(
                name=bus_name,
                parent_bus=str(getattr(config, "parent_bus", MASTER_BUS_NAME) or MASTER_BUS_NAME).strip() or MASTER_BUS_NAME,
                volume_db=float(config.volume_db),
                is_muted=bool(config.is_muted),
            )
        )
        seen.add(key)
    valid_bus_names = {config.name.casefold() for config in normalized}
    for config in normalized:
        parent_bus = str(config.parent_bus).strip() or MASTER_BUS_NAME
        if parent_bus.casefold() == config.name.casefold() or parent_bus.casefold() not in {MASTER_BUS_NAME.casefold(), *valid_bus_names}:
            config.parent_bus = MASTER_BUS_NAME
        elif parent_bus.casefold() == MASTER_BUS_NAME.casefold():
            config.parent_bus = MASTER_BUS_NAME
        else:
            for candidate in normalized:
                if candidate.name.casefold() == parent_bus.casefold():
                    config.parent_bus = candidate.name
                    break
    if not normalized:
        normalized = [BusConfig(name=bus_name) for bus_name in DEFAULT_BUSES]
    return [master_config, *normalized]


@dataclass(slots=True)
class ProjectSettings:
    default_bus: str = "SFX"
    supported_formats: list[str] = field(default_factory=lambda: ["wav", "ogg"])
    export_root: str = "./Export"
    buses: list[str] = field(default_factory=lambda: list(DEFAULT_BUSES))
    bus_configs: list[BusConfig] = field(default_factory=default_bus_configs)
    source_audio_format: str = "wav"
    runtime_audio_format: str = "ogg"

    def __post_init__(self) -> None:
        self.bus_configs = normalize_bus_configs(self.bus_configs, self.buses)
        self.buses = [config.name for config in self.bus_configs if config.name != MASTER_BUS_NAME]
        if self.default_bus not in self.buses:
            self.default_bus = self.buses[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "DefaultBus": self.default_bus,
            "SupportedFormats": list(self.supported_formats),
            "ExportRoot": self.export_root,
            "Buses": list(self.buses),
            "BusConfigs": [config.to_dict() for config in self.bus_configs],
            "SourceAudioFormat": self.source_audio_format,
            "RuntimeAudioFormat": self.runtime_audio_format,
        }


@dataclass(slots=True)
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    target: str


@dataclass(slots=True)
class AudioProject:
    name: str = DEFAULT_PROJECT_NAME
    project_version: int = PROJECT_VERSION
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    root_folder_ids: list[str] = field(default_factory=list)
    folders: dict[str, FolderModel] = field(default_factory=dict)
    events: dict[str, EventModel] = field(default_factory=dict)
    asset_registry: dict[str, AssetRegistryEntry] = field(default_factory=dict)
    file_path: str | None = None

    @classmethod
    def create_empty(cls, name: str = DEFAULT_PROJECT_NAME) -> "AudioProject":
        project = cls(name=name)
        root_folder = FolderModel(id=new_id("folder"), name="Default Work Unit")
        project.folders[root_folder.id] = root_folder
        project.root_folder_ids.append(root_folder.id)
        return project

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def register_source_asset(self, source_path: str) -> None:
        normalized = str(source_path).strip()
        if not normalized:
            return
        if normalized not in self.asset_registry:
            self.asset_registry[normalized] = AssetRegistryEntry(source_path=normalized)
            self.touch()

    def add_event(self, folder_id: str, event: EventModel) -> None:
        self.events[event.id] = event
        self.folders[folder_id].child_event_ids.append(event.id)
        for clip in event.clips:
            self.register_source_asset(clip.source_path)
        self.touch()

    def move_event(self, event_id: str, target_folder_id: str, target_index: int | None = None) -> None:
        if event_id not in self.events:
            raise KeyError(event_id)
        if target_folder_id not in self.folders:
            raise KeyError(target_folder_id)

        current_folder_id = self.find_event_folder_id(event_id)
        if current_folder_id is None:
            raise KeyError(event_id)

        source_children = self.folders[current_folder_id].child_event_ids
        source_children.remove(event_id)
        target_children = self.folders[target_folder_id].child_event_ids
        if target_index is None or target_index < 0 or target_index > len(target_children):
            target_children.append(event_id)
        else:
            target_children.insert(target_index, event_id)
        self.touch()

    def rename_event(self, old_id: str, new_id: str) -> None:
        if old_id not in self.events:
            raise KeyError(old_id)
        if old_id == new_id:
            return
        if new_id in self.events:
            raise ValueError(f"Event ID already exists: {new_id}")

        event = self.events.pop(old_id)
        event.id = new_id
        self.events[new_id] = event

        folder_id = self.find_event_folder_id(old_id)
        if folder_id is not None:
            child_event_ids = self.folders[folder_id].child_event_ids
            self.folders[folder_id].child_event_ids = [new_id if event_id == old_id else event_id for event_id in child_event_ids]
        self.touch()

    def remove_event(self, event_id: str) -> None:
        if event_id not in self.events:
            raise KeyError(event_id)

        folder_id = self.find_event_folder_id(event_id)
        if folder_id is not None:
            child_event_ids = self.folders[folder_id].child_event_ids
            self.folders[folder_id].child_event_ids = [child_id for child_id in child_event_ids if child_id != event_id]

        del self.events[event_id]
        self.touch()

    def add_folder(self, parent_folder_id: str | None, folder: FolderModel) -> None:
        self.folders[folder.id] = folder
        if parent_folder_id is None:
            self.root_folder_ids.append(folder.id)
        else:
            self.folders[parent_folder_id].child_folder_ids.append(folder.id)
        self.touch()

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        if folder_id not in self.folders:
            raise KeyError(folder_id)
        self.folders[folder_id].name = new_name
        self.touch()

    def move_folder(self, folder_id: str, target_parent_folder_id: str | None, target_index: int | None = None) -> None:
        if folder_id not in self.folders:
            raise KeyError(folder_id)
        if target_parent_folder_id is not None and target_parent_folder_id not in self.folders:
            raise KeyError(target_parent_folder_id)
        if target_parent_folder_id == folder_id or self.is_folder_descendant(target_parent_folder_id, folder_id):
            raise ValueError("Cannot move a folder into itself or one of its descendants.")

        current_parent_folder_id = self.find_folder_parent_id(folder_id)
        if current_parent_folder_id is None:
            self.root_folder_ids = [root_id for root_id in self.root_folder_ids if root_id != folder_id]
        else:
            current_parent = self.folders[current_parent_folder_id]
            current_parent.child_folder_ids = [child_id for child_id in current_parent.child_folder_ids if child_id != folder_id]

        if target_parent_folder_id is None:
            target_children = self.root_folder_ids
        else:
            target_children = self.folders[target_parent_folder_id].child_folder_ids

        if target_index is None or target_index < 0 or target_index > len(target_children):
            target_children.append(folder_id)
        else:
            target_children.insert(target_index, folder_id)
        self.touch()

    def remove_folder(self, folder_id: str) -> None:
        if folder_id not in self.folders:
            raise KeyError(folder_id)

        folder = self.folders[folder_id]
        for child_event_id in list(folder.child_event_ids):
            self.remove_event(child_event_id)
        for child_folder_id in list(folder.child_folder_ids):
            self.remove_folder(child_folder_id)

        parent_folder_id = self.find_folder_parent_id(folder_id)
        if parent_folder_id is None:
            self.root_folder_ids = [root_id for root_id in self.root_folder_ids if root_id != folder_id]
        else:
            parent = self.folders[parent_folder_id]
            parent.child_folder_ids = [child_id for child_id in parent.child_folder_ids if child_id != folder_id]

        del self.folders[folder_id]

        if not self.root_folder_ids and not self.folders:
            default_folder = FolderModel(id=new_id("folder"), name="Default Work Unit")
            self.folders[default_folder.id] = default_folder
            self.root_folder_ids.append(default_folder.id)
        self.touch()

    def add_clip_to_event(self, event_id: str, clip: ClipModel) -> None:
        self.events[event_id].clips.append(clip)
        self.register_source_asset(clip.source_path)
        self.touch()

    def sync_asset_registry(self) -> None:
        for event in self.events.values():
            for clip in event.clips:
                normalized = str(clip.source_path).strip()
                if normalized and normalized not in self.asset_registry:
                    self.asset_registry[normalized] = AssetRegistryEntry(source_path=normalized)

    def remove_clip_from_event(self, event_id: str, clip_id: str) -> None:
        event = self.events[event_id]
        event.clips = [clip for clip in event.clips if clip.id != clip_id]
        self.touch()

    def find_event_folder_id(self, event_id: str) -> str | None:
        for folder_id, folder in self.folders.items():
            if event_id in folder.child_event_ids:
                return folder_id
        return None

    def find_folder_parent_id(self, folder_id: str) -> str | None:
        for parent_id, folder in self.folders.items():
            if folder_id in folder.child_folder_ids:
                return parent_id
        return None

    def is_folder_descendant(self, folder_id: str | None, ancestor_folder_id: str) -> bool:
        if folder_id is None:
            return False
        current_parent_id = self.find_folder_parent_id(folder_id)
        while current_parent_id is not None:
            if current_parent_id == ancestor_folder_id:
                return True
            current_parent_id = self.find_folder_parent_id(current_parent_id)
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ProjectVersion": self.project_version,
            "ProjectName": self.name,
            "CreatedAt": self.created_at,
            "UpdatedAt": self.updated_at,
            "Settings": self.settings.to_dict(),
            "Tree": {
                "RootFolderIds": list(self.root_folder_ids),
                "Folders": {folder_id: folder.to_dict() for folder_id, folder in self.folders.items()},
            },
            "Events": {event_id: event.to_dict() for event_id, event in self.events.items()},
            "Assets": {source_path: entry.to_dict() for source_path, entry in self.asset_registry.items()},
        }


def project_from_dict(payload: dict[str, Any], file_path: str | None = None) -> AudioProject:
    settings_payload = payload.get("Settings", {})
    tree_payload = payload.get("Tree", {})
    bus_config_payloads = settings_payload.get("BusConfigs", [])
    bus_configs = [
        BusConfig(
            name=str(bus_payload.get("Name", "")).strip(),
            parent_bus=str(bus_payload.get("ParentBus", MASTER_BUS_NAME)).strip() or MASTER_BUS_NAME,
            volume_db=float(bus_payload.get("VolumeDb", 0.0)),
            is_muted=bool(bus_payload.get("IsMuted", False)),
        )
        for bus_payload in bus_config_payloads
        if isinstance(bus_payload, dict)
    ]
    project = AudioProject(
        name=payload.get("ProjectName", DEFAULT_PROJECT_NAME),
        project_version=payload.get("ProjectVersion", PROJECT_VERSION),
        created_at=payload.get("CreatedAt", utc_now_iso()),
        updated_at=payload.get("UpdatedAt", utc_now_iso()),
        settings=ProjectSettings(
            default_bus=settings_payload.get("DefaultBus", "SFX"),
            supported_formats=settings_payload.get("SupportedFormats", ["wav", "ogg"]),
            export_root=settings_payload.get("ExportRoot", "./Export"),
            buses=settings_payload.get("Buses", list(DEFAULT_BUSES)),
            bus_configs=bus_configs,
            source_audio_format=settings_payload.get("SourceAudioFormat", "wav"),
            runtime_audio_format=settings_payload.get("RuntimeAudioFormat", "ogg"),
        ),
        root_folder_ids=list(tree_payload.get("RootFolderIds", [])),
        file_path=file_path,
    )

    asset_payloads = payload.get("Assets", {})
    for source_path, asset_data in asset_payloads.items():
        if not isinstance(asset_data, dict):
            continue
        normalized = str(asset_data.get("source_path", source_path)).strip() or str(source_path).strip()
        if not normalized:
            continue
        project.asset_registry[normalized] = AssetRegistryEntry(
            source_path=normalized,
            discovered_at=str(asset_data.get("discovered_at", utc_now_iso())),
        )

    folder_payloads = tree_payload.get("Folders", {})
    for folder_id, folder_data in folder_payloads.items():
        project.folders[folder_id] = FolderModel(
            id=folder_id,
            name=folder_data["name"],
            child_folder_ids=list(folder_data.get("child_folder_ids", [])),
            child_event_ids=list(folder_data.get("child_event_ids", [])),
        )

    event_payloads = payload.get("Events", {})
    for event_id, event_data in event_payloads.items():
        clips = [ClipModel(**clip_payload) for clip_payload in event_data.get("clips", [])]
        project.events[event_id] = EventModel(
            id=event_id,
            display_name=event_data.get("display_name", ""),
            bus=event_data.get("bus", "SFX"),
            play_mode=event_data.get("play_mode", "Random"),
            avoid_immediate_repeat=event_data.get("avoid_immediate_repeat", False),
            volume_db=event_data.get("volume_db", 0.0),
            volume_rand_min_db=event_data.get("volume_rand_min_db", 0.0),
            volume_rand_max_db=event_data.get("volume_rand_max_db", 0.0),
            pitch_cents=event_data.get("pitch_cents", 0),
            pitch_rand_min_cents=event_data.get("pitch_rand_min_cents", 0),
            pitch_rand_max_cents=event_data.get("pitch_rand_max_cents", 0),
            max_instances=event_data.get("max_instances", 0),
            cooldown_seconds=event_data.get("cooldown_seconds", 0.0),
            steal_policy=event_data.get("steal_policy", "RejectNew"),
            combo_pitch_step_cents=event_data.get("combo_pitch_step_cents", 100),
            combo_reset_seconds=event_data.get("combo_reset_seconds", 1.5),
            combo_max_step=event_data.get("combo_max_step", 0),
            load_policy=event_data.get("load_policy", "OnDemand"),
            clips=clips,
            notes=event_data.get("notes", ""),
        )

    if not project.root_folder_ids and not project.folders:
        default_folder = FolderModel(id=new_id("folder"), name="Default Work Unit")
        project.folders[default_folder.id] = default_folder
        project.root_folder_ids.append(default_folder.id)

    project.sync_asset_registry()

    return project