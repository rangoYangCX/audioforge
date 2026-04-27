from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon


ICON_ROOT = Path(__file__).resolve().parents[1] / "assets" / "icons"


@lru_cache(maxsize=None)
def load_app_icon(name: str) -> QIcon:
    file_path = ICON_ROOT / f"{name}.svg"
    if not file_path.exists():
        return QIcon()
    return QIcon(str(file_path))