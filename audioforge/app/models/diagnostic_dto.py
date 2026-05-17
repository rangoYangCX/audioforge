"""诊断数据传输对象（DTO）。

从 controllers/main_controller.py 提取至 models 层，
解除 View → Controller 的跨层数据耦合。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIAGNOSTIC_FALLBACK_SUMMARY = "诊断概览已接入结果中心；等待新的日志、校验、构建或响度结果。"
DIAGNOSTIC_SECTION_DEFAULTS = {
    "log": "最近日志：等待运行输出。",
    "validation": "等待校验。",
    "build": "等待构建或差异预览。",
    "loudness": "等待响度扫描。",
    "bus": "等待 Bus 上下文。",
}
DIAGNOSTIC_PRIORITY_ORDER = ("validation", "build", "loudness", "bus", "log")
DIAGNOSTIC_SECTION_TITLES = {
    "validation": "校验",
    "build": "构建",
    "loudness": "响度",
    "bus": "Bus 状态",
    "log": "日志",
}


@dataclass(slots=True)
class DiagnosticSection:
    name: str
    default_summary: str
    summary: str = ""
    detail: str = ""
    status: str = "idle"
    target_type: str = ""
    target_id: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary:
            self.summary = self.default_summary
        if not self.detail:
            self.detail = self.summary

    def reset(self) -> None:
        self.summary = self.default_summary
        self.detail = self.default_summary
        self.status = "idle"
        self.target_type = ""
        self.target_id = ""
        self.metadata = {}

    def update(
        self,
        *,
        summary: str,
        detail: str | None = None,
        status: str = "info",
        target_type: str = "",
        target_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        normalized_summary = summary.strip() or self.default_summary
        normalized_detail = (detail if detail is not None else normalized_summary).strip() or normalized_summary
        self.summary = normalized_summary
        self.detail = normalized_detail
        self.status = status
        self.target_type = target_type.strip()
        self.target_id = target_id.strip()
        self.metadata = dict(metadata or {})


def _create_default_diagnostic_sections() -> dict[str, DiagnosticSection]:
    return {
        name: DiagnosticSection(name=name, default_summary=default_summary)
        for name, default_summary in DIAGNOSTIC_SECTION_DEFAULTS.items()
    }


@dataclass(slots=True)
class DiagnosticSnapshot:
    summary: str = DIAGNOSTIC_FALLBACK_SUMMARY
    sections: dict[str, DiagnosticSection] = field(default_factory=_create_default_diagnostic_sections)

    def section(self, name: str) -> DiagnosticSection:
        return self.sections[name]

    def as_payload(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "log_summary": self.section("log").summary,
            "validation_summary": self.section("validation").summary,
            "build_summary": self.section("build").summary,
            "loudness_summary": self.section("loudness").summary,
            "bus_summary": self.section("bus").summary,
        }