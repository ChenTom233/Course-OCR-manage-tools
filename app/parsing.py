"""课表文本、表格单元格的通用识别逻辑。

支持两类常见课表版式：
1. 网格课表：行是节次、列是星期，单元格里堆叠课程信息；
2. 列表课表：每行一门课，列包含课程名称/教师/星期/节次/周次等。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .models import Course, DEFAULT_PERIOD_TIMES, compress_weeks

LogFn = Callable[[str], None]


def _noop(msg: str) -> None:
    pass


# ---------------------------------------------------------------- 基础清洗

_DAY_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
_DAY_EN = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}

DAY_RE = re.compile(r"(?:周|星期|礼拜)\s*([一二三四五六日天])")
DAY_NUM_RE = re.compile(r"(?:周|星期|礼拜)\s*([1-7])(?![0-9])")
DAY_EN_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b", re.IGNORECASE)

# 周次按“段”解析：每段可带自己的单双周标记，
# 例如 "12-14周(双),15周" 中的双周只作用于 12-14 这一段。
_WEEK_BODY = (
    r"(?:第\s*)?\d{1,2}(?:\s*-\s*\d{1,2})?"
    r"(?:\s*[,，、]\s*(?:第\s*)?\d{1,2}(?:\s*-\s*\d{1,2})?)*"
)
WEEK_SEG_RE = re.compile(
    rf"(?P<body>{_WEEK_BODY})\s*(?:"
    r"周\s*(?:[（(]\s*(?P<paren>[单双])\s*[）)])?"
    r"|(?P<pre>[单双])\s*周"
    r"|[（(]\s*(?P<paren2>[单双])\s*[）)]"
    r")"
)
_STANDALONE_PARITY_RE = re.compile(r"[（(]\s*([单双])\s*[）)]|([单双])\s*周")

PERIOD_LIST_RE = re.compile(r"(\d{1,2}(?:\s*[,，、]\s*\d{1,2})+)\s*节")
PERIOD_RANGE_RE = re.compile(r"第?\s*(\d{1,2})\s*-\s*(\d{1,2})\s*节")
PERIOD_SINGLE_RE = re.compile(r"第?\s*(\d{1,2})\s*节")

TIME_RANGE_RE = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})\s*-\s*(\d{1,2})\s*[:：]\s*(\d{2})")

TEACHER_LABEL_RE = re.compile(
    r"(?:任课教师|授课教师|主讲教师|教师|老师)\s*[:：]\s*([^\s,，;；()（）]+)"
)
LOC_LABEL_RE = re.compile(
    r"(?:上课地点|上课教室|教室|地点)\s*[:：]\s*([^\s,，;；()（）]+)"
)

LOC_PATTERNS = [
    re.compile(
        r"(?:教学楼|实验楼|实训楼|机房|体育馆|操场|艺术楼|综合楼|图书馆|办公楼|"
        r"报告厅|阶梯教室|实验中心|实训中心|校区)[A-Za-z一二三四五六七八九十\d-]*"
    ),
    re.compile(r"教\s*[一二三四五六七八九十]+\s*-?\s*\d+"),
    re.compile(r"[一二三四五六七八九十]\s*教\s*-?\s*\d*"),
    re.compile(r"[A-Za-z]{1,3}\s*-\s*\d{2,4}[A-Za-z]?"),
    re.compile(r"[A-Za-z]{1,2}\d{2,4}[A-Za-z]?"),
    re.compile(r"\d+\s*号楼\s*[A-Za-z\d]*"),
    re.compile(r"[A-Za-z]\s*栋\s*[A-Za-z\d]*"),
]

_BAD_TEACHER_WORDS = {
    "理论", "实践", "实验", "上机", "必修", "选修", "限选", "任选", "公选",
    "考试", "考查", "上午", "下午", "晚上", "大节", "小节", "课程", "专业",
}


def normalize_text(value) -> str:
    if value is None:
        return ""
    s = str(value).replace("　", " ").replace("\xa0", " ")
    for ch in ("—", "–", "－", "~", "～", "至"):
        s = s.replace(ch, "-")
    # OCR 常把连字符读成汉字“一”，仅替换数字之间的情形
    s = re.sub(r"(?<=\d)\s*一\s*(?=\d)", "-", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


# ---------------------------------------------------------------- 字段解析

def parse_day(text, allow_bare: bool = False) -> Optional[int]:
    s = normalize_text(text)
    if not s:
        return None
    m = DAY_RE.search(s)
    if m:
        return _DAY_CN[m.group(1)]
    m = DAY_NUM_RE.search(s)
    if m:
        return int(m.group(1))
    m = DAY_EN_RE.search(s)
    if m:
        return _DAY_EN[m.group(1).lower()]
    if allow_bare:
        core = s.strip(" ()（）[]【】")
        if len(core) == 1 and core in _DAY_CN:
            return _DAY_CN[core]
    return None


def _weeks_from_body(body: str) -> set[int]:
    weeks: set[int] = set()
    for part in re.split(r"[,，、]", body):
        part = re.sub(r"^第\s*", "", part.strip())
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a.strip()), int(b.strip())
            if a > b:
                a, b = b, a
            weeks.update(range(a, b + 1))
        else:
            weeks.add(int(part))
    return weeks


def extract_weeks(text) -> tuple[list[int], str]:
    """返回 (周次列表, 展示文本)。支持 1-16周、单双周、逗号列举。"""
    s = normalize_text(text)
    weeks: set[int] = set()
    for m in WEEK_SEG_RE.finditer(s):
        seg = _weeks_from_body(m.group("body"))
        parity = m.group("paren") or m.group("pre") or m.group("paren2")
        if parity == "单":
            seg = {w for w in seg if w % 2 == 1}
        elif parity == "双":
            seg = {w for w in seg if w % 2 == 0}
        weeks.update(seg)

    if not weeks:
        # 只写了“单周/双周”时，按 1-16 周补全
        m = _STANDALONE_PARITY_RE.search(s)
        if m:
            parity = m.group(1) or m.group(2)
            weeks = {w for w in range(1, 17) if (w % 2 == 1) == (parity == "单")}

    weeks = {w for w in weeks if 1 <= w <= 60}
    ordered = sorted(weeks)
    return ordered, compress_weeks(ordered)


def parse_period(text) -> Optional[tuple[int, int]]:
    s = normalize_text(text)
    if not s:
        return None

    m = PERIOD_LIST_RE.search(s)
    if m:
        nums = [int(n) for n in re.split(r"[,，、]", m.group(1))]
        nums = [n for n in nums if 1 <= n <= 20]
        if nums:
            return min(nums), max(nums)

    m = PERIOD_RANGE_RE.search(s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        if 1 <= a <= 20 and 1 <= b <= 20:
            return a, b

    m = PERIOD_SINGLE_RE.search(s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return n, n

    core = s.strip(" ()（）[]【】")
    m = re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?(?:\s*节)?", core)
    if m:
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if 1 <= a <= 20 and 1 <= b <= 20:
            return (a, b) if a <= b else (b, a)
    return None


def parse_time_range(text) -> Optional[tuple[str, str]]:
    s = normalize_text(text)
    m = TIME_RANGE_RE.search(s)
    if not m:
        return None
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        return None
    return f"{h1:02d}:{m1:02d}", f"{h2:02d}:{m2:02d}"


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def periods_from_times(start: str, end: str, period_times=None) -> tuple[int, int]:
    """把具体时间映射到节次，匹配不上时取最接近的节次。"""
    period_times = period_times or DEFAULT_PERIOD_TIMES
    sm, em = _minutes(start), _minutes(end)
    p_start = min(period_times, key=lambda p: abs(_minutes(period_times[p][0]) - sm))
    p_end = min(period_times, key=lambda p: abs(_minutes(period_times[p][1]) - em))
    if p_end < p_start:
        p_end = p_start
    return p_start, p_end


def parse_location(text) -> str:
    s = normalize_text(text)
    m = LOC_LABEL_RE.search(s)
    if m:
        return m.group(1).strip()
    for pat in LOC_PATTERNS:
        m = pat.search(s)
        if m:
            loc = m.group(0).strip(" -")
            if 2 <= len(loc) <= 24:
                return loc
    return ""


def parse_teacher(text) -> str:
    s = normalize_text(text)
    m = TEACHER_LABEL_RE.search(s)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------- 单元格解析

def strip_meta(line: str) -> str:
    """去掉一行里的星期/节次/周次/时间/教师标签等元信息。"""
    s = normalize_text(line)
    s = DAY_RE.sub(" ", s)
    s = DAY_NUM_RE.sub(" ", s)
    s = DAY_EN_RE.sub(" ", s)
    s = WEEK_SEG_RE.sub(" ", s)
    s = _STANDALONE_PARITY_RE.sub(" ", s)
    for pat in (PERIOD_LIST_RE, PERIOD_RANGE_RE, PERIOD_SINGLE_RE):
        s = pat.sub(" ", s)
    s = TIME_RANGE_RE.sub(" ", s)
    s = TEACHER_LABEL_RE.sub(" ", s)
    s = LOC_LABEL_RE.sub(" ", s)
    return s.strip(" \t,，;；()（）[]【】")


def _looks_like_location(text: str) -> bool:
    return bool(parse_location(text)) and len(text) <= 24


def parse_course_cell(
    text,
    day_hint: Optional[int] = None,
    pstart_hint: Optional[int] = None,
    pend_hint: Optional[int] = None,
) -> Optional[Course]:
    raw = normalize_text(text)
    if not raw:
        return None

    day = parse_day(raw) or day_hint
    if day is None or not (1 <= day <= 7):
        return None

    period = parse_period(raw)
    if period is None and pstart_hint and pend_hint:
        period = (pstart_hint, pend_hint)
    time_range = parse_time_range(raw)
    if period is None and time_range:
        period = periods_from_times(*time_range)
    if period is None:
        return None
    pstart, pend = period
    pstart = max(1, min(pstart, 20))
    pend = max(pstart, min(pend, 20))

    weeks, weeks_label = extract_weeks(raw)
    location = parse_location(raw)
    teacher = parse_teacher(raw)

    lines = [ln for ln in re.split(r"[\r\n]+", raw) if ln.strip()]
    candidates: list[str] = []
    for ln in lines:
        s = strip_meta(ln)
        if location and location in s:
            s = s.replace(location, " ").strip()
        if s:
            candidates.append(s)

    name = candidates[0] if candidates else ""
    if not teacher:
        for cand in candidates[1:]:
            if (
                re.fullmatch(r"[一-鿿·]{2,4}", cand)
                and cand not in _BAD_TEACHER_WORDS
            ):
                teacher = cand
                break
    if not location:
        for cand in candidates[1:]:
            if _looks_like_location(cand):
                location = parse_location(cand)
                break
    if name and not teacher:
        # 单行文本里“课程名 教师”连在一起时，尝试把末尾 2-4 个汉字当教师
        m = re.fullmatch(r"(.+?)\s+([一-鿿·]{2,4})", name)
        if m and m.group(2) not in _BAD_TEACHER_WORDS:
            name, teacher = m.group(1).strip(), m.group(2)

    if not name:
        name = strip_meta(lines[0]) if lines else ""
    if not name:
        name = "(未识别课程)"

    return Course(
        name=name.strip(),
        day=day,
        period_start=pstart,
        period_end=pend,
        teacher=teacher,
        location=location,
        weeks=weeks,
        weeks_text=weeks_label,
        time_start=time_range[0] if time_range else "",
        time_end=time_range[1] if time_range else "",
    )


# 教务系统导出的“大格子”课表：一个单元格里堆叠多门课，
# 每门课以 "(1-2节)1-4周,6-14周/校区:…/场地:…/教师:…" 标记开头，
# 课程名在标记行上方若干行，元信息会任意折行。

_RICH_HINT_RE = re.compile(r"[/／]\s*(?:场\s*地|教\s*师|校\s*区|教\s*学\s*班)\s*[:：]")
_RICH_MARKER_RE = re.compile(r"^[（(]\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*节\s*[）)]")
# 字段名可能被折行拆开，如 “/教\n师:张彦”
_RICH_LOC_RE = re.compile(r"[/／]\s*场\s*地\s*[:：]\s*([^/／]*)")
_RICH_TEACHER_RE = re.compile(r"[/／]\s*教\s*师\s*[:：]\s*([^/／]*)")

_NAME_BLOCKERS = (
    ":", "：", "/", "／", "节", "周", "学时", "学分", "学期",
    "考核", "备注", "教学班", "教师", "场地", "校区", "选课", "组成",
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _clean_location(value: str) -> str:
    return re.sub(r"[()（）]", "", _compact(value))


def _is_course_name_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 40:
        return False
    if not any(_is_cjk(ch) for ch in s):
        return False
    return not any(token in s for token in _NAME_BLOCKERS)


def parse_rich_cell(
    text,
    day: int,
    pstart_hint: Optional[int] = None,
    pend_hint: Optional[int] = None,
) -> list[Course]:
    """解析大格子里的多门课；不是这种版式时返回空列表。"""
    lines = [ln.strip() for ln in normalize_text(text).splitlines()]
    markers = [i for i, line in enumerate(lines) if _RICH_MARKER_RE.match(line)]
    if not markers:
        return []

    courses: list[Course] = []
    for k, i in enumerate(markers):
        marker = _RICH_MARKER_RE.match(lines[i])
        end = markers[k + 1] if k + 1 < len(markers) else len(lines)
        block = "\n".join(lines[i:end])

        name_lines: list[str] = []
        j = i - 1
        while j >= 0 and len(name_lines) < 4 and _is_course_name_line(lines[j]):
            name_lines.insert(0, lines[j])
            j -= 1
        name = _compact("".join(name_lines))
        if not name:
            continue

        pstart = int(marker.group(1))
        pend = int(marker.group(2)) if marker.group(2) else pstart
        if pstart > pend:
            pstart, pend = pend, pstart
        if not (1 <= pstart <= 20 and 1 <= pend <= 20):
            pstart = pstart_hint or 1
            pend = pend_hint or pstart

        head = re.split(r"[/／]", block, maxsplit=1)[0]
        head = _RICH_MARKER_RE.sub(" ", head, count=1)
        weeks, weeks_label = extract_weeks(head)

        loc_m = _RICH_LOC_RE.search(block)
        teacher_m = _RICH_TEACHER_RE.search(block)
        courses.append(
            Course(
                name=name,
                day=day,
                period_start=pstart,
                period_end=pend,
                teacher=_compact(teacher_m.group(1)) if teacher_m else "",
                location=_clean_location(loc_m.group(1)) if loc_m else "",
                weeks=weeks,
                weeks_text=weeks_label,
            )
        )
    return courses


# ---------------------------------------------------------------- 表格解析

@dataclass
class GridCell:
    row: int
    col: int
    rowspan: int
    colspan: int
    text: str


def _padded(matrix: list[list[str]]) -> list[list[str]]:
    width = max((len(r) for r in matrix), default=0)
    return [list(r) + [""] * (width - len(r)) for r in matrix]


def _period_from_row_cell(value) -> Optional[tuple[int, int]]:
    pr = parse_period(value)
    if pr:
        return pr
    tr = parse_time_range(value)
    if tr:
        return periods_from_times(*tr)
    return None


def _dedupe_courses(courses: list[Course]) -> list[Course]:
    seen: set = set()
    out: list[Course] = []
    for course in courses:
        key = course.key()
        if key in seen:
            continue
        seen.add(key)
        out.append(course)
    return out


def detect_day_header(matrix: list[list[str]]) -> tuple[int, dict[int, int], int]:
    """返回 (表头行号, {列号: 星期}, 识别到的星期数)，找不到时行号为 -1。"""
    header_row = -1
    day_cols: dict[int, int] = {}
    best = 0
    for ri in range(min(len(matrix), 12)):
        mapping: dict[int, int] = {}
        explicit = 0
        for ci, value in enumerate(matrix[ri]):
            day = parse_day(value, allow_bare=True)
            if day is None or day in mapping.values():
                continue
            mapping[ci] = day
            norm = normalize_text(value)
            if DAY_RE.search(norm) or DAY_NUM_RE.search(norm):
                explicit += 1
        distinct = len(set(mapping.values()))
        if distinct >= 2 and (explicit >= 1 or distinct >= 4) and distinct > best:
            best = distinct
            header_row = ri
            day_cols = mapping
    return header_row, day_cols, best


def detect_period_col(
    matrix: list[list[str]], header_row: int, day_cols: dict[int, int]
) -> Optional[int]:
    """找节次列：优先看表头文字，其次找节次数字最多的一列。"""
    for ci, value in enumerate(matrix[header_row]):
        if "节次" in normalize_text(value):
            return ci
    for ci, value in enumerate(matrix[header_row]):
        norm = normalize_text(value)
        # “时间段”是上午/下午的分组列，不是节次列
        if ("时间" in norm or "课时" in norm) and "时间段" not in norm:
            return ci
    max_day_col = min(day_cols) if day_cols else len(matrix[0])
    best_hits = 0
    best_col: Optional[int] = None
    for ci in range(max_day_col):
        hits = 0
        for ri in range(header_row + 1, len(matrix)):
            if _period_from_row_cell(matrix[ri][ci]):
                hits += 1
        if hits > best_hits:
            best_hits = hits
            best_col = ci
    return best_col


def parse_grid(
    matrix: list[list[str]],
    cells: Optional[list[GridCell]] = None,
    log: LogFn = _noop,
    day_cols: Optional[dict[int, int]] = None,
    header_row: Optional[int] = None,
    period_col: Optional[int] = None,
) -> list[Course]:
    """解析网格课表。

    传入 day_cols 可解析没有表头的续页：此时 header_row 为 None 表示整页
    都没有表头，只处理节次列有值的行，避免把跨页残片当成课程。
    """
    matrix = _padded(matrix)
    if not matrix or not matrix[0]:
        return []
    width = len(matrix[0])

    if day_cols is None:
        header_row, day_cols, best = detect_day_header(matrix)
        if header_row < 0 or not day_cols:
            return []
        log(f"  表头在第 {header_row + 1} 行，识别到 {best} 个星期列")
    elif header_row is None:
        header_row = -1

    assert day_cols is not None
    if period_col is None:
        period_col = detect_period_col(matrix, header_row, day_cols)

    row_periods: dict[int, tuple[int, int]] = {}
    if period_col is not None:
        for ri in range(header_row + 1, len(matrix)):
            pr = _period_from_row_cell(matrix[ri][period_col])
            if pr:
                row_periods[ri] = pr
    if not row_periods:
        if header_row < 0:
            return []
        log("  未找到节次列，按表头下方行号推算节次")
        for ri in range(header_row + 1, len(matrix)):
            offset = ri - header_row
            if 1 <= offset <= 20:
                row_periods[ri] = (offset, offset)

    if cells is None:
        cells = [
            GridCell(ri, ci, 1, 1, value)
            for ri, row in enumerate(matrix)
            for ci, value in enumerate(row)
            if normalize_text(value)
        ]

    courses: list[Course] = []
    for cell in cells:
        if cell.row <= header_row or not normalize_text(cell.text):
            continue
        days: list[int] = []
        for ci in range(cell.col, min(cell.col + cell.colspan, width)):
            if ci in day_cols and day_cols[ci] not in days:
                days.append(day_cols[ci])
        if not days:
            continue

        period_values: list[int] = []
        for ri in range(cell.row, min(cell.row + cell.rowspan, len(matrix))):
            pr = row_periods.get(ri)
            if pr:
                period_values.extend(pr)
        if period_values:
            pstart, pend = min(period_values), max(period_values)
        elif header_row >= 0:
            pstart = max(1, cell.row - header_row)
            pend = min(20, pstart + cell.rowspan - 1)
        else:
            continue

        rich = bool(_RICH_HINT_RE.search(cell.text))
        # 同一个格子里可能用空行分隔了多门课（如前后半学期的课）
        blocks = [
            block.strip()
            for block in re.split(r"\n\s*\n", normalize_text(cell.text))
            if block.strip()
        ] or [cell.text]
        for day in days:
            if rich:
                rich_courses = parse_rich_cell(
                    cell.text, day, pstart_hint=pstart, pend_hint=pend
                )
                if rich_courses:
                    courses.extend(rich_courses)
                    continue
            for block in blocks:
                course = parse_course_cell(
                    block, day_hint=day, pstart_hint=pstart, pend_hint=pend
                )
                if course:
                    courses.append(course)

    return _dedupe_courses(courses)


_FIELD_PATTERNS = [
    ("name", ("课程名称", "课程名", "课程")),
    ("teacher", ("任课教师", "授课教师", "主讲教师", "任课老师", "教师", "老师", "姓名", "授课人")),
    ("location", ("上课地点", "上课教室", "场地名称", "场地", "场馆", "教室", "地点")),
    ("day", ("星期", "周几", "上课日")),
    ("period", ("节次", "节")),
    ("time", ("上课时间", "时间")),
    ("weeks", ("周次", "周数", "上课周")),
    ("content", ("教学内容", "内容")),
    ("note", ("教学班", "备注")),
]
_HEADER_EXCLUDE = ("编号", "代码", "序号", "学分", "学时", "人数", "班级", "专业", "备注")


def _match_field(value) -> Optional[str]:
    s = normalize_text(value)
    if not s or len(s) > 16:
        return None
    if any(bad in s for bad in _HEADER_EXCLUDE):
        return None
    for field, keywords in _FIELD_PATTERNS:
        if any(k in s for k in keywords):
            return field
    return None


def detect_list_header(
    matrix: list[list[str]],
) -> tuple[int, dict[str, int], int]:
    """返回 (表头行号, {字段: 列号}, 命中字段数)。"""
    matrix = _padded(matrix)
    header_row = -1
    best_score = 0
    field_cols: dict[str, int] = {}
    for ri in range(min(len(matrix), 10)):
        mapping: dict[str, int] = {}
        for ci, value in enumerate(matrix[ri]):
            field = _match_field(value)
            if field and field not in mapping:
                mapping[field] = ci
        score = len(mapping)
        if score > best_score:
            best_score = score
            header_row = ri
            field_cols = mapping
    return header_row, field_cols, best_score


def parse_list_table(
    matrix: list[list[str]],
    log: LogFn = _noop,
    field_cols: Optional[dict[str, int]] = None,
    header_row: Optional[int] = None,
) -> list[Course]:
    matrix = _padded(matrix)
    if not matrix:
        return []

    if field_cols is None:
        header_row, field_cols, best_score = detect_list_header(matrix)
        if best_score < 2 or header_row < 0:
            return []
        log(f"  列表式表头在第 {header_row + 1} 行：{', '.join(sorted(field_cols))}")
    elif header_row is None:
        header_row = -1

    if "name" not in field_cols and "day" not in field_cols:
        return []
    if not ({"day", "period", "time", "weeks"} & set(field_cols)):
        return []

    def get(row: list[str], field: str) -> str:
        ci = field_cols.get(field)
        if ci is None or ci >= len(row):
            return ""
        return normalize_text(row[ci])

    courses: list[Course] = []
    for ri in range(header_row + 1, len(matrix)):
        row = matrix[ri]
        combined = normalize_text(" ".join(v for v in row if normalize_text(v)))
        if not combined:
            continue
        day = parse_day(get(row, "day")) or parse_day(combined)
        if day is None:
            continue

        time_range = parse_time_range(get(row, "time")) or parse_time_range(combined)
        period = parse_period(get(row, "period")) or parse_period(combined)
        if period is None and time_range:
            period = periods_from_times(*time_range)
        if period is None:
            continue

        weeks_cell = get(row, "weeks")
        weeks, weeks_label = extract_weeks(weeks_cell + " " + combined)
        if not weeks and weeks_cell and "周" not in weeks_cell:
            weeks, weeks_label = extract_weeks(weeks_cell + "周")
        location = get(row, "location") or parse_location(combined)
        teacher = get(row, "teacher") or parse_teacher(combined)
        note = get(row, "note")
        name = get(row, "name")
        content = get(row, "content")
        if content:
            if not name:
                name = content
            elif content in name or name in content:
                name = name if len(name) >= len(content) else content
            else:
                name = f"{name} {content}"

        if not name:
            parsed = parse_course_cell(
                combined, day_hint=day, pstart_hint=period[0], pend_hint=period[1]
            )
            if parsed:
                if not parsed.weeks:
                    parsed.weeks, parsed.weeks_text = weeks, weeks_label
                courses.append(parsed)
            continue

        courses.append(
            Course(
                name=name,
                day=day,
                period_start=period[0],
                period_end=period[1],
                teacher=teacher,
                location=location,
                weeks=weeks,
                weeks_text=weeks_label,
                time_start=time_range[0] if time_range else "",
                time_end=time_range[1] if time_range else "",
                note=note,
            )
        )

    return _dedupe_courses(courses)


def parse_table(matrix: list[list[str]], log: LogFn = _noop) -> list[Course]:
    courses = parse_list_table(matrix, log)
    if courses:
        return courses
    return parse_grid(matrix, log=log)


def courses_from_text(text: str, log: LogFn = _noop) -> list[Course]:
    """纯文本兜底：一行一条记录。"""
    courses: list[Course] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if parse_day(line) and (parse_period(line) or parse_time_range(line)):
            course = parse_course_cell(line)
            if course:
                courses.append(course)
    return _dedupe_courses(courses)


# ---------------------------------------------------------------- 坐标还原（PDF / OCR）

Item = tuple[float, float, float, float, str]  # x0, y0, x1, y1, text


def _median(values: list[float]) -> float:
    if not values:
        return 10.0
    values = sorted(values)
    return values[len(values) // 2]


def _cluster_rows(items: list[Item]) -> list[dict]:
    heights = [y1 - y0 for x0, y0, x1, y1, _ in items if y1 > y0]
    tol = max(6.0, _median(heights) * 0.6)
    ordered = sorted(items, key=lambda it: (it[1] + it[3]) / 2)
    rows: list[dict] = []
    for item in ordered:
        cy = (item[1] + item[3]) / 2
        if rows and abs(cy - rows[-1]["cy"]) <= tol:
            row = rows[-1]
            row["items"].append(item)
            row["cy"] = (row["cy"] * (len(row["items"]) - 1) + cy) / len(row["items"])
        else:
            rows.append({"cy": cy, "items": [item]})
    for row in rows:
        row["items"].sort(key=lambda it: it[0])
        row["text"] = " ".join(it[4] for it in row["items"])
    return rows


def _join_line(items: list[Item]) -> str:
    out = ""
    prev: Item | None = None
    for item in items:
        text = item[4].strip()
        if not text:
            continue
        if out and prev is not None:
            gap = item[0] - prev[2]
            height = max(1.0, min(item[3] - item[1], prev[3] - prev[1]))
            if _is_cjk(out[-1]) or _is_cjk(text[0]):
                # 同一段中文被拆成多个框时缝隙很小，不同字段之间缝隙较大
                if gap > max(1.5, height * 0.25):
                    out += " "
            else:
                out += " "
        out += text
        prev = item
    return out


def _cell_text(tokens: list[Item]) -> str:
    if not tokens:
        return ""
    heights = [y1 - y0 for x0, y0, x1, y1, _ in tokens if y1 > y0]
    tol = max(6.0, _median(heights) * 0.6)
    ordered = sorted(tokens, key=lambda it: ((it[1] + it[3]) / 2, it[0]))
    lines: list[list[Item]] = []
    for item in ordered:
        cy = (item[1] + item[3]) / 2
        if lines:
            last_cy = (
                min(it[1] for it in lines[-1]) + max(it[3] for it in lines[-1])
            ) / 2
            if abs(cy - last_cy) <= tol:
                lines[-1].append(item)
                continue
        lines.append([item])
    rendered = []
    for line in lines:
        line.sort(key=lambda it: it[0])
        rendered.append(_join_line(line))
    return "\n".join(s for s in rendered if s.strip())


def courses_from_items(items: list[Item], log: LogFn = _noop) -> list[Course]:
    """根据带坐标的文字块还原网格课表（用于无表格线的 PDF 和扫描件）。"""
    items = [it for it in items if it[4].strip()]
    if len(items) < 4:
        return []
    rows = _cluster_rows(items)
    if not rows:
        return []

    header_index = -1
    header_days: list[tuple[int, float]] = []
    for ri, row in enumerate(rows[:10]):
        days: list[tuple[int, float]] = []
        seen = set()
        for item in row["items"]:
            day = parse_day(item[4])
            if day and day not in seen:
                seen.add(day)
                days.append((day, (item[0] + item[2]) / 2))
        if len(days) >= 2 and len(days) > len(header_days):
            header_index = ri
            header_days = days
    if header_index < 0 or len(header_days) < 2:
        return []
    header_days.sort(key=lambda d: d[1])
    header_bottom = max(it[3] for it in rows[header_index]["items"])
    day_xs = [x for _, x in header_days]
    gaps = [right - left for left, right in zip(day_xs, day_xs[1:])]
    # 左边界取第一列左边线，避免漏掉列内左对齐的课程名
    left_bound = day_xs[0] - (min(gaps) / 2 if gaps else 20)

    period_anchors: list[tuple[int, float, str]] = []
    for row in rows[header_index + 1:]:
        for item in row["items"]:
            center = (item[0] + item[2]) / 2
            if center >= left_bound:
                continue
            tr = parse_time_range(item[4])
            pr = periods_from_times(*tr) if tr else parse_period(item[4])
            if pr:
                for p in range(pr[0], pr[1] + 1):
                    period_anchors.append((p, (item[1] + item[3]) / 2, item[4]))
    # 网格补全的锚点形如“第 3 节”，比 OCR 从时间列拆出的裸数字可靠
    if any("第" in text for _, _, text in period_anchors):
        period_anchors = [a for a in period_anchors if "第" in a[2]]
    # 同一个节次取第一次出现的位置
    dedup_anchors: dict[int, float] = {}
    for p, cy, _ in period_anchors:
        dedup_anchors.setdefault(p, cy)
    anchors = sorted(dedup_anchors.items(), key=lambda kv: kv[1])

    day_centers = [x for _, x in header_days]
    bounds = []
    for i, x in enumerate(day_centers):
        left = (day_centers[i - 1] + x) / 2 if i > 0 else x - (day_centers[1] - x) / 2
        right = (x + day_centers[i + 1]) / 2 if i < len(day_centers) - 1 else x + (x - day_centers[-2]) / 2
        bounds.append((left, right))

    groups: dict[tuple[int, int], list[Item]] = {}
    row_index = 0
    for row in rows[header_index + 1:]:
        row_index += 1
        for item in row["items"]:
            if item[3] <= header_bottom + 2:
                continue
            cx = (item[0] + item[2]) / 2
            if cx < left_bound:
                continue
            if not any(lo <= cx <= hi for lo, hi in bounds):
                continue
            day_index = min(
                range(len(day_centers)), key=lambda i: abs(day_centers[i] - cx)
            )
            day = header_days[day_index][0]
            if anchors:
                period = min(anchors, key=lambda kv: abs(kv[1] - (item[1] + item[3]) / 2))[0]
            else:
                period = row_index
            if not (1 <= period <= 20):
                continue
            groups.setdefault((day, period), []).append(item)

    courses: list[Course] = []
    for (day, period), tokens in groups.items():
        text = _cell_text(tokens)
        if not text:
            continue
        course = parse_course_cell(text, day_hint=day, pstart_hint=period, pend_hint=period)
        if course:
            courses.append(course)
    return _dedupe_courses(courses)
