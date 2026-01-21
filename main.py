# Требуемые пакеты: PySide6, requests, lxml, selenium.
from PySide6.QtWidgets import QApplication

from gui_mainwindow import MainWindow


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
