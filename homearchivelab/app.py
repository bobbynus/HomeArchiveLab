"""Application entry point."""
from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

from . import APP_ID, APP_NAME
from .core.settings import Settings


def main() -> int:
    if os.name == "nt":  # own taskbar icon instead of python.exe
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setStyle("Fusion")

    from .ui import icons, theme

    pal = QPalette()
    for role, color in ((QPalette.Window, theme.BG), (QPalette.Base, theme.BG), (QPalette.AlternateBase, theme.PANEL2),
                        (QPalette.Text, theme.TEXT), (QPalette.WindowText, theme.TEXT), (QPalette.Button, theme.PANEL2),
                        (QPalette.ButtonText, theme.TEXT), (QPalette.Highlight, theme.ACCENT),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, theme.PANEL2),
                        (QPalette.ToolTipText, theme.TEXT), (QPalette.PlaceholderText, theme.MUTED)):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    check = Settings.app_dir() / "check.svg"
    check.write_text(icons.svg("check", "#ffffff", 3), "utf-8")
    app.setStyleSheet(theme.QSS.replace("CHECK_URL", check.as_posix()))
    app.setWindowIcon(icons.app_icon())

    from .ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
