"""浅色 / 深色主题。

使用 Fusion 风格 + 全局样式表实现，浅色和深色各自一套配色，
主题切换后所有控件会随之刷新。WeekGrid 等自绘控件通过
`grid_colors()` / `conflict_color()` 取当前主题颜色。
"""
from __future__ import annotations

import os
import tempfile

LIGHT = "light"
DARK = "dark"

_current = LIGHT

_LIGHT_QSS = """
QLabel#appTitle { color: #263238; }
QLabel[hint="true"] { color: #78909C; }
QPlainTextEdit#logText { background: #FAFAFA; border: none; }
"""

_DARK_QSS = """
QWidget {
    background-color: #1E1E1E;
    color: #E0E0E0;
}
QMainWindow, QDialog { background-color: #1E1E1E; }
QLabel { background: transparent; color: #E0E0E0; }
QLabel#appTitle { color: #FFFFFF; }
QLabel[hint="true"] { color: #90A4AE; }

QGroupBox {
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    margin-top: 12px;
    color: #E0E0E0;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
}

QPushButton {
    background-color: #3C3C3C;
    border: 1px solid #4A4A4A;
    border-radius: 3px;
    padding: 4px 12px;
    color: #E0E0E0;
}
QPushButton:hover { background-color: #4A4A4A; }
QPushButton:pressed { background-color: #333333; }
QPushButton:disabled { color: #777777; background-color: #2E2E2E; }

QLineEdit, QComboBox, QSpinBox, QTimeEdit {
    background-color: #2B2B2B;
    border: 1px solid #4A4A4A;
    border-radius: 3px;
    padding: 2px 6px;
    color: #E0E0E0;
    selection-background-color: #2979FF;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #4A4A4A;
    background-color: #3C3C3C;
    border-top-right-radius: 3px;
    border-bottom-right-radius: 3px;
}
QComboBox::down-arrow {
    image: __DOWN_ARROW__;
    width: 14px;
    height: 14px;
}
QSpinBox::up-button, QTimeEdit::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    background-color: #3C3C3C;
    border-left: 1px solid #4A4A4A;
    border-top: 1px solid #4A4A4A;
    border-top-right-radius: 3px;
}
QSpinBox::down-button, QTimeEdit::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    background-color: #3C3C3C;
    border-left: 1px solid #4A4A4A;
    border-bottom: 1px solid #4A4A4A;
    border-bottom-right-radius: 3px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QTimeEdit::up-button:hover, QTimeEdit::down-button:hover,
QComboBox::drop-down:hover { background-color: #4A4A4A; }
QSpinBox::up-arrow, QTimeEdit::up-arrow {
    image: __UP_ARROW__;
    width: 14px;
    height: 14px;
}
QSpinBox::down-arrow, QTimeEdit::down-arrow {
    image: __DOWN_ARROW__;
    width: 14px;
    height: 14px;
}
QComboBox QAbstractItemView {
    background-color: #2B2B2B;
    color: #E0E0E0;
    selection-background-color: #2979FF;
    border: 1px solid #4A4A4A;
}

QCheckBox { color: #E0E0E0; spacing: 6px; }
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #4A4A4A;
    border-radius: 3px;
    background: #2B2B2B;
}
QCheckBox::indicator:checked { background-color: #2979FF; border-color: #2979FF; }

QTableWidget, QListWidget {
    background-color: #1E1E1E;
    alternate-background-color: #242424;
    color: #E0E0E0;
    border: 1px solid #3C3C3C;
    gridline-color: #3C3C3C;
}
QHeaderView::section {
    background-color: #333333;
    color: #E0E0E0;
    border: 1px solid #4A4A4A;
    padding: 4px;
    font-weight: bold;
}
QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #2979FF;
    color: #FFFFFF;
}
QTableCornerButton::section { background-color: #333333; }

QPlainTextEdit#logText { background: #1E1E1E; border: none; color: #B0B0B0; }

QTabWidget::pane { border: 1px solid #3C3C3C; top: -1px; }
QTabBar::tab {
    background-color: #2B2B2B;
    color: #B0B0B0;
    padding: 6px 14px;
    border: 1px solid #3C3C3C;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected { background-color: #1E1E1E; color: #E0E0E0; }
QTabBar::tab:hover:!selected { background-color: #3C3C3C; }

QScrollBar:vertical {
    background: #1E1E1E;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4A4A4A;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #5A5A5A; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1E1E1E;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #4A4A4A;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QProgressBar {
    background-color: #2B2B2B;
    border: 1px solid #4A4A4A;
    border-radius: 3px;
    text-align: center;
    color: #E0E0E0;
}
QProgressBar::chunk { background-color: #2979FF; border-radius: 2px; }

QStatusBar { background-color: #1E1E1E; color: #B0B0B0; }
QMenu { background-color: #2B2B2B; color: #E0E0E0; border: 1px solid #4A4A4A; }
QMenu::item:selected { background-color: #2979FF; }
QFrame[frameShape="5"] { color: #3C3C3C; }
QSplitter::handle { background-color: #3C3C3C; }
"""


_arrow_cache: tuple[str, str] | None = None


def _ensure_arrows() -> tuple[str, str]:
    """生成深色主题的上/下箭头图标，返回路径；失败时返回 ("", "")。"""
    global _arrow_cache
    if _arrow_cache is not None:
        return _arrow_cache
    folder = os.path.join(tempfile.gettempdir(), "TimetableOCR_theme")
    up = os.path.join(folder, "arrow_up.png")
    down = os.path.join(folder, "arrow_down.png")
    try:
        os.makedirs(folder, exist_ok=True)
        if not (os.path.exists(up) and os.path.exists(down)):
            from PIL import Image, ImageDraw

            size = 20
            color = (224, 224, 224, 255)
            for path, pointing_up in ((up, True), (down, False)):
                img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                if pointing_up:
                    draw.polygon([(4, 14), (16, 14), (10, 6)], fill=color)
                else:
                    draw.polygon([(4, 6), (16, 6), (10, 14)], fill=color)
                img.save(path)
        _arrow_cache = (up, down)
    except Exception:
        _arrow_cache = ("", "")
    return _arrow_cache


def _dark_qss() -> str:
    up, down = _ensure_arrows()
    up_css = "none"
    down_css = "none"
    if up:
        up_css = 'url("%s")' % up.replace("\\", "/")
    if down:
        down_css = 'url("%s")' % down.replace("\\", "/")
    return _DARK_QSS.replace("__UP_ARROW__", up_css).replace("__DOWN_ARROW__", down_css)


def is_dark() -> bool:
    return _current == DARK


def apply_theme(app, theme: str) -> None:
    """把主题应用到整个应用；传入 LIGHT 或 DARK。"""
    global _current
    _current = DARK if theme == DARK else LIGHT
    app.setStyle("Fusion")
    app.setStyleSheet(_dark_qss() if _current == DARK else _LIGHT_QSS)


def grid_colors() -> dict[str, str]:
    """WeekGrid 自绘所需的当前主题颜色。"""
    if _current == DARK:
        return {
            "bg": "#1E1E1E",
            "header": "#263238",
            "line": "#3C3C3C",
            "alt": "#242424",
            "period": "#B0BEC5",
        }
    return {
        "bg": "#FFFFFF",
        "header": "#37474F",
        "line": "#CFD8DC",
        "alt": "#FAFAFA",
        "period": "#546E7A",
    }


def conflict_color() -> str:
    """时间冲突课程的高亮底色。"""
    return "#5C2A2A" if _current == DARK else "#FFCDD2"
