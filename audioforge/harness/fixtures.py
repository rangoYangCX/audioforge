from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, BusConfig, ClipModel, EventModel, MASTER_BUS_NAME, ProjectSettings
from audioforge.app.models.experiment_workspace import ExperimentWorkspace
from audioforge.app.services.experiment_serializer import ExperimentWorkspaceSerializer
from audioforge.app.services.project_serializer import ProjectSerializer


@dataclass(slots=True)
class HarnessProjectBundle:
    root_dir: Path
    project: AudioProject
    project_path: Path
    export_root: Path
    primary_source_path: Path
    extra_source_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "root_dir": str(self.root_dir),
            "project_path": str(self.project_path),
            "export_root": str(self.export_root),
            "primary_source_path": str(self.primary_source_path),
            "extra_source_paths": [str(path) for path in self.extra_source_paths],
        }


@dataclass(slots=True)
class HarnessWorkspaceBundle:
    root_dir: Path
    workspace: ExperimentWorkspace
    workspace_path: Path
    base_project_path: Path
    default_variant_path: Path
    task_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "root_dir": str(self.root_dir),
            "workspace_path": str(self.workspace_path),
            "base_project_path": str(self.base_project_path),
            "default_variant_path": str(self.default_variant_path),
            "task_id": self.task_id,
        }


def write_wav_fixture(path: Path, *, frequency_hz: float = 440.0, duration_seconds: float = 0.1, sample_rate: int = 22050) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(duration_seconds * sample_rate))
    amplitude = 0.35
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        for frame_index in range(frame_count):
            sample = amplitude * math.sin((2.0 * math.pi * frequency_hz * frame_index) / sample_rate)
            stream.writeframes(struct.pack("<h", int(sample * 32767)))
    return path


def build_sample_project(
    root_dir: Path,
    *,
    bus_volume_db: float = 0.0,
    event_volume_db: float = 0.0,
    runtime_audio_format: str = "wav",
) -> tuple[AudioProject, Path]:
    wav_path = write_wav_fixture(root_dir / "fixtures" / "ui_click.wav")

    project = AudioProject.create_empty(name="InternalReleaseSample")
    project.settings = ProjectSettings(
        default_bus="UI",
        export_root=str(root_dir / "Export"),
        buses=["BGM", "SFX", "UI"],
        bus_configs=[
            BusConfig(name=MASTER_BUS_NAME),
            BusConfig(name="BGM"),
            BusConfig(name="SFX"),
            BusConfig(name="UI", parent_bus="SFX", volume_db=bus_volume_db),
        ],
        source_audio_format="wav",
        runtime_audio_format=runtime_audio_format,
    )
    root_folder_id = project.root_folder_ids[0]
    clip = ClipModel.from_path(wav_path, "ui/click_primary")
    event = EventModel(
        id="UiClick",
        display_name="UI Click",
        bus="UI",
        volume_db=event_volume_db,
        clips=[clip],
    )
    project.add_event(root_folder_id, event)
    return project, wav_path


def save_sample_project(
    root_dir: Path,
    *,
    project_name: str = "HarnessSample",
    runtime_audio_format: str = "wav",
) -> HarnessProjectBundle:
    root_dir = Path(root_dir).resolve()
    export_root = root_dir / "Export"
    project_path = root_dir / f"{project_name}.afproj"

    project, _wav_path = build_sample_project(root_dir / "Seed", runtime_audio_format=runtime_audio_format)
    project.name = project_name
    project.settings.export_root = str(export_root)

    root_folder_id = project.root_folder_ids[0]
    hover_path = write_wav_fixture(root_dir / "Seed" / "fixtures" / "ui_hover.wav", frequency_hz=660.0)
    bgm_path = write_wav_fixture(root_dir / "Seed" / "fixtures" / "bgm_loop.wav", frequency_hz=220.0, duration_seconds=0.3)
    project.add_event(
        root_folder_id,
        EventModel(
            id="UIHover",
            display_name="UI Hover",
            bus="UI",
            volume_db=-2.0,
            clips=[ClipModel.from_path(hover_path, "ui/hover")],
        ),
    )
    project.add_event(
        root_folder_id,
        EventModel(
            id="BGMMenuLoop",
            display_name="BGM Menu Loop",
            bus="BGM",
            play_mode="Sequence",
            volume_db=-4.0,
            clips=[ClipModel.from_path(bgm_path, "bgm/menu_loop")],
        ),
    )

    ProjectSerializer().save(project, project_path)
    primary_source_path = Path(project.events["UiClick"].clips[0].source_path)
    extra_source_paths = (
        Path(project.events["UIHover"].clips[0].source_path),
        Path(project.events["BGMMenuLoop"].clips[0].source_path),
    )
    return HarnessProjectBundle(
        root_dir=root_dir,
        project=project,
        project_path=project_path,
        export_root=export_root,
        primary_source_path=primary_source_path,
        extra_source_paths=extra_source_paths,
    )


def create_workspace_from_base_project(
    root_dir: Path,
    base_project_path: Path,
    *,
    workspace_name: str = "HarnessWorkspace",
    task_name: str = "Harness Task",
    variant_name: str = "default",
) -> HarnessWorkspaceBundle:
    root_dir = Path(root_dir).resolve()
    workspace_path = root_dir / f"{workspace_name}.afws"
    workspace = ExperimentWorkspaceSerializer.create(
        workspace_path=workspace_path,
        base_project_path=Path(base_project_path),
        name=workspace_name,
    )
    task = ExperimentWorkspaceSerializer.create_task(workspace, task_name, variant_name=variant_name)
    ExperimentWorkspaceSerializer.save(workspace, workspace_path)
    default_variant_path = workspace.resolve_variant_copy_path(task.variants[0])
    return HarnessWorkspaceBundle(
        root_dir=root_dir,
        workspace=workspace,
        workspace_path=workspace_path,
        base_project_path=Path(base_project_path).resolve(),
        default_variant_path=default_variant_path,
        task_id=task.id,
    )


def create_sample_workspace(
    root_dir: Path,
    *,
    project_name: str = "HarnessBaseProject",
    workspace_name: str = "HarnessWorkspace",
    task_name: str = "Harness Task",
    variant_name: str = "default",
) -> tuple[HarnessProjectBundle, HarnessWorkspaceBundle]:
    root_dir = Path(root_dir).resolve()
    project_bundle = save_sample_project(root_dir / "base_project", project_name=project_name)
    workspace_bundle = create_workspace_from_base_project(
        root_dir / "workspace",
        project_bundle.project_path,
        workspace_name=workspace_name,
        task_name=task_name,
        variant_name=variant_name,
    )
    return project_bundle, workspace_bundle