"""课表数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field

DAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DEFAULT_PERIOD_TIMES: dict[int, tuple[str, str]] = {
    1: ("08:00", "08:45"),
    2: ("08:55", "09:40"),
    3: ("10:00", "10:45"),
    4: ("10:55", "11:40"),
    5: ("14:00", "14:45"),
    6: ("14:55", "15:40"),
    7: ("16:00", "16:45"),
    8: ("16:55", "17:40"),
    9: ("19:00", "19:45"),
    10: ("19:55", "20:40"),
    11: ("20:50", "21:35"),
    12: ("21:45", "22:30"),
}

DEFAULT_TERM_WEEKS = list(range(1, 17))


def compress_weeks(weeks: list[int]) -> str:
    """把周次列表压缩成 1-16周 / 1-15周(单) / 1-4,6,8-16周 这样的文本。"""
    ws = sorted({w for w in weeks if 1 <= w <= 60})
    if not ws:
        return ""
    if len(ws) > 2 and all(ws[i + 1] - ws[i] == 2 for i in range(len(ws) - 1)):
        tag = "单" if ws[0] % 2 == 1 else "双"
        return f"{ws[0]}-{ws[-1]}周({tag})"
    parts: list[str] = []
    start = prev = ws[0]
    for w in ws[1:]:
        if w == prev + 1:
            prev = w
            continue
        parts.append(f"{start}-{prev}" if prev > start else str(start))
        start = prev = w
    parts.append(f"{start}-{prev}" if prev > start else str(start))
    return ",".join(parts) + "周"


@dataclass
class Course:
    name: str
    day: int  # 1=周一 ... 7=周日
    period_start: int
    period_end: int
    teacher: str = ""
    location: str = ""
    weeks: list[int] = field(default_factory=list)
    weeks_text: str = ""
    time_start: str = ""
    time_end: str = ""
    note: str = ""

    @property
    def day_name(self) -> str:
        return DAY_NAMES[self.day - 1] if 1 <= self.day <= 7 else ""

    @property
    def weeks_label(self) -> str:
        if self.weeks_text:
            return self.weeks_text
        return compress_weeks(self.weeks) or "未指定"

    def key(self) -> tuple:
        return (
            self.name,
            self.day,
            self.period_start,
            self.period_end,
            tuple(self.weeks),
            self.location,
            self.teacher,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "day": self.day,
            "day_name": self.day_name,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "periods_text": (
                f"{self.period_start}节"
                if self.period_start == self.period_end
                else f"{self.period_start}-{self.period_end}节"
            ),
            "weeks": self.weeks,
            "weeks_text": self.weeks_label,
            "teacher": self.teacher,
            "location": self.location,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "note": self.note,
        }


@dataclass
class Timetable:
    courses: list[Course] = field(default_factory=list)
    period_times: dict[int, tuple[str, str]] = field(
        default_factory=lambda: dict(DEFAULT_PERIOD_TIMES)
    )
    sources: list[str] = field(default_factory=list)

    def dedupe(self) -> int:
        seen: set = set()
        unique: list[Course] = []
        for course in self.courses:
            key = course.key()
            if key in seen:
                continue
            seen.add(key)
            unique.append(course)
        removed = len(self.courses) - len(unique)
        self.courses = unique
        return removed

    def max_period(self) -> int:
        return max((c.period_end for c in self.courses), default=12)
