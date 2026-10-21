"""Metadata page: view all tags, edit common fields, strip everything or GPS only."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit,
                               QMessageBox, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...core import metadata
from ...core.media import kind_of
from ..widgets import Card, FileList, Page, ProgressRow, button, file_list_toolbar, label, run_task


class MetadataPage(Page):
    def __init__(self, state):
        super().__init__("Метаданные", "Просмотр, редактирование и удаление EXIF, GPS и тегов видео", state)
        main = QHBoxLayout()
        left = QVBoxLayout()
        self.files = FileList(40)
        left.addLayout(file_list_toolbar(self.files, self))
        left.addWidget(self.files, 1)
        main.addLayout(left, 2)

        mid = QVBoxLayout()
        mid.addWidget(label("Все теги выбранного файла", "H2"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Тег", "Значение"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        mid.addWidget(self.table, 1)
        main.addLayout(mid, 3)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 6, 0)
        edit = Card("Редактировать поля", "Пустое поле удалит тег. Применяется к отмеченным файлам.")
        self.form = QFormLayout()
        self.fields: dict[str, QLineEdit] = {}
        self.enabled: dict[str, QCheckBox] = {}
        edit.lay.addLayout(self.form)
        self.b_apply = button("Записать в выбранные", "check", "Primary")
        edit.lay.addWidget(self.b_apply)
        pl.addWidget(edit)
        strip = Card("Очистка", "Перед публикацией удалите геолокацию и данные камеры.")
        self.keep_orient = QCheckBox("Сохранить ориентацию фото")
        self.keep_orient.setChecked(True)
        strip.lay.addWidget(self.keep_orient)
        self.b_gps = button("Удалить только GPS", "x")
        self.b_all = button("Удалить все метаданные", "trash", "Danger")
        strip.lay.addWidget(self.b_gps)
        strip.lay.addWidget(self.b_all)
        pl.addWidget(strip)
        self.scope = QCheckBox("Применять ко всем файлам списка (а не только выделенным)")
        pl.addWidget(self.scope)
        self.progress = ProgressRow()
        pl.addWidget(self.progress)
        pl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(400)
        main.addWidget(scroll)
        self.body.addLayout(main, 1)

        self._build_fields(video=False)
        self.files.currentItemChanged.connect(self._show)
        self.b_apply.clicked.connect(self.apply_fields)
        self.b_gps.clicked.connect(lambda: self.strip(only_gps=True))
        self.b_all.clicked.connect(lambda: self.strip(only_gps=False))
        state.send_to.connect(self._receive)

    def _receive(self, key, paths):
        if key == "meta":
            self.files.add_paths(paths)
            if self.files.count():
                self.files.setCurrentRow(self.files.count() - 1)

    def _build_fields(self, video: bool):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        spec = metadata.VIDEO_EDITABLE if video else {k: v[0] for k, v in metadata.EDITABLE.items()}
        for key, title in spec.items():
            e = QLineEdit()
            e.setPlaceholderText("—")
            self.fields[key] = e
            self.form.addRow(title, e)
        self._video_fields = video

    def _targets(self) -> list[Path]:
        return self.files.paths() if self.scope.isChecked() else (self.files.selected_paths() or self.files.paths()[:1])

    def _show(self, cur, _prev=None):
        if not cur:
            self.table.setRowCount(0)
            return
        p = Path(cur.data(Qt.UserRole))
        video = kind_of(p) == "video"
        if video != getattr(self, "_video_fields", False):
            self._build_fields(video)

        def work(report, cancelled):
            return metadata.read_all(p), metadata.read_fields(p)

        def done(res):
            tags, fields = res
            self.table.setRowCount(len(tags))
            for i, (k, v) in enumerate(sorted(tags.items())):
                self.table.setItem(i, 0, QTableWidgetItem(k))
                self.table.setItem(i, 1, QTableWidgetItem(v))
            if not tags:
                self.table.setRowCount(1)
                self.table.setItem(0, 0, QTableWidgetItem("Метаданных нет"))
            for k, e in self.fields.items():
                e.setText(fields.get(k, ""))

        run_task(work, done)

    def _run(self, fn, title):
        targets = self._targets()
        if not targets:
            return
        n = len(targets)
        self.progress.start(title)

        def work(report, cancelled):
            errors = []
            for i, p in enumerate(targets):
                if cancelled():
                    break
                try:
                    fn(p)
                except Exception as e:
                    errors.append(f"{p.name}: {e}")
                report((i + 1) / n, f"{i + 1}/{n}  {p.name}")
            return errors

        def done(errors):
            self.progress.finish(f"Готово: {n - len(errors)} из {n}")
            if errors:
                QMessageBox.warning(self, "Ошибки", "\n".join(errors[:15]))
            self._show(self.files.currentItem())
            self.state.toast.emit(title.rstrip("…") + " — готово")

        run_task(work, done, self.progress.update)

    def apply_fields(self):
        values = {k: e.text().strip() for k, e in self.fields.items()}
        video = self._video_fields

        def fn(p):
            if (kind_of(p) == "video") == video:
                metadata.write_fields(p, values)

        self._run(fn, "Запись метаданных…")

    def strip(self, only_gps: bool):
        n = len(self._targets())
        what = "GPS-координаты" if only_gps else "ВСЕ метаданные"
        if QMessageBox.question(self, "Очистка", f"Удалить {what} из {n} файл(ов)? Файлы изменяются на месте.") != QMessageBox.Yes:
            return
        keep = self.keep_orient.isChecked()
        self._run(lambda p: metadata.strip_metadata(p, keep_orientation=keep, only_gps=only_gps), "Очистка метаданных…")
