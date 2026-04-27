from __future__ import annotations

import math
from dataclasses import dataclass


MASTER_BUS_NAME = "Master"
MIN_AUDIBLE_DB = -96.0


@dataclass(slots=True)
class PreviewBusState:
    name: str
    volume_linear: float = 1.0
    is_muted: bool = False


class PreviewBusMixer:
    def __init__(self) -> None:
        self._states: dict[str, PreviewBusState] = {MASTER_BUS_NAME: PreviewBusState(name=MASTER_BUS_NAME)}
        self._parent_map: dict[str, str] = {}

    def sync_buses(self, buses: list[str], parent_map: dict[str, str] | None = None) -> None:
        normalized = [self._normalize_name(bus) for bus in buses if self._normalize_name(bus)]
        keep_names = {MASTER_BUS_NAME, *normalized}
        for bus_name in normalized:
            self._states.setdefault(bus_name, PreviewBusState(name=bus_name))
        self._states = {name: state for name, state in self._states.items() if name in keep_names}
        self._states.setdefault(MASTER_BUS_NAME, PreviewBusState(name=MASTER_BUS_NAME))
        self._parent_map = {}
        for bus_name in normalized:
            parent_name = self._normalize_name((parent_map or {}).get(bus_name, MASTER_BUS_NAME))
            if parent_name == bus_name:
                parent_name = MASTER_BUS_NAME
            if parent_name != MASTER_BUS_NAME and parent_name not in keep_names:
                parent_name = MASTER_BUS_NAME
            self._parent_map[bus_name] = parent_name

    def editable_bus_names(self, buses: list[str], parent_map: dict[str, str] | None = None) -> list[str]:
        self.sync_buses(buses, parent_map)
        return [MASTER_BUS_NAME, *[bus for bus in buses if self._normalize_name(bus) and self._normalize_name(bus) != MASTER_BUS_NAME]]

    def get_state(self, bus_name: str) -> PreviewBusState:
        normalized = self._normalize_name(bus_name)
        if normalized not in self._states:
            self._states[normalized] = PreviewBusState(name=normalized)
        state = self._states[normalized]
        return PreviewBusState(name=state.name, volume_linear=state.volume_linear, is_muted=state.is_muted)

    def set_state(self, bus_name: str, *, volume_linear: float, is_muted: bool) -> PreviewBusState:
        normalized = self._normalize_name(bus_name)
        state = self._states.setdefault(normalized, PreviewBusState(name=normalized))
        state.volume_linear = max(0.0, min(1.0, float(volume_linear)))
        state.is_muted = bool(is_muted)
        return PreviewBusState(name=state.name, volume_linear=state.volume_linear, is_muted=state.is_muted)

    def effective_gain_linear(self, bus_name: str) -> float:
        normalized = self._normalize_name(bus_name)
        gain = 1.0
        current = normalized
        visited: set[str] = set()
        while True:
            state = self._states.get(current, PreviewBusState(name=current))
            if state.is_muted:
                return 0.0
            gain *= max(0.0, min(1.0, state.volume_linear))
            if current == MASTER_BUS_NAME:
                return max(0.0, min(1.0, gain))
            if current in visited:
                return 0.0
            visited.add(current)
            current = self._parent_map.get(current, MASTER_BUS_NAME)

    def effective_gain_db(self, bus_name: str) -> float:
        return self.linear_to_db(self.effective_gain_linear(bus_name))

    def describe_bus(self, bus_name: str) -> str:
        normalized = self._normalize_name(bus_name)
        route_names = [normalized]
        current = normalized
        visited: set[str] = set()
        while current != MASTER_BUS_NAME:
            if current in visited:
                route_names.append("RouteCycle")
                break
            visited.add(current)
            current = self._parent_map.get(current, MASTER_BUS_NAME)
            route_names.append(current)
        route_text = " -> ".join(route_names)
        effective = self.effective_gain_linear(normalized) * 100.0
        if effective <= 0.0:
            return f"{route_text} | 静音"
        return f"{route_text} | {effective:.0f}%"

    @staticmethod
    def linear_to_db(value: float) -> float:
        if value <= 0.0:
            return MIN_AUDIBLE_DB
        return max(MIN_AUDIBLE_DB, 20.0 * math.log10(value))

    @staticmethod
    def _normalize_name(bus_name: str) -> str:
        normalized = str(bus_name).strip() or MASTER_BUS_NAME
        if normalized.casefold() == MASTER_BUS_NAME.casefold():
            return MASTER_BUS_NAME
        return normalized
