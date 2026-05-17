"""AB 实验工作区数据模型。

ExperimentWorkspace（套壳工程）管理底板工程 + 实验任务列表。
每个 ExperimentVariant 持有一份底板 .afproj 的文件副本，独立编辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from audioforge.app.models.audio_project import new_id, utc_now_iso


class ExperimentLifecycle(str, Enum):
    """实验/方案生命周期。"""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    MERGED = "merged"


@dataclass(slots=True)
class ExperimentVariant:
    """实验方案——独立拥有一份底板工程副本。

    每个方案对应一份底板 .afproj 的副本文件，用户编辑的
    就是这份副本。导出时与原底板对比产生增量 JSON。
    """

    id: str
    name: str
    lifecycle: ExperimentLifecycle = ExperimentLifecycle.DRAFT
    base_project_copy_path: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at
        if isinstance(self.lifecycle, str):
            self.lifecycle = ExperimentLifecycle(self.lifecycle)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "Id": self.id,
            "Name": self.name,
            "Lifecycle": self.lifecycle.value,
            "BaseProjectCopyPath": self.base_project_copy_path,
            "Notes": self.notes,
            "CreatedAt": self.created_at,
            "UpdatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentVariant:
        return cls(
            id=str(data.get("Id", "")),
            name=str(data.get("Name", "")),
            lifecycle=str(data.get("Lifecycle", "draft")),
            base_project_copy_path=str(data.get("BaseProjectCopyPath", "")),
            notes=str(data.get("Notes", "")),
            created_at=str(data.get("CreatedAt", "")),
            updated_at=str(data.get("UpdatedAt", "")),
        )


@dataclass(slots=True)
class ExperimentTask:
    """实验任务——策划视角的实验单元。

    一个任务可包含多个方案（Variant），导出时每个方案独立产出
    增量 JSON。variants 列表长度为 1 时视为无子方案（单方案）。
    """

    id: str
    name: str
    variants: list[ExperimentVariant] = field(default_factory=list)
    active_variant_index: int = 0
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def active_variant(self) -> ExperimentVariant | None:
        if 0 <= self.active_variant_index < len(self.variants):
            return self.variants[self.active_variant_index]
        return None

    @property
    def baseline_variant(self) -> ExperimentVariant | None:
        if self.variants:
            return self.variants[0]
        return None

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "Id": self.id,
            "Name": self.name,
            "ActiveVariantIndex": self.active_variant_index,
            "Variants": [v.to_dict() for v in self.variants],
            "Notes": self.notes,
            "CreatedAt": self.created_at,
            "UpdatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentTask:
        variants = [
            ExperimentVariant.from_dict(v)
            for v in (data.get("Variants") or [])
        ]
        return cls(
            id=str(data.get("Id", "")),
            name=str(data.get("Name", "")),
            variants=variants,
            active_variant_index=int(data.get("ActiveVariantIndex", 0)),
            notes=str(data.get("Notes", "")),
            created_at=str(data.get("CreatedAt", "")),
            updated_at=str(data.get("UpdatedAt", "")),
        )


WORKSPACE_SCHEMA_VERSION = 1


@dataclass(slots=True)
class ExperimentWorkspace:
    """实验工作区——套壳工程。

    管理一个底板工程引用和多个实验任务。文件格式为 .afws (JSON)。
    """

    name: str
    file_path: str = ""
    base_project_path: str = ""
    source_audio_root: str = ""
    tasks: list[ExperimentTask] = field(default_factory=list)
    active_task_index: int = 0
    schema_version: int = WORKSPACE_SCHEMA_VERSION
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def active_task(self) -> ExperimentTask | None:
        if 0 <= self.active_task_index < len(self.tasks):
            return self.tasks[self.active_task_index]
        return None

    @property
    def active_variant(self) -> ExperimentVariant | None:
        task = self.active_task
        return task.active_variant if task else None

    @property
    def workspace_dir(self) -> Path:
        file_path = Path(self.file_path) if self.file_path else Path(".")
        return file_path.resolve().parent

    @property
    def base_project_abs_path(self) -> Path:
        return (self.workspace_dir / self.base_project_path).resolve()

    def resolve_variant_copy_path(self, variant: ExperimentVariant) -> Path:
        return (self.workspace_dir / variant.base_project_copy_path).resolve()

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "SchemaVersion": self.schema_version,
            "Type": "ExperimentWorkspace",
            "Name": self.name,
            "BaseProjectPath": self.base_project_path,
            "SourceAudioRoot": self.source_audio_root,
            "Tasks": [t.to_dict() for t in self.tasks],
            "ActiveTaskIndex": self.active_task_index,
            "Notes": self.notes,
            "CreatedAt": self.created_at,
            "UpdatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentWorkspace:
        tasks = [
            ExperimentTask.from_dict(t)
            for t in (data.get("Tasks") or [])
        ]
        return cls(
            name=str(data.get("Name", "")),
            base_project_path=str(data.get("BaseProjectPath", "")),
            source_audio_root=str(data.get("SourceAudioRoot", "")),
            tasks=tasks,
            active_task_index=int(data.get("ActiveTaskIndex", 0)),
            schema_version=int(data.get("SchemaVersion", WORKSPACE_SCHEMA_VERSION)),
            notes=str(data.get("Notes", "")),
            created_at=str(data.get("CreatedAt", "")),
            updated_at=str(data.get("UpdatedAt", "")),
        )

    def find_task(self, task_id: str) -> ExperimentTask | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def find_variant(self, variant_id: str) -> tuple[ExperimentTask, ExperimentVariant] | None:
        for task in self.tasks:
            for variant in task.variants:
                if variant.id == variant_id:
                    return task, variant
        return None


def new_variant_id() -> str:
    return new_id("variant")


def new_task_id() -> str:
    return new_id("task")
