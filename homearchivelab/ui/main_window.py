"""Main window: sidebar navigation + stacked pages + toast notifications."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from . import icons, theme
from .pages.batch import BatchPage
from .pages.dupes import DupesPage
from .pages.editor import EditorPage
from .pages.library import LibraryPage
from .pages.metadata import MetadataPage
from .pages.network import NetworkPage
from .pages.settings import SettingsPage
from .pages.sort import SortPage
from .pages.upscale import UpscalePage
from .state import AppState
from .widgets import label

NAV = [
    ("library", "library", "Медиатека", LibraryPage),
    ("sort", "sort", "Сортировка", SortPage),
    ("dupes", "dupes", "Дубликаты", DupesPage),
    ("edit", "edit", "Редактор", EditorPage),
    ("batch", "batch", "Пакетная обработка", BatchPage),
    ("upscale", "upscale", "Апскейл (GPU)", UpscalePage),
    ("meta", "meta", "Метаданные", MetadataPage),
    ("network", "network", "Сеть", NetworkPage),
    ("settings", "settings", "Настройки", SettingsPage),
]


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet(f"background:{theme.PANEL2};border:1px solid {theme.ACCENT};border-radius:12px;"
                           f"padding:10px 18px;font-weight:600;")
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.setDuration(250)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)
        self.hide()

    def show_text(self, text: str):
        self.setText("✓  " + text)
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 24, p.height() - self.height() - 24)
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(3200)

    def _fade_out(self):
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()
        QTimer.singleShot(260, self.hide)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self.setAcceptDrops(True)
        self.state = AppState()

        root = QWidget()
        root.setObjectName("Root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(38, 38))
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        bt.addWidget(label("Home Archive", "Brand"))
        bt.addWidget(label("Lab · v" + __version__, "BrandSub"))
        brand.addLayout(bt)
        brand.addStretch()
        sl.addLayout(brand)
        sl.addSpacing(18)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.nav = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for i, (key, icon_name, title, cls) in enumerate(NAV):
            if key == "settings":
                sl.addStretch()
            b = QPushButton("  " + title)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setIcon(icons.icon(icon_name, theme.MUTED, theme.ACCENT))
            b.setIconSize(QSize(20, 20))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            sl.addWidget(b)
            page = cls(self.state)
            self.pages[key] = page
            self.stack.addWidget(page)
        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.toast = Toast(root)
        self.state.toast.connect(self.toast.show_text)
        self.state.send_to.connect(self._on_send)
        self.go("library")

    def go(self, key: str):
        self.nav_buttons[key].setChecked(True)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        page.on_show()

    def _on_send(self, key: str, _paths):
        target = {"edit": "edit", "batch": "batch", "upscale": "upscale", "meta": "meta"}.get(key)
        if target:
            self.go(target)

    # Drop a folder anywhere to open it as the library; files go to the current tool.
    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        current = next(k for k, p in self.pages.items() if p is self.stack.currentWidget())
        if len(paths) == 1 and paths[0].is_dir() and current in ("library", "sort", "dupes", "network", "settings"):
            self.state.set_library(str(paths[0]))
            self.state.toast.emit(f"Открыта папка {paths[0].name}")
            return
        if current in ("edit", "batch", "upscale", "meta"):
            self.state.send_to.emit(current, paths)
        else:
            self.state.send_to.emit("batch", paths)

    def closeEvent(self, e):  # noqa: N802
        self.pages["network"].shutdown()
        super().closeEvent(e)
