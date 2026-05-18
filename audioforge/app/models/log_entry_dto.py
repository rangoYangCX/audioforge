from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


_LEVEL_ALIASES = {
    "debug": "DEBUG",
    "info": "INFO",
    "warn": "WARNING",
    "warning": "WARNING",
    "error": "ERROR",
    "critical": "CRITICAL",
    "fatal": "CRITICAL",
}


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    return str(value)


def normalize_log_level(level: str) -> str:
    normalized = str(level or "INFO").strip().casefold()
    return _LEVEL_ALIASES.get(normalized, "INFO")


@dataclass(slots=True)
class ExperimentLogContext:
    workspace_path: str = ""
    task_id: str = ""
    task_name: str = ""
    variant_id: str = ""
    variant_name: str = ""
    lifecycle: str = ""
    action: str = ""
    base_project_path: str = ""
    variant_project_path: str = ""
    baseline_variant_id: str = ""
    baseline_variant_name: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace_path": self.workspace_path,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "variant_id": self.variant_id,
            "variant_name": self.variant_name,
            "lifecycle": self.lifecycle,
            "action": self.action,
            "base_project_path": self.base_project_path,
            "variant_project_path": self.variant_project_path,
            "baseline_variant_id": self.baseline_variant_id,
            "baseline_variant_name": self.baseline_variant_name,
        }

    def summary_text(self) -> str:
        parts: list[str] = []
        if self.task_name:
            parts.append(f"任务={self.task_name}")
        if self.variant_name:
            parts.append(f"方案={self.variant_name}")
        if self.lifecycle:
            parts.append(f"生命周期={self.lifecycle}")
        if self.action:
            parts.append(f"动作={self.action}")
        return " | ".join(parts)


@dataclass(slots=True)
class LogEntry:
    timestamp: str
    level: str
    subsystem: str
    message: str
    summary: str
    session_id: str
    correlation_id: str
    source: str = "desktop"
    project_name: str = ""
    project_path: str = ""
    target_type: str = ""
    target_id: str = ""
    operation_id: str = ""
    parent_operation_id: str = ""
    context: dict[str, object] = field(default_factory=dict)
    experiment_context: ExperimentLogContext | None = None

    def __post_init__(self) -> None:
        self.level = normalize_log_level(self.level)
        self.subsystem = str(self.subsystem or "general").strip() or "general"
        self.message = str(self.message or "").strip()
        self.summary = str(self.summary or self.message).strip() or self.message or "无摘要"
        self.session_id = str(self.session_id or "").strip()
        self.correlation_id = str(self.correlation_id or "").strip()
        self.source = str(self.source or "desktop").strip() or "desktop"
        self.project_name = str(self.project_name or "").strip()
        self.project_path = str(self.project_path or "").strip()
        self.target_type = str(self.target_type or "").strip()
        self.target_id = str(self.target_id or "").strip()
        self.operation_id = str(self.operation_id or "").strip()
        self.parent_operation_id = str(self.parent_operation_id or "").strip()
        self.timestamp = str(self.timestamp or datetime.now().isoformat(timespec="seconds")).strip()
        self.context = dict(self.context or {})

    @property
    def severity_state(self) -> str:
        return {
            "CRITICAL": "error",
            "ERROR": "error",
            "WARNING": "warning",
            "DEBUG": "info",
            "INFO": "info",
        }.get(self.level, "info")

    @property
    def is_failure(self) -> bool:
        return self.level in {"ERROR", "CRITICAL"}

    def as_dict(self) -> dict[str, object]:
        payload = {
            "timestamp": self.timestamp,
            "level": self.level,
            "subsystem": self.subsystem,
            "message": self.message,
            "summary": self.summary,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "operation_id": self.operation_id,
            "parent_operation_id": self.parent_operation_id,
            "context": _json_safe_value(self.context),
        }
        if self.experiment_context is not None:
            payload["experiment_context"] = _json_safe_value(self.experiment_context.as_dict())
        return payload

    def raw_line(self) -> str:
        parts = [self.timestamp, self.level, f"[{self.subsystem}]", self.message]
        if self.target_type and self.target_id:
            parts.append(f"target={self.target_type}:{self.target_id}")
        if self.correlation_id:
            parts.append(f"cid={self.correlation_id}")
        return " ".join(part for part in parts if part)

    def detail_text(self) -> str:
        lines = [
            f"时间：{self.timestamp}",
            f"级别：{self.level}",
            f"子系统：{self.subsystem}",
            f"来源：{self.source}",
            f"摘要：{self.summary}",
            f"消息：{self.message}",
            f"关联 ID：{self.correlation_id or '-'}",
            f"操作 ID：{self.operation_id or '-'}",
            f"父操作 ID：{self.parent_operation_id or '-'}",
            f"工程：{self.project_name or '-'}",
            f"工程路径：{self.project_path or '-'}",
            f"定位对象：{self.target_type + ':' + self.target_id if self.target_type and self.target_id else '-'}",
        ]
        if self.experiment_context is not None:
            lines.extend([
                "",
                "实验上下文：",
                self.experiment_context.summary_text() or "无",
                json.dumps(self.experiment_context.as_dict(), ensure_ascii=False, indent=2),
            ])
        if self.context:
            lines.extend([
                "",
                "结构化上下文：",
                json.dumps(_json_safe_value(self.context), ensure_ascii=False, indent=2, sort_keys=True),
            ])
        if self.target_type and self.target_id:
            lines.extend([
                "",
                "建议动作：",
                "双击左侧条目可尝试定位到对应对象。",
            ])
        return "\n".join(lines)
