"""课表识别助手入口。"""
import sys


def main() -> int:
    from app.crashlog import install, install_qt_handler

    install()

    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    install_qt_handler()
    app.setApplicationName("课表识别助手")
    app.setFont(QFont("Microsoft YaHei UI", 10))

    from app.gui import TimetableApp

    window = TimetableApp()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
