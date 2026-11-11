"""PyQt5 图形界面。"""
from __future__ import annotations

import os
import queue
import re
import threading
from datetime import date, timedelta

from PyQt5.QtCore import QRectF, QTime, QTimer, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .crashlog import get_log_path
from .excel_parser import parse_excel
from .exporters import export_ics, export_json, export_xlsx
from .models import (
    Course,
    DAY_NAMES,
    DEFAULT_PERIOD_TIMES,
    Timetable,
    compress_weeks,
    find_conflicts,
)
from .parsing import extract_weeks
from .pdf_parser import parse_pdf
from .settings import (
    load_period_times,
    load_reminders,
    load_theme,
    save_period_times,
    save_reminders,
    save_theme,
)
from . import theme

_UI_FONT = "Microsoft YaHei UI"
_GRID_COLORS = [
    "#FFE0B2", "#C8E6C9", "#BBDEFB", "#F8BBD0",
    "#E1BEE7", "#B2EBF2", "#FFF9C4", "#D7CCC8",
]


def _default_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("hint", "true")
    return label


def _normalize_weeks_input(text: str) -> list[int]:
    s = text.strip()
    if not s:
        return []
    for src, dst in (("（单）", "单周"), ("(单)", "单周"), ("（双）", "双周"), ("(双)", "双周")):
        s = s.replace(src, dst)
    if "周" not in s:
        s += "周"
    weeks, _ = extract_weeks(s)
    return weeks


def _normalize_clock(text: str) -> str | None:
    s = text.strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2})\s*[:：]\s*(\d{2})", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


_REMINDER_OPTIONS = [
    "不提醒",
    "事件开始时",
    "提前 5 分钟",
    "提前 10 分钟",
    "提前 15 分钟",
    "提前 30 分钟",
    "提前 1 小时",
    "提前 1 天",
]
_REMINDER_MINUTES = [None, 0, 5, 10, 15, 30, 60, 1440]
_REMINDER_LABELS = {
    0: "事件开始时",
    5: "5 分钟",
    10: "10 分钟",
    15: "15 分钟",
    30: "30 分钟",
    60: "1 小时",
    1440: "1 天",
}


class CourseDialog(QDialog):
    def __init__(self, parent=None, course: Course | None = None, period_times=None):
        super().__init__(parent)
        self.result: Course | None = None
        self.period_times = period_times or DEFAULT_PERIOD_TIMES
        self.setWindowTitle("编辑课程" if course else "新增课程")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        grid = QGridLayout(self)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(7)
        pad = 7

        self.name_edit = QLineEdit(course.name if course else "")
        self.name_edit.setMinimumWidth(300)
        grid.addWidget(self._right_label("课程名称"), 0, 0)
        grid.addWidget(self.name_edit, 0, 1, 1, 3)
        grid.setRowMinimumHeight(0, 34)

        self.day_combo = QComboBox()
        self.day_combo.addItems(DAY_NAMES)
        self.day_combo.setEditable(False)
        self.day_combo.setCurrentText(course.day_name if course else DAY_NAMES[0])
        self.ps_spin = QSpinBox()
        self.ps_spin.setRange(1, 20)
        self.ps_spin.setValue(course.period_start if course else 1)
        self.pe_spin = QSpinBox()
        self.pe_spin.setRange(1, 20)
        self.pe_spin.setValue(course.period_end if course else 2)

        period_box = QWidget()
        period_lay = QHBoxLayout(period_box)
        period_lay.setContentsMargins(0, 0, 0, 0)
        period_lay.setSpacing(4)
        period_lay.addWidget(self.ps_spin)
        period_lay.addWidget(QLabel("至"))
        period_lay.addWidget(self.pe_spin)
        period_lay.addStretch(1)

        grid.addWidget(self._right_label("星期"), 1, 0)
        grid.addWidget(self.day_combo, 1, 1)
        grid.addWidget(self._right_label("节次"), 1, 2)
        grid.addWidget(period_box, 1, 3)

        self.weeks_edit = QLineEdit(
            compress_weeks(course.weeks) if course else ""
        )
        grid.addWidget(self._right_label("周次"), 2, 0)
        grid.addWidget(self.weeks_edit, 2, 1, 1, 3)
        grid.addWidget(
            _hint("例如：1-16、1-16(单)、1,3,5-9；留空表示未指定"), 3, 1, 1, 3
        )

        self.teacher_edit = QLineEdit(course.teacher if course else "")
        self.location_edit = QLineEdit(course.location if course else "")
        grid.addWidget(self._right_label("教师"), 4, 0)
        grid.addWidget(self.teacher_edit, 4, 1)
        grid.addWidget(self._right_label("教室"), 4, 2)
        grid.addWidget(self.location_edit, 4, 3)

        self.start_edit = QLineEdit(course.time_start if course else "")
        self.end_edit = QLineEdit(course.time_end if course else "")
        for editor in (self.start_edit, self.end_edit):
            editor.setMaximumWidth(70)
        time_box = QWidget()
        time_lay = QHBoxLayout(time_box)
        time_lay.setContentsMargins(0, 0, 0, 0)
        time_lay.setSpacing(4)
        time_lay.addWidget(self.start_edit)
        time_lay.addWidget(QLabel("-"))
        time_lay.addWidget(self.end_edit)
        time_lay.addWidget(_hint("可留空，按标准作息时间"))

        grid.addWidget(self._right_label("时间"), 5, 0)
        grid.addWidget(time_box, 5, 1, 1, 3)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 14, 0, 0)
        buttons.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("保存")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        grid.addLayout(buttons, 6, 0, 1, 4)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setSizeConstraint(QLayout.SetFixedSize)

        self._center_on_parent()
        self.name_edit.setFocus()

    def _right_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        geo = self.frameGeometry()
        geo.moveCenter(parent.frameGeometry().center())
        self.move(geo.topLeft())

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请填写课程名称")
            return
        ps, pe = self.ps_spin.value(), self.pe_spin.value()
        if ps > pe:
            ps, pe = pe, ps

        weeks_text = self.weeks_edit.text().strip()
        weeks = _normalize_weeks_input(weeks_text)
        if weeks_text and not weeks:
            QMessageBox.warning(
                self, "提示", "周次格式无法识别，请参考：1-16、1-16(单)、1,3,5"
            )
            return

        start = _normalize_clock(self.start_edit.text())
        end = _normalize_clock(self.end_edit.text())
        if start is None or end is None:
            QMessageBox.warning(self, "提示", "时间格式应为 HH:MM，例如 08:00")
            return
        if bool(start) != bool(end):
            QMessageBox.warning(self, "提示", "开始时间和结束时间请同时填写或同时留空")
            return
        if start and end and end <= start:
            QMessageBox.warning(self, "提示", "结束时间需晚于开始时间")
            return

        self.result = Course(
            name=name,
            day=DAY_NAMES.index(self.day_combo.currentText()) + 1,
            period_start=ps,
            period_end=pe,
            teacher=self.teacher_edit.text().strip(),
            location=self.location_edit.text().strip(),
            weeks=weeks,
            weeks_text=compress_weeks(weeks),
            time_start=start,
            time_end=end,
        )
        self.accept()


