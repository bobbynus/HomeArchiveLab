"""Settings & about."""
from __future__ import annotations

import os
import shutil

from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QSpinBox

from ... import APP_NAME, __version__
from ...core import upscale
from ...core.media import HEIF_SUPPORTED, find_tool, human_size
from ...core.settings import Settings
from .. import icons, theme
from ..widgets import Card, Page, button, label


class SettingsPage(Page):
    def __init__(self, state):
        super().__init__("Настройки", "Параметры программы и состояние компонентов", state)
        row = QHBoxLayout()
        gen = Card("Общие")
        f = QFormLayout()
        self.name = QLineEdit(Settings.get("device_name"))
        self.name.editingFinished.connect(lambda: Settings.set("device_name", self.name.text().strip()))
        self.quality = QSpinBox()
        self.quality.setRange(40, 100)
        self.quality.setValue(int(Settings.get("jpeg_quality")))
        self.quality.valueChanged.connect(lambda v: Settings.set("jpeg_quality", v))
        f.addRow("Имя устройства в сети", self.name)
        f.addRow("Качество JPEG по умолчанию", self.quality)
        gen.lay.addLayout(f)
        cache = QHBoxLayout()
        self.cache_lbl = label("", "Muted")
        b_clear = button("Очистить кэш миниатюр", "trash")
        b_clear.clicked.connect(self._clear_cache)
        cache.addWidget(self.cache_lbl, 1)
        cache.addWidget(b_clear)
        gen.lay.addLayout(cache)
        b_dir = button("Открыть папку программы", "folder")
        b_dir.clicked.connect(lambda: os.startfile(Settings.app_dir()))  # noqa: S606
        gen.lay.addWidget(b_dir)
        row.addWidget(gen, 1)

        comp = Card("Компоненты")
        self.comp = QFormLayout()
        comp.lay.addLayout(self.comp)
        comp.lay.addWidget(label("ffmpeg нужен для видео. Если его нет, установите (winget install ffmpeg) "
                                 f"или положите ffmpeg.exe и ffprobe.exe в {Settings.tools_dir()}", "Muted", wrap=True))
        row.addWidget(comp, 1)
        self.body.addLayout(row)

        about = Card()
        ab = QHBoxLayout()
        logo = label("")
        from .. import icons as ic

        logo.setPixmap(ic.app_icon().pixmap(64, 64))
        ab.addWidget(logo)
        txt = label(f"<b style='font-size:14pt'>{APP_NAME}</b><br>Версия {__version__}<br>"
                    f"<span style='color:{theme.MUTED}'>Сортировка, дубликаты, кроп, пресеты соцсетей, "
                    "пакетная обработка, GPU-апскейл, метаданные и обмен по локальной сети.</span>", wrap=True)
        ab.addWidget(txt, 1)
        about.lay.addLayout(ab)
        self.body.addWidget(about)
        self.body.addStretch()

    def on_show(self):
        while self.comp.rowCount():
            self.comp.removeRow(0)

        def status(ok: bool, text: str):
            lb = label(("✓ " if ok else "✗ ") + text)
            lb.setStyleSheet(f"color:{theme.OK if ok else theme.WARN}")
            return lb

        ff = find_tool("ffmpeg")
        fp = find_tool("ffprobe")
        self.comp.addRow("ffmpeg", status(bool(ff), ff or "не найден"))
        self.comp.addRow("ffprobe", status(bool(fp), fp or "не найден"))
        ex = upscale.engine_exe()
        self.comp.addRow("Real-ESRGAN", status(bool(ex), str(ex) if ex else "не установлен (вкладка «Апскейл»)"))
        self.comp.addRow("HEIC/HEIF", status(HEIF_SUPPORTED, "поддерживается" if HEIF_SUPPORTED else "нет"))
        d = Settings.app_dir() / "thumbs"
        size = sum(f.stat().st_size for f in d.glob("*.jpg")) if d.exists() else 0
        self.cache_lbl.setText(f"Кэш миниатюр: {human_size(size)}")

    def _clear_cache(self):
        d = Settings.app_dir() / "thumbs"
        shutil.rmtree(d, ignore_errors=True)
        from ..widgets import ThumbLoader

        ThumbLoader.get().mem.clear()
        self.on_show()
        QMessageBox.information(self, "Кэш", "Кэш миниатюр очищен.")
