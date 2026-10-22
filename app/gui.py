"""tkinter 图形界面。"""
from __future__ import annotations

import os
import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, timedelta
from tkinter import filedialog, messagebox, ttk

from .exporters import export_ics, export_json, export_xlsx
from .excel_parser import parse_excel
from .models import Course, DAY_NAMES, DEFAULT_PERIOD_TIMES, Timetable, compress_weeks
from .parsing import extract_weeks
from .pdf_parser import parse_pdf

_UI_FONT = "Microsoft YaHei UI"
_GRID_COLORS = [
    "#FFE0B2", "#C8E6C9", "#BBDEFB", "#F8BBD0",
    "#E1BEE7", "#B2EBF2", "#FFF9C4", "#D7CCC8",
]


def _default_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


_fit_font_cache: dict[tuple, tkfont.Font] = {}


def _fit_text(widget: tk.Misc, text: str, size: int, weight: str, max_width: float) -> str:
    """把文字截断到单行能放下的宽度，超出部分用省略号。"""
    key = (str(widget.winfo_toplevel()), size, weight)
    font = _fit_font_cache.get(key)
    if font is None:
        font = tkfont.Font(root=widget, family=_UI_FONT, size=size, weight=weight)
        _fit_font_cache[key] = font
    if max_width <= 0 or font.measure(text) <= max_width:
        return text
    while text and font.measure(text + "…") > max_width:
        text = text[:-1]
    return (text + "…") if text else ""


def _pick_font(root: tk.Misc) -> None:
    families = set(tkfont.families(root))
    family = _UI_FONT if _UI_FONT in families else "Microsoft YaHei"
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=family, size=10)
        except tk.TclError:
            pass


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