def _period_duration(start_text: str, end_text: str) -> int:
    start = QTime.fromString(start_text, "HH:mm")
    end = QTime.fromString(end_text, "HH:mm")
    if start.isValid() and end.isValid():
        minutes = start.secsTo(end) // 60
        if 5 <= minutes <= 240:
            return minutes
    return 45


class ScheduleEditor(QWidget):
    """作息时间编辑器（嵌入设置窗口）。"""

    def __init__(self, parent=None, period_times=None, max_period: int = 12):
        super().__init__(parent)
        self._rows: list[tuple[QTimeEdit, QSpinBox, QLabel]] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        lay.addWidget(_hint("修改每节课的开始时间与时长，结束时间自动计算。"))
        lay.addWidget(_hint("保存后，周课表预览和日历(ICS)导出会使用新的作息。"))
        lay.addSpacing(6)

        periods = min(20, max(12, max_period, max(period_times or {}, default=0)))
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setMinimumHeight(360)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        header_font = QFont(_UI_FONT, 9, QFont.Bold)
        for col, text in enumerate(("节次", "开始时间", "时长", "结束时间")):
            label = QLabel(text)
            label.setFont(header_font)
            label.setAlignment(Qt.AlignCenter)
            grid.addWidget(label, 0, col)

        prev_end: QTime | None = None
        for period in range(1, periods + 1):
            start_text, end_text = (period_times or {}).get(period, ("", ""))
            if not start_text and prev_end is not None:
                start_text = prev_end.addSecs(10 * 60).toString("HH:mm")
            start = QTime.fromString(start_text, "HH:mm")
            if not start.isValid():
                start = QTime(8, 0)
            duration = _period_duration(start_text, end_text)

            name_label = QLabel(str(period))
            name_label.setAlignment(Qt.AlignCenter)

            time_edit = QTimeEdit(start)
            time_edit.setDisplayFormat("HH:mm")
            time_edit.setFixedWidth(84)

            duration_spin = QSpinBox()
            duration_spin.setRange(5, 240)
            duration_spin.setSuffix(" 分钟")
            duration_spin.setFixedWidth(96)
            duration_spin.setValue(duration)

            end_label = QLabel()
            end_label.setProperty("hint", "true")
            end_label.setAlignment(Qt.AlignCenter)

            grid.addWidget(name_label, period, 0)
            grid.addWidget(time_edit, period, 1)
            grid.addWidget(duration_spin, period, 2)
            grid.addWidget(end_label, period, 3)

            index = period - 1
            self._rows.append((time_edit, duration_spin, end_label))
            time_edit.timeChanged.connect(
                lambda *_, i=index: self._update_end(i)
            )
            duration_spin.valueChanged.connect(
                lambda *_, i=index: self._update_end(i)
            )
            self._update_end(index)
            prev_end = start.addSecs(duration * 60)

        area.setWidget(body)
        lay.addWidget(area, 1)

        reset_row = QHBoxLayout()
        reset_button = QPushButton("恢复默认")
        reset_button.clicked.connect(self._reset_defaults)
        reset_row.addWidget(reset_button)
        reset_row.addStretch(1)
        lay.addLayout(reset_row)

    def _update_end(self, index: int) -> None:
        time_edit, duration_spin, end_label = self._rows[index]
        end = time_edit.time().addSecs(duration_spin.value() * 60)
        end_label.setText(end.toString("HH:mm"))

    def _reset_defaults(self) -> None:
        prev_end: QTime | None = None
        for period, (time_edit, duration_spin, _) in enumerate(self._rows, 1):
            times = DEFAULT_PERIOD_TIMES.get(period)
            if times:
                start = QTime.fromString(times[0], "HH:mm")
                duration = _period_duration(*times)
            else:
                start = (
                    prev_end.addSecs(10 * 60) if prev_end is not None else QTime(8, 0)
                )
                duration = 45
            time_edit.setTime(start)
            duration_spin.setValue(duration)
            self._update_end(period - 1)
            prev_end = start.addSecs(duration * 60)

    def period_times(self) -> dict[int, tuple[str, str]] | None:
        """校验并返回作息时间；结束时间超过 24:00 时返回 None 并弹提示。"""
        result: dict[int, tuple[str, str]] = {}
        for period, (time_edit, duration_spin, _) in enumerate(self._rows, 1):
            start = time_edit.time()
            minutes = start.hour() * 60 + start.minute() + duration_spin.value()
            if minutes >= 24 * 60:
                QMessageBox.warning(
                    self,
                    "提示",
                    f"第 {period} 节的结束时间超过 24:00，请调整开始时间或时长",
                )
                return None
            end = start.addSecs(duration_spin.value() * 60)
            result[period] = (start.toString("HH:mm"), end.toString("HH:mm"))
        return result


