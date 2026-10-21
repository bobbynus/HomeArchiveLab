"""Upscale page: Real-ESRGAN on the GPU with a before/after compare view."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QMessageBox, QScrollArea, QVBoxLayout, QWidget)

from ...core import upscale
from ...core.media import kind_of
from ...core.settings import Settings
from .. import icons, theme
from ..widgets import (Card, CompareView, FileList, FolderPicker, Page, ProgressRow, button, file_list_toolbar,
                       label, run_task)


class UpscalePage(Page):
    def __init__(self, state):
        super().__init__("Апскейл", "Увеличение разрешения нейросетью Real-ESRGAN на видеокарте", state)
        main = QHBoxLayout()
        left = QVBoxLayout()
        self.files = FileList()
        left.addLayout(file_list_toolbar(self.files, self))
        left.addWidget(self.files, 1)
        self.compare = CompareView()
        left.addWidget(self.compare, 2)
        main.addLayout(left, 3)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 6, 0)
        eng = Card("Движок")
        self.status_icon = label("")
        self.status = label("", wrap=True)
        sr = QHBoxLayout()
        sr.addWidget(self.status_icon)
        sr.addWidget(self.status, 1)
        eng.lay.addLayout(sr)
        self.b_install = button("Установить Real-ESRGAN (~45 МБ)", "download", "Primary")
        self.b_install.clicked.connect(self.install)
        eng.lay.addWidget(self.b_install)
        eng.lay.addWidget(label("Работает через Vulkan на видеокартах NVIDIA, AMD и Intel. "
                                "Без движка используется быстрый CPU-режим (Lanczos + резкость).", "Muted", wrap=True))
        pl.addWidget(eng)

        st = Card("Параметры")
        f = QFormLayout()
        self.gpu = QComboBox()
        for i, name in enumerate(upscale.list_gpus()):
            self.gpu.addItem(f"{i}: {name}", i)
        self.gpu.setCurrentIndex(min(int(Settings.get("upscale_gpu")), self.gpu.count() - 1))
        self.model = QComboBox()
        for key, (title, _scales) in upscale.MODELS.items():
            self.model.addItem(title, key)
        self.model.setCurrentIndex(max(0, self.model.findData(Settings.get("upscale_model"))))
        self.scale = QComboBox()
        for s in (2, 3, 4):
            self.scale.addItem(f"×{s}", s)
        self.scale.setCurrentIndex(2)
        self.fmt = QComboBox()
        for k, v in (("png", "PNG (без потерь)"), ("jpg", "JPEG 95%"), ("webp", "WebP 95%")):
            self.fmt.addItem(v, k)
        self.out_dir = FolderPicker("Рядом с исходниками")
        f.addRow("Видеокарта", self.gpu)
        f.addRow("Модель", self.model)
        f.addRow("Увеличение", self.scale)
        f.addRow("Формат фото", self.fmt)
        f.addRow("Папка", self.out_dir)
        st.lay.addLayout(f)
        st.lay.addWidget(label("Видео обрабатывается покадрово — это может занять много времени и места на диске.",
                               "Muted", wrap=True))
        pl.addWidget(st)
        self.b_run = button("Увеличить", "upscale", "Primary")
        pl.addWidget(self.b_run)
        self.progress = ProgressRow()
        pl.addWidget(self.progress)
        self.log = label("", "Muted", wrap=True)
        pl.addWidget(self.log)
        pl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(400)
        main.addWidget(scroll)
        self.body.addLayout(main, 1)

        self.task = None
        self.b_run.clicked.connect(self.run)
        self.progress.cancel_clicked.connect(lambda: self.task and self.task.cancel())
        self.files.currentItemChanged.connect(self._show_before)
        state.send_to.connect(lambda k, p: self.files.add_paths(p) if k == "upscale" else None)
        self.refresh_status()

    def refresh_status(self):
        ok = upscale.is_available()
        self.status_icon.setPixmap(icons.pixmap("gpu", 28, theme.OK if ok else theme.WARN))
        self.status.setText("Real-ESRGAN установлен — используется GPU" if ok
                            else "Real-ESRGAN не установлен — будет CPU-режим")
        self.b_install.setVisible(not ok)

    def install(self):
        if QMessageBox.question(self, "Установка", "Скачать портативный Real-ESRGAN с GitHub (xinntao/Real-ESRGAN) "
                                "в папку программы?") != QMessageBox.Yes:
            return
        self.b_install.setEnabled(False)
        self.progress.start("Загрузка Real-ESRGAN…")

        def done(_):
            self.b_install.setEnabled(True)
            self.progress.finish("Установлено")
            self.refresh_status()

        def err(m):
            self.b_install.setEnabled(True)
            self.progress.finish("Ошибка загрузки")
            QMessageBox.critical(self, "Ошибка", m)

        self.task = run_task(lambda report, c: upscale.download_engine(lambda f: report(f, f"Загрузка… {int(f * 100)}%")),
                             done, self.progress.update, err)

    def _show_before(self, cur, _prev):
        if not cur:
            return
        p = Path(cur.data(Qt.UserRole))
        if kind_of(p) == "image":
            self.compare.set_images(QPixmap(str(p)), None)

    def run(self):
        files = self.files.paths()
        if not files:
            return QMessageBox.information(self, "Апскейл", "Добавьте файлы.")
        scale, model, gpu, fmt = self.scale.currentData(), self.model.currentData(), self.gpu.currentData(), self.fmt.currentData()
        Settings.set("upscale_model", model)
        Settings.set("upscale_gpu", gpu)
        out_dir = Path(self.out_dir.value()) if self.out_dir.value() else None
        if any(kind_of(f) == "video" for f in files) and not upscale.is_available():
            return QMessageBox.warning(self, "Апскейл", "Для видео нужно установить Real-ESRGAN.")
        self.b_run.setEnabled(False)
        self.progress.start("Подготовка…")
        n = len(files)

        def work(report, cancelled):
            results, errors = [], []
            for i, src in enumerate(files):
                if cancelled():
                    break
                folder = out_dir or src.parent
                ext = ".mp4" if kind_of(src) == "video" else "." + fmt
                dst = folder / f"{src.stem}_x{scale}{ext}"
                k = 1
                while dst.exists():
                    dst = folder / f"{src.stem}_x{scale} ({k}){ext}"
                    k += 1
                report(i / n, f"{i + 1}/{n}  {src.name}")
                try:
                    upscale.upscale(src, dst, scale, model, gpu,
                                    lambda f, t="", i=i: report((i + f) / n, f"{i + 1}/{n}  {t}"), cancelled)
                    results.append((src, dst))
                except Exception as e:
                    errors.append(f"{src.name}: {e}")
            return results, errors

        def done(res):
            results, errors = res
            self.b_run.setEnabled(True)
            self.progress.finish(f"Готово: {len(results)}" + (f", ошибок: {len(errors)}" if errors else ""))
            self.log.setText("\n".join(errors[:10]))
            imgs = [(s, d) for s, d in results if kind_of(d) == "image"]
            if imgs:
                s, d = imgs[-1]
                self.compare.set_images(QPixmap(str(s)), QPixmap(str(d)))
            self.state.toast.emit(f"Апскейл завершён: {len(results)} файлов")

        def err(m):
            self.b_run.setEnabled(True)
            self.progress.finish("Ошибка")
            QMessageBox.critical(self, "Ошибка", m)

        self.task = run_task(work, done, self.progress.update, err)