class CourseDialog(tk.Toplevel):
    def __init__(self, master, course: Course | None = None, period_times=None):
        super().__init__(master)
        self.result: Course | None = None
        self.period_times = period_times or DEFAULT_PERIOD_TIMES
        self.title("编辑课程" if course else "新增课程")
        self.resizable(False, False)
        self.transient(master)

        pad = {"padx": 6, "pady": 7}
        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        self.name_var = tk.StringVar(value=course.name if course else "")
        self.day_var = tk.StringVar(
            value=course.day_name if course else DAY_NAMES[0]
        )
        self.ps_var = tk.StringVar(value=str(course.period_start if course else 1))
        self.pe_var = tk.StringVar(value=str(course.period_end if course else 2))
        self.weeks_var = tk.StringVar(
            value=compress_weeks(course.weeks) if course else ""
        )
        self.teacher_var = tk.StringVar(value=course.teacher if course else "")
        self.location_var = tk.StringVar(value=course.location if course else "")
        self.start_var = tk.StringVar(value=course.time_start if course else "")
        self.end_var = tk.StringVar(value=course.time_end if course else "")

        ttk.Label(frm, text="课程名称").grid(row=0, column=0, sticky="e", **pad)
        name_entry = ttk.Entry(frm, textvariable=self.name_var, width=34)
        name_entry.grid(row=0, column=1, columnspan=3, sticky="we", **pad)

        ttk.Label(frm, text="星期").grid(row=1, column=0, sticky="e", **pad)
        ttk.Combobox(
            frm, textvariable=self.day_var, values=DAY_NAMES,
            state="readonly", width=8,
        ).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(frm, text="节次").grid(row=1, column=2, sticky="e", **pad)
        period_frame = ttk.Frame(frm)
        period_frame.grid(row=1, column=3, sticky="w", **pad)
        ttk.Spinbox(
            period_frame, from_=1, to=20, width=4, textvariable=self.ps_var
        ).pack(side="left")
        ttk.Label(period_frame, text="至").pack(side="left", padx=4)
        ttk.Spinbox(
            period_frame, from_=1, to=20, width=4, textvariable=self.pe_var
        ).pack(side="left")

        ttk.Label(frm, text="周次").grid(row=2, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.weeks_var, width=34).grid(
            row=2, column=1, columnspan=3, sticky="we", **pad
        )
        ttk.Label(
            frm, text="例如：1-16、1-16(单)、1,3,5-9；留空表示未指定",
            foreground="#78909C",
        ).grid(row=3, column=1, columnspan=3, sticky="w", padx=6)

        ttk.Label(frm, text="教师").grid(row=4, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.teacher_var, width=12).grid(
            row=4, column=1, sticky="we", **pad
        )
        ttk.Label(frm, text="教室").grid(row=4, column=2, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.location_var, width=12).grid(
            row=4, column=3, sticky="we", **pad
        )

        ttk.Label(frm, text="时间").grid(row=5, column=0, sticky="e", **pad)
        time_frame = ttk.Frame(frm)
        time_frame.grid(row=5, column=1, columnspan=3, sticky="w", **pad)
        ttk.Entry(time_frame, textvariable=self.start_var, width=8).pack(side="left")
        ttk.Label(time_frame, text="-").pack(side="left", padx=4)
        ttk.Entry(time_frame, textvariable=self.end_var, width=8).pack(side="left")
        ttk.Label(
            time_frame, text="可留空，按标准作息时间", foreground="#78909C"
        ).pack(side="left", padx=8)

        buttons = ttk.Frame(frm)
        buttons.grid(row=6, column=0, columnspan=4, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="保存", command=self._save).pack(side="right")
        ttk.Button(buttons, text="取消", command=self.destroy).pack(
            side="right", padx=(0, 8)
        )

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._save())
        name_entry.focus_set()

        self.update_idletasks()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - self.winfo_reqwidth()) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请填写课程名称", parent=self)
            return
        try:
            ps = int(self.ps_var.get())
            pe = int(self.pe_var.get())
        except ValueError:
            messagebox.showwarning("提示", "节次必须是数字", parent=self)
            return
        if ps > pe:
            ps, pe = pe, ps
        if not (1 <= ps <= 20 and 1 <= pe <= 20):
            messagebox.showwarning("提示", "节次需在 1-20 之间", parent=self)
            return

        weeks_text = self.weeks_var.get().strip()
        weeks = _normalize_weeks_input(weeks_text)
        if weeks_text and not weeks:
            messagebox.showwarning(
                "提示", "周次格式无法识别，请参考：1-16、1-16(单)、1,3,5", parent=self
            )
            return

        start = _normalize_clock(self.start_var.get())
        end = _normalize_clock(self.end_var.get())
        if start is None or end is None:
            messagebox.showwarning("提示", "时间格式应为 HH:MM，例如 08:00", parent=self)
            return
        if bool(start) != bool(end):
            messagebox.showwarning("提示", "开始时间和结束时间请同时填写或同时留空", parent=self)
            return
        if start and end and end <= start:
            messagebox.showwarning("提示", "结束时间需晚于开始时间", parent=self)
            return

        self.result = Course(
            name=name,
            day=DAY_NAMES.index(self.day_var.get()) + 1,
            period_start=ps,
            period_end=pe,
            teacher=self.teacher_var.get().strip(),
            location=self.location_var.get().strip(),
            weeks=weeks,
            weeks_text=compress_weeks(weeks),
            time_start=start,
            time_end=end,
        )
        self.destroy()