class SettingsDialog(QDialog):
    """设置窗口：作息时间 + 导出提醒 + 外观。"""

    def __init__(
        self,
        parent=None,
        period_times=None,
        max_period: int = 12,
        reminders: list[int] | None = None,
        theme_value: str = "light",
    ):
        super().__init__(parent)
        self.result_period_times: dict[int, tuple[str, str]] | None = None
        self.result_reminders: list[int] = []
        self.result_theme: str = theme.LIGHT
        self.setWindowTitle("设置")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        tabs = QTabWidget()
        self.schedule_editor = ScheduleEditor(tabs, period_times, max_period)
        tabs.addTab(self.schedule_editor, " 作息时间 ")

        reminder_tab = QWidget()
        rlay = QVBoxLayout(reminder_tab)
        rlay.setContentsMargins(16, 16, 16, 16)
        rlay.setSpacing(8)
        rlay.addWidget(_hint("导出日历(ICS)时，可为每门课添加最多 3 个开始前提醒。"))
        rlay.addWidget(_hint("提醒按先后顺序排列，后面的提醒时间不能比前面的晚（例如提醒1为30分钟前时，提醒2不能为15分钟前）。"))
        rlay.addSpacing(6)

        self.reminder_combos: list[QComboBox] = []
        for i in range(3):
            row = QHBoxLayout()
            label = QLabel(f"提醒{i + 1}：")
            label.setFixedWidth(52)
            combo = QComboBox()
            combo.addItems(_REMINDER_OPTIONS)
            row.addWidget(label)
            row.addWidget(combo)
            row.addStretch(1)
            rlay.addLayout(row)
            self.reminder_combos.append(combo)
        self._set_reminder_values(reminders or [])
        rlay.addStretch(1)
        tabs.addTab(reminder_tab, " 导出提醒 ")

        theme_tab = QWidget()
        tlay = QVBoxLayout(theme_tab)
        tlay.setContentsMargins(16, 16, 16, 16)
        tlay.setSpacing(8)
        tlay.addWidget(_hint("选择界面主题，保存后立即生效："))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("浅色（白）", theme.LIGHT)
        self.theme_combo.addItem("深色（黑）", theme.DARK)
        self.theme_combo.setCurrentIndex(0 if theme_value != theme.DARK else 1)
        tlay.addWidget(self.theme_combo)
        tlay.addStretch(1)
        tabs.addTab(theme_tab, " 外观 ")

        lay.addWidget(tabs, 1)

        buttons = QHBoxLayout()
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("保存")
        save_button.setDefault(True)
        save_button.clicked.connect(self._save)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        lay.addLayout(buttons)

        self.resize(500, 600)
        self._center_on_parent()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        geo = self.frameGeometry()
        geo.moveCenter(parent.frameGeometry().center())
        self.move(geo.topLeft())

    def _set_reminder_values(self, reminders: list[int]) -> None:
        for combo in self.reminder_combos:
            combo.setCurrentIndex(0)
        for i, minutes in enumerate(reminders[:3]):
            if minutes in _REMINDER_MINUTES:
                self.reminder_combos[i].setCurrentIndex(
                    _REMINDER_MINUTES.index(minutes)
                )

    def _collect_reminders(self) -> list[int] | None:
        """收集并校验最多 3 个提醒；非法时返回 None 并弹提示。"""
        values: list[int] = []
        for i, combo in enumerate(self.reminder_combos):
            minutes = _REMINDER_MINUTES[combo.currentIndex()]
            if minutes is None:
                for later in self.reminder_combos[i + 1:]:
                    if _REMINDER_MINUTES[later.currentIndex()] is not None:
                        QMessageBox.warning(
                            self,
                            "提示",
                            f"提醒{i + 2} 已设置，但提醒{i + 1} 未设置，请按顺序填写。",
                        )
                        return None
                break
            if values and minutes < values[-1]:
                QMessageBox.warning(
                    self,
                    "提示",
                    "提醒时间顺序有误：后面的提醒时间不能比前面的晚。\n"
                    "（例如提醒1为30分钟前时，提醒2不能为15分钟前）",
                )
                return None
            values.append(minutes)
        return values

    def _save(self) -> None:
        period_times = self.schedule_editor.period_times()
        if period_times is None:
            return
        reminders = self._collect_reminders()
        if reminders is None:
            return
        self.result_period_times = period_times
        self.result_reminders = reminders
        self.result_theme = self.theme_combo.currentData()
        self.accept()


class CohortDialog(QDialog):
    """识别后选择要保留的班次（Excel 末列「教学班」）。"""

    def __init__(self, parent=None, counts: dict[str, int] | None = None):
        super().__init__(parent)
        self.result: list[str] | None = None
        self.setWindowTitle("选择班次")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(2)
        title = QLabel("识别到以下班次，请勾选要保留的：")
        title.setFont(QFont(_UI_FONT, 10, QFont.Bold))
        lay.addWidget(title)
        lay.addWidget(_hint("未标注班次的课程会始终保留。"))
        lay.addSpacing(6)

        self.checks: dict[str, QCheckBox] = {}
        for value, count in (counts or {}).items():
            box = QCheckBox(f"{value}（{count} 门）")
            box.setChecked(True)
            lay.addWidget(box)
            self.checks[value] = box

        lay.addSpacing(12)
        buttons = QHBoxLayout()
        select_all = QPushButton("全选")
        select_all.clicked.connect(lambda: self._set_all(True))
        select_none = QPushButton("全不选")
        select_none.clicked.connect(lambda: self._set_all(False))
        ok_button = QPushButton("确定")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self._save)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(select_all)
        buttons.addWidget(select_none)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(ok_button)
        lay.addLayout(buttons)

        self._center_on_parent()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        geo = self.frameGeometry()
        geo.moveCenter(parent.frameGeometry().center())
        self.move(geo.topLeft())

    def _set_all(self, value: bool) -> None:
        for box in self.checks.values():
            box.setChecked(value)

    def _save(self) -> None:
        selected = [value for value, box in self.checks.items() if box.isChecked()]
        if not selected and QMessageBox.question(
            self,
            "确认",
            "没有勾选任何班次，所有带班次的课程都会被移除。是否继续？",
        ) != QMessageBox.Yes:
            return
        self.result = selected
        self.accept()


