from __future__ import annotations

from audioforge.app.models.log_entry_dto import ExperimentLogContext, LogEntry
from audioforge.app.services.log_store import LogQuery, LogStore


def _entry(
    message: str,
    *,
    level: str = "INFO",
    subsystem: str = "general",
    source: str = "desktop",
    experiment: bool = False,
) -> LogEntry:
    return LogEntry(
        timestamp="2026-05-18T12:00:00",
        level=level,
        subsystem=subsystem,
        message=message,
        summary=message,
        session_id="session-1",
        correlation_id=f"cid-{subsystem}-{level}",
        source=source,
        context={"message": message},
        experiment_context=(
            ExperimentLogContext(task_name="任务A", variant_name="方案1", action="导出增量") if experiment else None
        ),
    )


def test_log_store_filters_by_subsystem_keyword_and_experiment() -> None:
    store = LogStore(max_entries=10)
    store.append(_entry("构建完成", subsystem="build"))
    store.append(_entry("实验导出完成", subsystem="experiment", experiment=True))
    store.append(_entry("试听完成", subsystem="preview"))

    experiment_entries = store.query(LogQuery(subsystem="experiment", experiment_mode="only"))
    assert [entry.subsystem for entry in experiment_entries] == ["experiment"]
    assert experiment_entries[0].experiment_context is not None

    keyword_entries = store.query(LogQuery(keyword="试听"))
    assert [entry.summary for entry in keyword_entries] == ["试听完成"]


def test_log_store_tracks_latest_failure_and_capacity() -> None:
    store = LogStore(max_entries=2)
    store.append(_entry("普通信息", subsystem="build"))
    store.append(_entry("预警", level="WARNING", subsystem="preview"))
    store.append(_entry("构建失败", level="ERROR", subsystem="build"))

    entries = store.entries()
    assert [entry.summary for entry in entries] == ["预警", "构建失败"]
    latest_failure = store.latest(failures_only=True)
    assert latest_failure is not None
    assert latest_failure.summary == "构建失败"
