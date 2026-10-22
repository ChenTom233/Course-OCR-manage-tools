"""课表识别助手入口。"""
import ctypes
import sys


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main() -> int:
    _enable_dpi_awareness()
    from app.gui import TimetableApp

    app = TimetableApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