class SheetSelectDialog(QDialog):
    """识别前选择要导入的工作表（Excel 存在多个工作表时弹出）。"""

    def __init__(self, parent=None, entries: list[tuple[str, str]] | None = None):
        super().__init__(parent)
        self.result: list[tuple[str, str]] | None = None
        self.setWindowTitle("选择工作表")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(2)
        title = QLabel("检测到多个工作表，请勾选要导入的：")
        title.setFont(QFont(_UI_FONT, 10, QFont.Bold))
        lay.addWidget(title)
        lay.addSpacing(6)

        self.checks: list[tuple[tuple[str, str], QCheckBox]] = []
        multi_file = len({path for path, _ in (entries or [])}) > 1
        for path, sheet in (entries or []):
            label = f"{os.path.basename(path)} → {sheet}" if multi_file else sheet
            box = QCheckBox(label)
            box.setChecked(True)
            lay.addWidget(box)
            self.checks.append(((path, sheet), box))

        lay.addSpacing(12)
        buttons = QHBoxLayout()
        select_all = QPushButton("全选")
        select_all.clicked.connect(lambda: self._set_all(True))
        select_none = QPushButton("全不选")
        select_none.clicked.connect(lambda: self._set_all(False))
        ok_button = QPushButton("确定")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self._save)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(select_all)
        buttons.addWidget(select_none)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(ok_button)
        lay.addLayout(buttons)

        self._center_on_parent()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        geo = self.frameGeometry()
        geo.moveCenter(parent.frameGeometry().center())
        self.move(geo.topLeft())

    def _set_all(self, value: bool) -> None:
        for _, box in self.checks:
            box.setChecked(value)

    def _save(self) -> None:
        selected = [key for key, box in self.checks if box.isChecked()]
        if not selected:
            QMessageBox.warning(self, "提示", "请至少选择一个工作表")
            return
        self.result = selected
        self.accept()


