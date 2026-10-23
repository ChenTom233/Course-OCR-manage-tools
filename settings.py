"""用户设置持久化（目前只有作息时间）。"""
from __future__ import annotations

import json
import os
from datetime import time as dtime

from PyQt5.QtCore import QSettings

from .models import DEFAULT_PERIOD_TIMES


def _settings() -> QSettings:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "TimetableOCR")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return QSettings("TimetableOCR", "TimetableOCR")
    return QSettings(os.path.join(folder, "settings.ini"), QSettings.IniFormat)


def load_period_times() -> dict[int, tuple[str, str]]:
    raw = _settings().value("schedule/period_times", "")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        result: dict[int, tuple[str, str]] = {}
        for key, value in data.items():
            period = int(key)
            start, end = value
            dtime.fromisoformat(start)
            dtime.fromisoformat(end)
            result[period] = (start, end)
        if result:
            return result
    except (AttributeError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return dict(DEFAULT_PERIOD_TIMES)


def save_period_times(period_times: dict[int, tuple[str, str]]) -> None:
    settings = _settings()
    settings.setValue(
        "schedule/period_times",
        json.dumps({str(k): list(v) for k, v in sorted(period_times.items())}),
    )
    settings.sync()