class CohortDialog(tk.Toplevel):
    """识别后选择要保留的班次（Excel 末列「教学班」）。"""

    def __init__(self, master, counts: dict[str, int]):
        super().__init__(master)
        self.result: list[str] | None = None
        self.title("选择班次")
        self.resizable(False, False)
        self.transient(master)

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(
            frm, text="识别到以下班次，请勾选要保留的：",
            font=(_UI_FONT, 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frm, text="未标注班次的课程会始终保留。",
            foreground="#78909C",
        ).pack(anchor="w", pady=(2, 8))

        values = ttk.Frame(frm)
        values.pack(fill="x")
        self.vars: dict[str, tk.BooleanVar] = {}
        for value, count in counts.items():
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(
                values, text=f"{value}（{count} 门）", variable=var
            ).pack(anchor="w", pady=1)
            self.vars[value] = var

        buttons = ttk.Frame(frm)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="全选", command=lambda: self._set_all(True)).pack(
            side="left"
        )
        ttk.Button(buttons, text="全不选", command=lambda: self._set_all(False)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="确定", command=self._save).pack(side="right")
        ttk.Button(buttons, text="取消", command=self.destroy).pack(
            side="right", padx=(0, 8)
        )

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = master.winfo_rootx() + max(
            0, (master.winfo_width() - self.winfo_reqwidth()) // 2
        )
        y = master.winfo_rooty() + max(
            0, (master.winfo_height() - self.winfo_reqheight()) // 3
        )
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _set_all(self, value: bool) -> None:
        for var in self.vars.values():
            var.set(value)

    def _save(self) -> None:
        selected = [value for value, var in self.vars.items() if var.get()]
        if not selected and not messagebox.askyesno(
            "确认",
            "没有勾选任何班次，所有带班次的课程都会被移除。是否继续？",
            parent=self,
        ):
            return
        self.result = selected
        self.destroy()


class TimetableApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("课表识别助手 - PDF / Excel")
        self.geometry("1220x800")
        self.minsize(1020, 660)

        _pick_font(self)
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=(_UI_FONT, 15, "bold"), foreground="#263238")
        style.configure("Hint.TLabel", foreground="#78909C")
        style.configure("Treeview", rowheight=26, font=(_UI_FONT, 9))
        style.configure("Treeview.Heading", font=(_UI_FONT, 10, "bold"))

        self.timetable = Timetable()
        self.files: list[str] = []
        self.queue: queue.Queue = queue.Queue()
        self.parsing = False

        self.week1_var = tk.StringVar(value=_default_monday().isoformat())
        self.status_var = tk.StringVar(value="就绪")

        self._build_toolbar()
        self._build_main()
        self._build_statusbar()

        self.bind("<Control-o>", lambda e: self.add_files())
        self.bind("<F5>", lambda e: self.start_parse())

        self.after(120, self._poll_queue)
        self.after(600, self._set_initial_sash)
        self._log("欢迎使用课表识别助手。")
        self._log("1. 点击「添加文件」选择 PDF 或 Excel 课表；")
        self._log("2. 点击「开始识别」；")
        self._log("3. 双击结果表格中的课程可以修正识别错误；")
        self._log("4. 导出 Excel / JSON / 日历(ICS)。")
        self._log("提示：日历导出以工具栏里的「第 1 周周一」为基准。")

    # ------------------------------------------------------------ 构建界面

    def _set_initial_sash(self, attempts: int = 0) -> None:
        try:
            if self.main_pane.winfo_width() <= 1:
                raise tk.TclError("布局尚未完成")
            self.main_pane.sashpos(0, 560)
        except tk.TclError:
            if attempts < 20:
                self.after(150, lambda: self._set_initial_sash(attempts + 1))


    def _build_toolbar(self) -> None:
        top = ttk.Frame(self, padding=(14, 12, 14, 4))
        top.pack(fill="x")
        ttk.Label(top, text="课表识别助手", style="Title.TLabel").pack(side="left")
        date_frame = ttk.Frame(top)
        date_frame.pack(side="right")
        ttk.Label(date_frame, text="第 1 周周一：").pack(side="left")
        ttk.Entry(date_frame, textvariable=self.week1_var, width=12).pack(side="left")
        ttk.Label(
            date_frame, text="YYYY-MM-DD", style="Hint.TLabel"
        ).pack(side="left", padx=(6, 0))

        bar = ttk.Frame(self, padding=(14, 6, 14, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="添加文件", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="移除文件", command=self.remove_files).pack(
            side="left", padx=(6, 16)
        )
        self.parse_button = ttk.Button(
            bar, text="开始识别", command=self.start_parse, style="Accent.TButton"
        )
        self.parse_button.pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=14)
        ttk.Label(bar, text="导出：").pack(side="left")
        ttk.Button(bar, text="Excel", command=self.export_xlsx).pack(
            side="left", padx=(4, 4)
        )
        ttk.Button(bar, text="JSON", command=self.export_json_file).pack(
            side="left", padx=4
        )
        ttk.Button(bar, text="日历 ICS", command=self.export_ics_file).pack(
            side="left", padx=4
        )

    def _build_main(self) -> None:
        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=14, pady=(4, 6))
        self.main_pane = main

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=5)
        main.add(right, weight=6)

        files_box = ttk.Labelframe(left, text="文件列表", padding=8)
        files_box.pack(fill="x")
        file_frame = ttk.Frame(files_box)
        file_frame.pack(fill="x")
        self.file_list = tk.Listbox(
            file_frame, height=4, activestyle="none",
            font=(_UI_FONT, 9), selectmode=tk.EXTENDED,
        )
        file_scroll = ttk.Scrollbar(file_frame, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=file_scroll.set)
        self.file_list.pack(side="left", fill="x", expand=True)
        file_scroll.pack(side="right", fill="y")

        courses_box = ttk.Labelframe(
            left, text="识别结果（双击编辑课程）", padding=8
        )
        courses_box.pack(fill="both", expand=True, pady=(8, 0))

        actions = ttk.Frame(courses_box)
        actions.pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="新增课程", command=self.add_course).pack(side="left")
        ttk.Button(actions, text="编辑选中", command=self.edit_selected).pack(
            side="left", padx=6
        )
        ttk.Button(actions, text="删除选中", command=self.delete_selected).pack(side="left")

        tree_frame = ttk.Frame(courses_box)
        tree_frame.pack(fill="both", expand=True)
        columns = ("name", "day", "periods", "weeks", "teacher", "location")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "name": ("课程名称", 140),
            "day": ("星期", 44),
            "periods": ("节次", 56),
            "weeks": ("周次", 92),
            "teacher": ("教师", 58),
            "location": ("教室", 80),
        }
        for col, (title, width) in headings.items():
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="center" if col != "name" else "w")
        tree_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)

        grid_tab = ttk.Frame(notebook)
        notebook.add(grid_tab, text=" 周课表预览 ")
        canvas_frame = ttk.Frame(grid_tab)
        canvas_frame.pack(fill="both", expand=True)
        self.grid_canvas = tk.Canvas(
            canvas_frame, background="white", highlightthickness=0
        )
        cx = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.grid_canvas.xview)
        cy = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.grid_canvas.yview)
        self.grid_canvas.configure(xscrollcommand=cx.set, yscrollcommand=cy.set)
        self.grid_canvas.grid(row=0, column=0, sticky="nsew")
        cy.grid(row=0, column=1, sticky="ns")
        cx.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.grid_canvas.bind(
            "<MouseWheel>",
            lambda e: self.grid_canvas.yview_scroll(int(-e.delta / 120), "units"),
        )
        self.grid_canvas.bind(
            "<Shift-MouseWheel>",
            lambda e: self.grid_canvas.xview_scroll(int(-e.delta / 120), "units"),
        )
        self.grid_canvas.bind("<Configure>", lambda e: self._draw_grid())

        log_tab = ttk.Frame(notebook)
        notebook.add(log_tab, text=" 识别日志 ")
        self.log_text = tk.Text(
            log_tab, wrap="word", state="disabled",
            font=(_UI_FONT, 9), background="#FAFAFA", relief="flat",
        )
        log_scroll = ttk.Scrollbar(log_tab, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(14, 0, 14, 10))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=170)

    # ------------------------------------------------------------ 文件操作

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择课表文件",
            filetypes=[
                ("课表文件", "*.pdf *.xlsx *.xlsm *.xls"),
                ("PDF", "*.pdf"),
                ("Excel", "*.xlsx *.xlsm *.xls"),
                ("所有文件", "*.*"),
            ],
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
        self.status_var.set(f"就绪 · 已添加 {len(self.files)} 个文件")

    def remove_files(self) -> None:
        selected = list(self.file_list.curselection())
        if not selected:
            return
        for index in reversed(selected):
            del self.files[index]
        self._refresh_file_list()
        self.status_var.set(f"就绪 · 已添加 {len(self.files)} 个文件")

    def _refresh_file_list(self) -> None:
        self.file_list.delete(0, tk.END)
        for path in self.files:
            self.file_list.insert(tk.END, os.path.basename(path))

    # ------------------------------------------------------------ 识别

    def start_parse(self) -> None:
        if self.parsing:
            return
        if not self.files:
            messagebox.showinfo("提示", "请先添加 PDF 或 Excel 课表文件")
            return
        if self.timetable.courses:
            if not messagebox.askyesno(
                "重新识别", "识别结果将替换当前课程列表（包括手动修改），是否继续？"
            ):
                return
        self.parsing = True
        self.parse_button.configure(state="disabled")
        self.progress.pack(side="right")
        self.progress.start(12)
        self.status_var.set("正在识别…")
        files = list(self.files)
        threading.Thread(target=self._parse_worker, args=(files,), daemon=True).start()

    def _parse_worker(self, files: list[str]) -> None:
        def log(msg: str) -> None:
            self.queue.put(("log", msg))

        all_courses: list[Course] = []
        for path in files:
            log(f"开始处理：{os.path.basename(path)}")
            try:
                if path.lower().endswith(".pdf"):
                    found = parse_pdf(path, log)
                else:
                    found = parse_excel(path, log)
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
        self.after(120, self._poll_queue)

    def _choose_cohorts(self, courses: list[Course]) -> list[Course] | None:
        """识别到多个班次时弹窗询问要保留哪些；返回 None 表示不筛选。"""
        counts: dict[str, int] = {}
        for course in courses:
            if course.note:
                counts[course.note] = counts.get(course.note, 0) + 1
        if len(counts) < 2:
            return None

        dialog = CohortDialog(
            self, {value: counts[value] for value in sorted(counts)}
        )
        self.wait_window(dialog)
        if dialog.result is None:
            return None
        selected = set(dialog.result)
        kept = [c for c in courses if not c.note or c.note in selected]
        self._log(
            f"按班次筛选：保留 {', '.join(dialog.result) or '无'}，"
            f"课程 {len(kept)} 条"
        )
        return kept

    def _on_parse_done(self, courses: list[Course], files: list[str]) -> None:
        timetable = Timetable()
        timetable.courses = list(courses)
        removed = timetable.dedupe()
        timetable.sources = list(files)
        self.timetable = timetable
        self.parsing = False
        self.progress.stop()
        self.progress.pack_forget()
        self.parse_button.configure(state="normal")

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
        self.status_var.set(summary)

        if not timetable.courses and parsed_any:
            self._log("班次筛选后没有剩余课程")
        elif not timetable.courses:
            messagebox.showwarning(
                "未识别到课程",
                "没有识别到课程。请查看「识别日志」了解原因。\n"
                "如果是扫描版 PDF，请确认 OCR 依赖已安装；也可以把样例文件提供给开发者调整解析规则。",
            )

    # ------------------------------------------------------------ 课程编辑

    def _refresh_courses(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, course in enumerate(self.timetable.courses):
            periods = (
                f"{course.period_start}节"
                if course.period_start == course.period_end
                else f"{course.period_start}-{course.period_end}节"
            )
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    course.name,
                    course.day_name,
                    periods,
                    course.weeks_label,
                    course.teacher,
                    course.location,
                ),
            )
        self._draw_grid()

    def _selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _on_tree_double_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.edit_selected()

    def add_course(self) -> None:
        dialog = CourseDialog(self, None, self.timetable.period_times)
        self.wait_window(dialog)
        if dialog.result:
            self.timetable.courses.append(dialog.result)
            self._refresh_courses()
            self._log(f"新增课程：{dialog.result.name}")
            self.status_var.set(f"共 {len(self.timetable.courses)} 条课程记录")

    def edit_selected(self) -> None:
        index = self._selected_index()
        if index is None or index >= len(self.timetable.courses):
            messagebox.showinfo("提示", "请先在列表中选择一门课程")
            return
        dialog = CourseDialog(
            self, self.timetable.courses[index], self.timetable.period_times
        )
        self.wait_window(dialog)
        if dialog.result:
            self.timetable.courses[index] = dialog.result
            self._refresh_courses()
            self.tree.selection_set(str(index))
            self.status_var.set(f"共 {len(self.timetable.courses)} 条课程记录")

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先在列表中选择要删除的课程")
            return
        indices = sorted((int(i) for i in selection), reverse=True)
        for index in indices:
            if 0 <= index < len(self.timetable.courses):
                self.timetable.courses.pop(index)
        self._refresh_courses()
        self._log(f"删除了 {len(indices)} 条课程")
        self.status_var.set(f"共 {len(self.timetable.courses)} 条课程记录")

    # ------------------------------------------------------------ 课表预览

    def _draw_grid(self) -> None:
        canvas = self.grid_canvas
        canvas.delete("all")
        courses = self.timetable.courses
        max_period = min(max([12] + [c.period_end for c in courses]), 20)
        head_w, head_h = 92, 36
        avail = canvas.winfo_width()
        if avail > head_w + 7 * 70:
            cell_w = (avail - head_w - 2) / 7
        else:
            cell_w = 130
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
        for h in row_heights:
            row_tops.append(row_tops[-1] + h)
        total_h = row_tops[-1]

        canvas.create_rectangle(0, 0, total_w, head_h, fill="#37474F", outline="")
        canvas.create_text(
            head_w / 2, head_h / 2, text="节次", fill="white",
            font=(_UI_FONT, 9, "bold"),
        )
        for i, name in enumerate(DAY_NAMES):
            canvas.create_text(
                head_w + cell_w * i + cell_w / 2,
                head_h / 2,
                text=name,
                fill="white",
                font=(_UI_FONT, 10, "bold"),
            )

        period_times = self.timetable.period_times
        for p in range(1, max_period + 1):
            y = row_tops[p - 1]
            h = row_heights[p - 1]
            if p % 2 == 0:
                canvas.create_rectangle(
                    0, y, total_w, y + h, fill="#FAFAFA", outline=""
                )
            canvas.create_line(0, y, total_w, y, fill="#CFD8DC")
            start, end = period_times.get(p, ("", ""))
            label = f"{p}\n{start}\n{end}" if start else str(p)
            canvas.create_text(
                head_w / 2, y + h / 2, text=label, fill="#546E7A",
                font=(_UI_FONT, 7), justify="center",
            )

        canvas.create_line(0, total_h, total_w, total_h, fill="#CFD8DC")
        canvas.create_line(head_w, 0, head_w, total_h, fill="#CFD8DC")
        for i in range(1, 8):
            x = head_w + cell_w * i
            canvas.create_line(x, head_h, x, total_h, fill="#CFD8DC")

        for (day, p_start, p_end), items in groups.items():
            x = head_w + (day - 1) * cell_w
            y = row_tops[p_start - 1]
            height = row_tops[min(p_end, max_period)] - y
            inner_w = max(10, cell_w - 10)
            if len(items) == 1:
                index, course = items[0]
                color = _GRID_COLORS[index % len(_GRID_COLORS)]
                canvas.create_rectangle(
                    x + 2, y + 2, x + cell_w - 2, y + height - 2,
                    fill=color, outline="#B0BEC5",
                )
                canvas.create_text(
                    x + 5, y + 4, text=course.name, width=inner_w,
                    anchor="nw", font=(_UI_FONT, 7, "bold"), fill="#263238",
                )
                meta_parts = []
                if course.teacher:
                    meta_parts.append(course.teacher)
                if course.location:
                    meta_parts.append(course.location)
                if course.weeks:
                    meta_parts.append(course.weeks_label)
                if meta_parts:
                    meta = _fit_text(
                        canvas, " ".join(meta_parts), 6, "normal", inner_w
                    )
                    canvas.create_text(
                        x + 5, y + 24, text=meta, anchor="nw",
                        font=(_UI_FONT, 6), fill="#546E7A",
                    )
                continue

            slot_h = (height - 4) / len(items)
            for slot, (index, course) in enumerate(items):
                sy = y + 2 + slot * slot_h
                color = _GRID_COLORS[index % len(_GRID_COLORS)]
                canvas.create_rectangle(
                    x + 2, sy, x + cell_w - 2,
                    min(y + height - 2, sy + slot_h - 1),
                    fill=color, outline="#B0BEC5",
                )
                name = _fit_text(canvas, course.name, 6, "bold", inner_w)
                canvas.create_text(
                    x + 5, sy + 1, text=name, anchor="nw",
                    font=(_UI_FONT, 6, "bold"), fill="#263238",
                )
                if slot_h >= 23:
                    meta_parts = []
                    if course.teacher:
                        meta_parts.append(course.teacher)
                    if course.location:
                        meta_parts.append(course.location)
                    if course.weeks:
                        meta_parts.append(course.weeks_label)
                    meta = _fit_text(
                        canvas, " ".join(meta_parts), 5, "normal", inner_w
                    )
                    canvas.create_text(
                        x + 5, sy + 13, text=meta, anchor="nw",
                        font=(_UI_FONT, 5), fill="#546E7A",
                    )

        canvas.configure(scrollregion=(0, 0, total_w, total_h))

    # ------------------------------------------------------------ 导出

    def _ensure_courses(self) -> bool:
        if not self.timetable.courses:
            messagebox.showinfo("提示", "暂时没有可导出的课程，请先识别或新增课程")
            return False
        return True

    def _ask_save(self, default_name: str, filetypes) -> str | None:
        path = filedialog.asksaveasfilename(
            title="导出课表",
            initialfile=default_name,
            filetypes=filetypes,
        )
        return path or None

    def _after_export(self, path: str) -> None:
        self._log(f"已导出：{path}")
        self.status_var.set(f"已导出：{os.path.basename(path)}")
        if messagebox.askyesno(
            "导出成功", f"已保存到：\n{path}\n\n是否打开所在文件夹？"
        ):
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                pass

    def export_xlsx(self) -> None:
        if not self._ensure_courses():
            return
        path = self._ask_save(
            "课表.xlsx", [("Excel 工作簿", "*.xlsx")]
        )
        if not path:
            return
        try:
            export_xlsx(self.timetable.courses, path, self.timetable.period_times)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self._after_export(path)

    def export_json_file(self) -> None:
        if not self._ensure_courses():
            return
        path = self._ask_save("课表.json", [("JSON 文件", "*.json")])
        if not path:
            return
        try:
            export_json(self.timetable.courses, path, self.timetable.sources)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self._after_export(path)

    def export_ics_file(self) -> None:
        if not self._ensure_courses():
            return
        try:
            first_monday = date.fromisoformat(self.week1_var.get().strip())
        except ValueError:
            messagebox.showwarning(
                "日期格式错误", "「第 1 周周一」请填写 YYYY-MM-DD，例如 2026-09-07"
            )
            return
        path = self._ask_save("课程表.ics", [("iCalendar 日历", "*.ics")])
        if not path:
            return
        try:
            aligned, count = export_ics(
                self.timetable.courses,
                path,
                first_monday,
                self.timetable.period_times,
            )
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        if aligned != first_monday:
            self._log(
                f"日期已对齐到该周周一：{aligned.isoformat()}（原输入 {first_monday.isoformat()}）"
            )
        missing_weeks = sum(1 for c in self.timetable.courses if not c.weeks)
        if missing_weeks:
            self._log(
                f"{missing_weeks} 条课程未识别到周次，已按 1-16 周写入日历"
            )
        self._log(f"日历导出完成，共 {count} 个事件")
        self._after_export(path)

    # ------------------------------------------------------------ 日志

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
