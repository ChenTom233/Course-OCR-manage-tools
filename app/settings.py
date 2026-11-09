"""用户设置持久化（作息时间与导出提醒）。

设置文件保存在应用目录下（打包后为 exe 所在目录，源码运行为项目根目录）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import time as dtime

from PyQt5.QtCore import QSettings

from .models import DEFAULT_PERIOD_TIMES


def _app_dir() -> str:
    """返回应用目录：打包后为 exe 所在目录，源码运行为项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _settings() -> QSettings:
    folder = _app_dir()
    ini = os.path.join(folder, "settings.ini")

    # 旧版本把设置放在 %LOCALAPPDATA%\TimetableOCR，迁移到应用目录
    old_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "TimetableOCR"
    )
    old_ini = os.path.join(old_dir, "settings.ini")
    if os.path.isfile(old_ini) and not os.path.isfile(ini):
        try:
            os.makedirs(folder, exist_ok=True)
            shutil.copy2(old_ini, ini)
        except OSError:
            pass

    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return QSettings("TimetableOCR", "TimetableOCR")
    return QSettings(ini, QSettings.IniFormat)


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


def load_reminders() -> list[int]:
    """读取 ICS 导出提醒列表（每个元素为提前分钟数，升序；空列表表示不提醒）。"""
    raw = _settings().value("ics/reminders", "")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        data = None
    if isinstance(data, list):
        minutes = sorted({int(x) for x in data if isinstance(x, (int, float)) and int(x) >= 0})
        if minutes:
            return minutes
    return []


def save_reminders(minutes: list[int]) -> None:
    settings = _settings()
    cleaned = sorted({int(m) for m in minutes if int(m) >= 0})
    settings.setValue("ics/reminders", json.dumps(cleaned))
    settings.sync()
