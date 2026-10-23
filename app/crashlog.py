"""把未捕获异常和原生崩溃写入日志文件。"""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback

_MAX_BYTES = 1024 * 1024
_LOG_LOCK = threading.Lock()

_log_path: str | None = None
_fault_file = None
_qt_handler = None  # 必须保持引用，否则 Qt 里的回调指针会失效
_installed = False


def get_log_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "TimetableOCR", "logs", "crash.log")


def get_native_log_path() -> str:
    return os.path.join(os.path.dirname(get_log_path()), "native.log")


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _write(text: str) -> None:
    if not _log_path:
        return
    with _LOG_LOCK:
        try:
            with open(_log_path, "a", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
        except OSError:
            pass


def _report(title: str, detail: str) -> None:
    _write(f"\n[{_stamp()}] {title}\n{detail}\n")


def install() -> str | None:
    """启用崩溃日志，返回日志路径；目录不可写时返回 None。"""
    global _log_path, _fault_file, _installed
    if _installed:
        return _log_path

    path = get_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > _MAX_BYTES:
            old = path + ".old"
            if os.path.exists(old):
                os.remove(old)
            os.replace(path, old)
        # 每次启动截断，只保留本次运行的原生崩溃信息；Windows 下 Qt 会产生
        # 一条可忽略的 COM 首次异常，放这里免得混进 crash.log
        _fault_file = open(get_native_log_path(), "wb", buffering=0)
        faulthandler.enable(file=_fault_file, all_threads=True)
        _log_path = path
    except OSError:
        _log_path = None

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    _installed = True
    _write(f"===== {_stamp()} 程序启动 =====\n")
    return _log_path


def install_qt_handler() -> None:
    """记录 Qt 自身的 Critical/Fatal 消息。"""
    global _qt_handler
    try:
        from PyQt5.QtCore import QtCriticalMsg, QtFatalMsg, qInstallMessageHandler
    except ImportError:
        return

    def handler(mode, context, message):
        if mode not in (QtCriticalMsg, QtFatalMsg):
            return
        where = ""
        if context is not None and context.file:
            where = f"（{context.file}:{context.line}）"
        _report("Qt 消息", f"{message}{where}")

    _qt_handler = handler
    qInstallMessageHandler(handler)


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    _report("未捕获异常（主线程）", detail)
    if sys.stderr is not None:
        # 打包后的窗口程序没有控制台，此时只写日志
        sys.__excepthook__(exc_type, exc, tb)
    _show_dialog(detail)


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit or issubclass(args.exc_type, KeyboardInterrupt):
        return
    detail = "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    )
    name = args.thread.name if args.thread is not None else "未知线程"
    _report(f"未捕获异常（线程 {name}）", detail)


def _show_dialog(detail: str) -> None:
    """主线程崩溃时尽量让用户看到日志位置。"""
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        box = QMessageBox(
            QMessageBox.Critical,
            "程序出错",
            "程序内部出现错误，详细信息已写入日志。",
        )
        box.setInformativeText(f"日志文件：\n{_log_path or get_log_path()}")
        box.setDetailedText(detail)
        open_button = box.addButton("打开日志位置", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec_()
        if box.clickedButton() is open_button:
            folder = os.path.dirname(_log_path or get_log_path())
            try:
                os.startfile(folder)
            except OSError:
                pass
    except Exception:
        pass
