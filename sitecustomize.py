from __future__ import annotations

import dataclasses
import datetime as _datetime
from datetime import timezone


if not hasattr(_datetime, "UTC"):
    _datetime.UTC = timezone.utc


_original_dataclass = dataclasses.dataclass


def _compat_dataclass(*args, **kwargs):
    kwargs.pop("slots", None)
    return _original_dataclass(*args, **kwargs)


dataclasses.dataclass = _compat_dataclass