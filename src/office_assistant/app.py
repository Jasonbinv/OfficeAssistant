import sys

from office_assistant.qt_preload import preload_pyside6

preload_pyside6()

from PySide6.QtWidgets import QApplication

from office_assistant.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("办公文件助手")
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
