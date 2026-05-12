from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

from PySide6.QtGui import QIcon


def _resolve_icon_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        bundled_icons = bundle_root / "audioforge" / "app" / "assets" / "icons"
        if bundled_icons.exists():
            return bundled_icons
    return Path(__file__).resolve().parents[1] / "assets" / "icons"


ICON_ROOT = _resolve_icon_root()

EVENT_ICON_NAMES = {
    "OneShot": "event_one_shot",
    "Random": "event_random",
    "Sequence": "event_sequence",
    "Combo": "event_combo",
}


@lru_cache(maxsize=None)
def load_app_icon(name: str) -> QIcon:
    file_path = ICON_ROOT / f"{name}.svg"
    if not file_path.exists():
        return QIcon()
    return QIcon(str(file_path))


def load_event_icon(play_mode: str | None) -> QIcon:
    return load_app_icon(EVENT_ICON_NAMES.get(str(play_mode), "event"))