class WeekGrid(QWidget):
    """自绘周课表网格。"""

    def __init__(self, timetable: Timetable, parent=None):
        super().__init__(parent)
        self.timetable = timetable
        self._viewport_width = 0
        self._compute()

    def set_timetable(self, timetable: Timetable) -> None:
        self.timetable = timetable
        self.refresh()

    def set_viewport_width(self, width: int) -> None:
        if width != self._viewport_width:
            self._viewport_width = width
            self.refresh()

    def refresh(self) -> None:
        self._compute()
        self.update()

    def _compute(self) -> None:
        courses = self.timetable.courses
        max_period = min(max([12] + [c.period_end for c in courses]), 20)
        head_w, head_h = 92, 36
        avail = self._viewport_width
        if avail > head_w + 7 * 70:
            cell_w = (avail - head_w - 2) / 7.0
        else:
            cell_w = 130.0
        total_w = head_w + cell_w * 7

        # 同一格可能有多门课，按 (星期, 起始节, 结束节) 分组后纵向排开
        groups: dict[tuple[int, int, int], list[tuple[int, Course]]] = {}
        for index, course in enumerate(courses):
            if not (1 <= course.day <= 7 and 1 <= course.period_start <= 20):
                continue
            if course.period_end < course.period_start:
                continue
            groups.setdefault(
                (course.day, course.period_start, course.period_end), []
            ).append((index, course))

        # 课程堆得多的行自动加高，避免文字挤在一起
        base_row_h = 52
        row_heights = [base_row_h] * max_period
        for (_, p_start, _), items in groups.items():
            if p_start <= max_period:
                need = min(240, len(items) * 20 + 20)
                row_heights[p_start - 1] = max(row_heights[p_start - 1], need)
        row_tops = [head_h]
        for height in row_heights:
            row_tops.append(row_tops[-1] + height)

        self._max_period = max_period
        self._head_w = head_w
        self._head_h = head_h
        self._cell_w = cell_w
        self._total_w = total_w
        self._row_heights = row_heights
        self._row_tops = row_tops
        self._groups = groups
        self.setFixedSize(int(round(total_w)), int(round(row_tops[-1])))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        gc = theme.grid_colors()
        painter.fillRect(self.rect(), QColor(gc["bg"]))

        max_period = self._max_period
        head_w, head_h = self._head_w, self._head_h
        cell_w = self._cell_w
        total_w = self._total_w
        row_heights = self._row_heights
        row_tops = self._row_tops

        painter.fillRect(QRectF(0, 0, total_w, head_h), QColor(gc["header"]))
        painter.setPen(QColor("white"))
        painter.setFont(QFont(_UI_FONT, 9, QFont.Bold))
        painter.drawText(
            QRectF(0, 0, head_w, head_h), Qt.AlignCenter, "节次"
        )
        painter.setFont(QFont(_UI_FONT, 10, QFont.Bold))
        for i, name in enumerate(DAY_NAMES):
            painter.drawText(
                QRectF(head_w + cell_w * i, 0, cell_w, head_h),
                Qt.AlignCenter, name,
            )

        line_pen = QPen(QColor(gc["line"]), 1)
        painter.setFont(QFont(_UI_FONT, 7))
        period_times = self.timetable.period_times
        for p in range(1, max_period + 1):
            y = row_tops[p - 1]
            h = row_heights[p - 1]
            if p % 2 == 0:
                painter.fillRect(QRectF(0, y, total_w, h), QColor(gc["alt"]))
            painter.setPen(line_pen)
            painter.drawLine(0, y, int(round(total_w)), y)
            start, end = period_times.get(p, ("", ""))
            label = f"{p}\n{start}\n{end}" if start else str(p)
            painter.setPen(QColor(gc["period"]))
            painter.drawText(QRectF(0, y, head_w, h), Qt.AlignCenter, label)

        total_h = int(round(row_tops[-1]))
        painter.setPen(line_pen)
        painter.drawLine(0, total_h, int(round(total_w)), total_h)
        painter.drawLine(head_w, 0, head_w, total_h)
        for i in range(1, 8):
            x = int(round(head_w + cell_w * i))
            painter.drawLine(x, head_h, x, total_h)

        for (day, p_start, p_end), items in self._groups.items():
            x = head_w + (day - 1) * cell_w
            y = row_tops[p_start - 1]
            height = row_tops[min(p_end, max_period)] - y
            inner_w = max(10.0, cell_w - 10)

            if len(items) == 1:
                index, course = items[0]
                color = _GRID_COLORS[index % len(_GRID_COLORS)]
                rect = QRectF(x + 2, y + 2, cell_w - 4, height - 4)
                painter.fillRect(rect, QColor(color))
                painter.setPen(QPen(QColor("#B0BEC5"), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)

                painter.save()
                painter.setClipRect(rect)
                painter.setPen(QColor("#263238"))
                painter.setFont(QFont(_UI_FONT, 7, QFont.Bold))
                painter.drawText(
                    QRectF(x + 5, y + 3, inner_w, max(10.0, height - 31)),
                    Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
                    course.name,
                )
                meta = self._meta_text(course)
                if meta:
                    font = QFont(_UI_FONT, 6)
                    painter.setFont(font)
                    painter.setPen(QColor("#546E7A"))
                    painter.drawText(
                        QRectF(x + 5, y + 23, inner_w, 14),
                        Qt.AlignLeft | Qt.AlignTop,
                        QFontMetrics(font).elidedText(
                            meta, Qt.ElideRight, int(inner_w)
                        ),
                    )
                painter.restore()
                continue

            slot_h = (height - 4) / len(items)
            for slot, (index, course) in enumerate(items):
                sy = y + 2 + slot * slot_h
                slot_bottom = min(y + height - 2, sy + slot_h - 1)
                rect = QRectF(x + 2, sy, cell_w - 4, max(4.0, slot_bottom - sy))
                color = _GRID_COLORS[index % len(_GRID_COLORS)]
                painter.fillRect(rect, QColor(color))
                painter.setPen(QPen(QColor("#B0BEC5"), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)

                painter.save()
                painter.setClipRect(rect)
                painter.setPen(QColor("#263238"))
                name_font = QFont(_UI_FONT, 6, QFont.Bold)
                painter.setFont(name_font)
                painter.drawText(
                    QRectF(x + 5, sy + 1, inner_w, 12),
                    Qt.AlignLeft | Qt.AlignTop,
                    QFontMetrics(name_font).elidedText(
                        course.name, Qt.ElideRight, int(inner_w)
                    ),
                )
                if slot_h >= 23:
                    meta = self._meta_text(course)
                    if meta:
                        meta_font = QFont(_UI_FONT, 5)
                        painter.setFont(meta_font)
                        painter.setPen(QColor("#546E7A"))
                        painter.drawText(
                            QRectF(x + 5, sy + 12, inner_w, 10),
                            Qt.AlignLeft | Qt.AlignTop,
                            QFontMetrics(meta_font).elidedText(
                                meta, Qt.ElideRight, int(inner_w)
                            ),
                        )
                painter.restore()

        painter.end()

    @staticmethod
    def _meta_text(course: Course) -> str:
        parts = []
        if course.teacher:
            parts.append(course.teacher)
        if course.location:
            parts.append(course.location)
        if course.weeks:
            parts.append(course.weeks_label)
        return " ".join(parts)


class GridScrollArea(QScrollArea):
    def __init__(self, grid: WeekGrid, parent=None):
        super().__init__(parent)
        self._grid = grid
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setWidget(grid)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._grid.set_viewport_width(self.viewport().width())

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)


class TimetableApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("课表识别助手 - PDF / Excel")
        self.resize(1220, 800)
        self.setMinimumSize(1020, 660)

        self.timetable = Timetable()
        self.timetable.period_times = load_period_times()
        self.files: list[str] = []
        self.queue: queue.Queue = queue.Queue()
        self.parsing = False

        self._build_ui()
        self._bind_shortcuts()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_queue)
        self._timer.start(120)

        self._log("欢迎使用课表识别助手。")
        self._log("1. 点击「添加文件」选择 PDF 或 Excel 课表；")
        self._log("2. 点击「开始识别」；")
        self._log("3. 双击结果表格中的课程可以修正识别错误；")
        self._log("4. 导出 Excel / JSON / 日历(ICS)。")
        self._log("提示：日历导出以工具栏里的「第 1 周周一」为基准。")
        self._log(f"崩溃日志：{get_log_path()}")

    # ------------------------------------------------------------ 构建界面

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(14, 12, 14, 10)
        outer.setSpacing(6)

        title_row = QHBoxLayout()
        title = QLabel("课表识别助手")
        title.setFont(QFont(_UI_FONT, 15, QFont.Bold))
        title.setObjectName("appTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(QLabel("第 1 周周一："))
        self.week1_edit = QLineEdit(_default_monday().isoformat())
        self.week1_edit.setMaximumWidth(110)
        title_row.addWidget(self.week1_edit)
        title_row.addWidget(_hint("YYYY-MM-DD"))
        outer.addLayout(title_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        add_button = QPushButton("添加文件")
        add_button.clicked.connect(self.add_files)
        remove_button = QPushButton("移除文件")
        remove_button.clicked.connect(self.remove_files)
        self.parse_button = QPushButton("开始识别")
        self.parse_button.clicked.connect(self.start_parse)
        settings_button = QPushButton("设置")
        settings_button.setToolTip("作息时间与导出提醒设置")
        settings_button.clicked.connect(self.open_settings)
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addSpacing(10)
        button_row.addWidget(self.parse_button)
        button_row.addWidget(settings_button)

        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        button_row.addSpacing(8)
        button_row.addWidget(separator)
        button_row.addSpacing(8)
        button_row.addWidget(QLabel("导出："))
        for text, handler in (
            ("Excel", self.export_xlsx),
            ("JSON", self.export_json_file),
            ("日历 ICS", self.export_ics_file),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            button_row.addWidget(button)
        button_row.addStretch(1)
        outer.addLayout(button_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([560, 660])
        outer.addWidget(splitter, 1)

        self.statusBar().showMessage("就绪")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(170)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        files_box = QGroupBox("文件列表")
        files_lay = QVBoxLayout(files_box)
        files_lay.setContentsMargins(8, 8, 8, 8)
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setFixedHeight(96)
        files_lay.addWidget(self.file_list)
        lay.addWidget(files_box)

        courses_box = QGroupBox("识别结果（双击编辑课程）")
        courses_lay = QVBoxLayout(courses_box)
        courses_lay.setContentsMargins(8, 8, 8, 8)
        courses_lay.setSpacing(6)

        actions = QHBoxLayout()
        add_course = QPushButton("新增课程")
        add_course.clicked.connect(self.add_course)
        edit_course = QPushButton("编辑选中")
        edit_course.clicked.connect(self.edit_selected)
        delete_course = QPushButton("删除选中")
        delete_course.clicked.connect(self.delete_selected)
        actions.addWidget(add_course)
        actions.addWidget(edit_course)
        actions.addWidget(delete_course)
        actions.addStretch(1)
        courses_lay.addLayout(actions)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["课程名称", "星期", "节次", "周次", "教师", "教室"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setFont(QFont(_UI_FONT, 10, QFont.Bold))
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setStretchLastSection(False)
        for col, width in enumerate((140, 44, 56, 92, 58, 80)):
            self.table.setColumnWidth(col, width)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        courses_lay.addWidget(self.table, 1)

        lay.addWidget(courses_box, 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        tabs = QTabWidget()

        grid_tab = QWidget()
        grid_lay = QVBoxLayout(grid_tab)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        self.grid = WeekGrid(self.timetable)
        self.grid_scroll = GridScrollArea(self.grid)
        grid_lay.addWidget(self.grid_scroll)
        tabs.addTab(grid_tab, " 周课表预览 ")

        log_tab = QWidget()
        log_lay = QVBoxLayout(log_tab)
        log_lay.setContentsMargins(0, 0, 0, 0)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(5000)
        self.log_text.setObjectName("logText")
        log_lay.addWidget(self.log_text)
        tabs.addTab(log_tab, " 识别日志 ")

        return tabs

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.add_files)
        QShortcut(QKeySequence("F5"), self, activated=self.start_parse)

    # ------------------------------------------------------------ 文件操作

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择课表文件",
            "",
            "课表文件 (*.pdf *.xlsx *.xlsm *.xls);;PDF (*.pdf);;"
            "Excel (*.xlsx *.xlsm *.xls);;所有文件 (*)",
        )
        added = 0
        for path in paths:
            path = os.path.normpath(path)
            if path not in self.files:
                self.files.append(path)
                added += 1
            else:
                self._log(f"已忽略重复文件：{os.path.basename(path)}")
        if added:
            self._refresh_file_list()
            self._log(f"已添加 {added} 个文件")
        self.statusBar().showMessage(f"就绪 · 已添加 {len(self.files)} 个文件")

    def remove_files(self) -> None:
        selected = sorted(
            {self.file_list.row(item) for item in self.file_list.selectedItems()},
            reverse=True,
        )
        if not selected:
            return
        for index in selected:
            if 0 <= index < len(self.files):
                del self.files[index]
        self._refresh_file_list()
        self.statusBar().showMessage(f"就绪 · 已添加 {len(self.files)} 个文件")

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        for path in self.files:
            self.file_list.addItem(os.path.basename(path))

    # ------------------------------------------------------------ 设置

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self,
            self.timetable.period_times,
            self.timetable.max_period(),
            load_reminders(),
            load_theme(),
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        if dialog.result_period_times is not None:
            self.timetable.period_times = dialog.result_period_times
            save_period_times(dialog.result_period_times)
            self.grid.refresh()
        save_reminders(dialog.result_reminders)
        save_theme(dialog.result_theme)
        theme.apply_theme(QApplication.instance(), dialog.result_theme)
        self._log("设置已保存")
        self.statusBar().showMessage("设置已保存")

    # ------------------------------------------------------------ 识别

    def start_parse(self) -> None:
        if self.parsing:
            return
        if not self.files:
            QMessageBox.information(self, "提示", "请先添加 PDF 或 Excel 课表文件")
            return
        if self.timetable.courses:
            if QMessageBox.question(
                self,
                "重新识别",
                "识别结果将替换当前课程列表（包括手动修改），是否继续？",
            ) != QMessageBox.Yes:
                return
        sheet_selection = self._collect_sheet_selection()
        if sheet_selection is None:
            return
        self.parsing = True
        self.parse_button.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage("正在识别…")
        files = list(self.files)
        threading.Thread(
            target=self._parse_worker, args=(files, sheet_selection), daemon=True
        ).start()

    def _collect_sheet_selection(self) -> dict[str, list[str]] | None:
        """枚举各 Excel 文件的工作表；有多个可选时弹窗让用户勾选。

        返回 {文件路径: [选中的工作表名]}；用户取消返回 None。
        """
        from .excel_parser import list_excel_sheets

        sheet_map: dict[str, list[str]] = {}
        entries: list[tuple[str, str]] = []
        for path in self.files:
            if not path.lower().endswith((".xlsx", ".xlsm", ".xls")):
                continue
            try:
                names = list_excel_sheets(path)
            except Exception as exc:
                self._log(f"读取工作表失败：{os.path.basename(path)} — {exc}")
                names = []
            if names:
                sheet_map[path] = names
                for name in names:
                    entries.append((path, name))

        # 没有任何一个 Excel 有多个工作表时，无需询问
        if not entries or all(len(v) <= 1 for v in sheet_map.values()):
            return sheet_map

        dialog = SheetSelectDialog(self, entries)
        if dialog.exec_() != QDialog.Accepted:
            return None
        selected: dict[str, list[str]] = {path: [] for path in sheet_map}
        for path, sheet in dialog.result or []:
            selected[path].append(sheet)
        return selected

    def _parse_worker(self, files: list[str], sheet_selection: dict[str, list[str]] | None) -> None:
        def log(msg: str) -> None:
            self.queue.put(("log", msg))

        all_courses: list[Course] = []
        for path in files:
            log(f"开始处理：{os.path.basename(path)}")
            try:
                if path.lower().endswith(".pdf"):
                    found = parse_pdf(path, log)
                else:
                    sheet_names = sheet_selection.get(path) if sheet_selection else None
                    found = parse_excel(path, log, sheet_names=sheet_names)
                log(f"完成：{os.path.basename(path)}，识别到 {len(found)} 条课程")
                all_courses.extend(found)
            except Exception as exc:
                log(f"处理失败：{os.path.basename(path)} — {exc}")
        self.queue.put(("done", (all_courses, files)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self._on_parse_done(*payload)
        except queue.Empty:
            pass

    def _choose_cohorts(self, courses: list[Course]) -> list[Course] | None:
        """识别到多个班次时弹窗询问要保留哪些；返回 None 表示不筛选。"""
        counts: dict[str, int] = {}
        for course in courses:
            if course.note:
                counts[course.note] = counts.get(course.note, 0) + 1
        if len(counts) < 2:
            return None

        dialog = CohortDialog(self, {value: counts[value] for value in sorted(counts)})
        if dialog.exec_() != QDialog.Accepted:
            return None
        selected = set(dialog.result or [])
        kept = [c for c in courses if not c.note or c.note in selected]
        self._log(
            f"按班次筛选：保留 {', '.join(dialog.result or []) or '无'}，"
            f"课程 {len(kept)} 条"
        )
        return kept

    def _on_parse_done(self, courses: list[Course], files: list[str]) -> None:
        timetable = Timetable()
        timetable.courses = list(courses)
        timetable.period_times = dict(self.timetable.period_times)
        removed = timetable.dedupe()
        timetable.sources = list(files)
        self.timetable = timetable
        self.grid.set_timetable(timetable)
        self.parsing = False
        self.progress.hide()
        self.parse_button.setEnabled(True)

        parsed_any = bool(timetable.courses)
        kept = self._choose_cohorts(timetable.courses)
        if kept is not None:
            dropped = len(timetable.courses) - len(kept)
            timetable.courses = kept
            if dropped:
                self._log(f"已移除 {dropped} 条其他班次的课程")

        self._refresh_courses()
        summary = f"识别完成：{len(timetable.courses)} 条课程"
        if removed:
            summary += f"（去除重复 {removed} 条）"
        self._log(summary)
        self.statusBar().showMessage(summary)

        if self._conflicts():
            QMessageBox.warning(
                self,
                "检测到时间冲突",
                "以下课程在同一时段上课，可能存在时间冲突：\n\n"
                f"{self._conflict_summary()}\n\n"
                "这些课程已在「识别结果」中用浅红色高亮，请确认是否需要删除或修改。",
            )

        if not timetable.courses and parsed_any:
            self._log("班次筛选后没有剩余课程")
        elif not timetable.courses:
            QMessageBox.warning(
                self,
                "未识别到课程",
                "没有识别到课程。请查看「识别日志」了解原因。\n"
                "如果是扫描版 PDF，请确认系统已安装中文 OCR 语言包"
                "（设置 → 时间和语言 → 语言）；"
                "也可以把样例文件提供给开发者调整解析规则。",
            )

    # ------------------------------------------------------------ 课程编辑

    def _refresh_courses(self) -> None:
        table = self.table
        conflict_rows = {
            index for pair in find_conflicts(self.timetable.courses) for index in pair
        }
        table.setUpdatesEnabled(False)
        table.clearContents()
        table.setRowCount(len(self.timetable.courses))
        for row, course in enumerate(self.timetable.courses):
            periods = (
                f"{course.period_start}节"
                if course.period_start == course.period_end
                else f"{course.period_start}-{course.period_end}节"
            )
            values = (
                course.name,
                course.day_name,
                periods,
                course.weeks_label,
                course.teacher,
                course.location,
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                alignment = (
                    Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter
                )
                item.setTextAlignment(alignment)
                if row in conflict_rows:
                    item.setBackground(QColor(theme.conflict_color()))
                table.setItem(row, col, item)
        table.setUpdatesEnabled(True)
        self.grid.refresh()

    def _conflicts(self) -> list[tuple[int, int]]:
        return find_conflicts(self.timetable.courses)

    def _conflict_summary(self) -> str:
        """把时间冲突按「星期 + 重叠节次」分组，生成简短文本。"""
        groups: dict[tuple[int, int, int], set[str]] = {}
        for i, j in self._conflicts():
            a = self.timetable.courses[i]
            b = self.timetable.courses[j]
            ps = max(a.period_start, b.period_start)
            pe = min(a.period_end, b.period_end)
            groups.setdefault((a.day, ps, pe), set()).update((a.name, b.name))
        lines = []
        for day, ps, pe in sorted(groups):
            day_name = DAY_NAMES[day - 1]
            periods = f"{ps}节" if ps == pe else f"{ps}-{pe}节"
            names = "、".join(sorted(groups[(day, ps, pe)]))
            lines.append(f"· {day_name} {periods}：{names}")
        return "\n".join(lines)

    def _on_cell_double_clicked(self, row: int, _column: int) -> None:
        self._edit_course(row)

    def add_course(self) -> None:
        dialog = CourseDialog(self, None, self.timetable.period_times)
        if dialog.exec_() == QDialog.Accepted and dialog.result:
            self.timetable.courses.append(dialog.result)
            self._refresh_courses()
            self._log(f"新增课程：{dialog.result.name}")
            self.statusBar().showMessage(
                f"共 {len(self.timetable.courses)} 条课程记录"
            )

    def edit_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.timetable.courses):
            QMessageBox.information(self, "提示", "请先在列表中选择一门课程")
            return
        self._edit_course(row)

    def _edit_course(self, index: int) -> None:
        if not 0 <= index < len(self.timetable.courses):
            return
        dialog = CourseDialog(
            self, self.timetable.courses[index], self.timetable.period_times
        )
        if dialog.exec_() != QDialog.Accepted or not dialog.result:
            return
        self.timetable.courses[index] = dialog.result
        self._refresh_courses()
        self.table.selectRow(index)
        self.statusBar().showMessage(
            f"共 {len(self.timetable.courses)} 条课程记录"
        )

    def delete_selected(self) -> None:
        indices = sorted(
            {item.row() for item in self.table.selectionModel().selectedRows()},
            reverse=True,
        )
        if not indices:
            QMessageBox.information(self, "提示", "请先在列表中选择要删除的课程")
            return
        for index in indices:
            if 0 <= index < len(self.timetable.courses):
                self.timetable.courses.pop(index)
        self._refresh_courses()
        self._log(f"删除了 {len(indices)} 条课程")
        self.statusBar().showMessage(
            f"共 {len(self.timetable.courses)} 条课程记录"
        )

    # ------------------------------------------------------------ 导出

    def _ensure_courses(self) -> bool:
        if not self.timetable.courses:
            QMessageBox.information(
                self, "提示", "暂时没有可导出的课程，请先识别或新增课程"
            )
            return False
        return True

    def _ask_save(self, default_name: str, filter_text: str, suffix: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出课表", default_name, filter_text
        )
        if not path:
            return None
        if not path.lower().endswith(suffix):
            path += suffix
        return path

    def _after_export(self, path: str) -> None:
        self._log(f"已导出：{path}")
        self.statusBar().showMessage(f"已导出：{os.path.basename(path)}")
        if QMessageBox.question(
            self,
            "导出成功",
            f"已保存到：\n{path}\n\n是否打开所在文件夹？",
        ) == QMessageBox.Yes:
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                pass

    def export_xlsx(self) -> None:
        if not self._ensure_courses():
            return
        path = self._ask_save("课表.xlsx", "Excel 工作簿 (*.xlsx)", ".xlsx")
        if not path:
            return
        try:
            export_xlsx(self.timetable.courses, path, self.timetable.period_times)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self._after_export(path)

    def export_json_file(self) -> None:
        if not self._ensure_courses():
            return
        path = self._ask_save("课表.json", "JSON 文件 (*.json)", ".json")
        if not path:
            return
        try:
            export_json(self.timetable.courses, path, self.timetable.sources)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self._after_export(path)

    def export_ics_file(self) -> None:
        if not self._ensure_courses():
            return
        try:
            first_monday = date.fromisoformat(self.week1_edit.text().strip())
        except ValueError:
            QMessageBox.warning(
                self,
                "日期格式错误",
                "「第 1 周周一」请填写 YYYY-MM-DD，例如 2026-09-07",
            )
            return
        reminders = load_reminders()
        path = self._ask_save("课程表.ics", "iCalendar 日历 (*.ics)", ".ics")
        if not path:
            return
        try:
            aligned, count = export_ics(
                self.timetable.courses,
                path,
                first_monday,
                self.timetable.period_times,
                reminders,
            )
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        if aligned != first_monday:
            self._log(
                f"日期已对齐到该周周一：{aligned.isoformat()}"
                f"（原输入 {first_monday.isoformat()}）"
            )
        missing_weeks = sum(1 for c in self.timetable.courses if not c.weeks)
        if missing_weeks:
            self._log(f"{missing_weeks} 条课程未识别到周次，已按 1-16 周写入日历")
        if reminders:
            labels = "、".join(_REMINDER_LABELS.get(m, f"{m} 分钟") for m in reminders)
            reminder_text = f"，提醒：{labels}"
        else:
            reminder_text = "（无提醒）"
        self._log(f"日历导出完成，共 {count} 个事件{reminder_text}")
        self._after_export(path)

    # ------------------------------------------------------------ 日志

    def _log(self, message: str) -> None:
        self.log_text.appendPlainText(message.rstrip())
        bar = self.log_text.verticalScrollBar()
        bar.setValue(bar.maximum())
