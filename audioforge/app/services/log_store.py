from __future__ import annotations

from dataclasses import dataclass

from audioforge.app.models.log_entry_dto import LogEntry


@dataclass(slots=True)
class LogQuery:
    levels: set[str] | None = None
    subsystem: str = ""
    source: str = ""
    keyword: str = ""
    experiment_mode: str = "all"
    failures_only: bool = False
    limit: int | None = None


class LogStore:
    def __init__(self, *, max_entries: int = 1000) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: list[LogEntry] = []

    def append(self, entry: LogEntry) -> None:
        self._entries.append(entry)
        overflow = len(self._entries) - self._max_entries
        if overflow > 0:
            del self._entries[:overflow]

    def clear(self) -> None:
        self._entries.clear()

    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    def latest(self, *, failures_only: bool = False) -> LogEntry | None:
        for entry in reversed(self._entries):
            if not failures_only or entry.is_failure:
                return entry
        return None

    def query(self, query: LogQuery | None = None) -> list[LogEntry]:
        if query is None:
            return self.entries()
        entries = [entry for entry in self._entries if self._matches(entry, query)]
        if query.limit is not None and query.limit >= 0:
            return entries[-query.limit :]
        return entries

    def available_subsystems(self) -> list[str]:
        return sorted({entry.subsystem for entry in self._entries if entry.subsystem}, key=str.casefold)

    def available_sources(self) -> list[str]:
        return sorted({entry.source for entry in self._entries if entry.source}, key=str.casefold)

    def _matches(self, entry: LogEntry, query: LogQuery) -> bool:
        if query.failures_only and not entry.is_failure:
            return False
        if query.levels and entry.level not in query.levels:
            return False
        if query.subsystem and entry.subsystem != query.subsystem:
            return False
        if query.source and entry.source != query.source:
            return False
        if query.experiment_mode == "only" and entry.experiment_context is None:
            return False
        if query.experiment_mode == "exclude" and entry.experiment_context is not None:
            return False
        keyword = query.keyword.strip().casefold()
        if keyword:
            haystacks = [
                entry.timestamp,
                entry.level,
                entry.subsystem,
                entry.source,
                entry.summary,
                entry.message,
                entry.target_type,
                entry.target_id,
                entry.correlation_id,
                entry.project_name,
                entry.project_path,
            ]
            if entry.experiment_context is not None:
                haystacks.extend(str(value) for value in entry.experiment_context.as_dict().values())
            haystacks.extend(str(value) for value in entry.context.values())
            normalized_haystack = " ".join(value.casefold() for value in haystacks if value)
            if keyword not in normalized_haystack:
                return False
        return True
