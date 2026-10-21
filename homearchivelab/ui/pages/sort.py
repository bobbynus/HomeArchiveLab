"""Sort page: preview and execute folder organisation."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLineEdit, QMessageBox, QRadioButton, QTableWidget, QTableWidgetItem)

from ...core.media import iter_media
from ...core.settings import Settings
from ...core.sorter import SORT_PATTERNS, execute_sort, plan_sort
from .. import theme
from ..widgets import Card, FolderPicker, Page, ProgressRow, button, label, run_task

RENAME_PATTERNS = {
    "Не переименовывать": "",
    "20240715_123000": "{year}{month:02d}{day:02d}_{hour:02d}{minute:02d}{second:02d}",
    "2024-07-15 12.30.00": "{year}-{month:02d}-{day:02d} {hour:02d}.{minute:02d}.{second:02d}",
    "2024-07-15_ИмяФайла": "{year}-{month:02d}-{day:02d}_{name}",
}


class SortPage(Page):
    def __init__(self, state):
        super().__init__("Сортировка", "Разложите фото и видео по папкам по дате, типу или камере", state)
        top = QHBoxLayout()
        card = Card("Откуда и куда")
        form = QFormLayout()
        form.setSpacing(10)
        self.src = FolderPicker("Папка с неразобранными файлами", state.library)
        self.dst = FolderPicker("Папка архива (куда раскладывать)")
        self.recursive = QCheckBox("Включая подпапки")
        self.recursive.setChecked(True)
        form.addRow("Источник", self.src)
        form.addRow("Назначение", self.dst)
        form.addRow("", self.recursive)
        card.lay.addLayout(form)
        top.addWidget(card, 1)

        card2 = Card("Правила")
        form2 = QFormLayout()
        form2.setSpacing(10)
        self.pattern = QComboBox()
        for name, pat in SORT_PATTERNS.items():
            self.pattern.addItem(name, pat)
        self.pattern.addItem("Свой шаблон…", "custom")
        self.custom = QLineEdit(Settings.get("sort_pattern"))
        self.custom.setPlaceholderText("{year}/{month:02d} {month_name}")
        self.custom.setToolTip("Поля: {year} {month} {day} {month_name} {kind} {camera} {ext}")
        self.custom.setVisible(False)
        self.pattern.currentIndexChanged.connect(lambda: self.custom.setVisible(self.pattern.currentData() == "custom"))
        self.rename = QComboBox()
        for name, pat in RENAME_PATTERNS.items():
            self.rename.addItem(name, pat)
        mode = QHBoxLayout()
        self.copy = QRadioButton("Копировать")
        self.move = QRadioButton("Перемещать")
        (self.move if Settings.get("sort_mode") == "move" else self.copy).setChecked(True)
        mode.addWidget(self.copy)
        mode.addWidget(self.move)
        mode.addStretch()
        form2.addRow("Структура", self.pattern)
        form2.addRow("", self.custom)
        form2.addRow("Имена файлов", self.rename)
        form2.addRow("Режим", mode)
        card2.lay.addLayout(form2)
        top.addWidget(card2, 1)
        self.body.addLayout(top)

        row = QHBoxLayout()
        self.b_preview = button("Предпросмотр", "eye")
        self.b_run = button("Разложить", "play", "Primary")
        self.b_run.setEnabled(False)
        self.summary = label("Сначала нажмите «Предпросмотр» — ничего не будет изменено, пока вы не подтвердите.", "Muted")
        row.addWidget(self.b_preview)
        row.addWidget(self.b_run)
        row.addWidget(self.summary, 1)
        self.body.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Файл", "Куда", "Статус"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.body.addWidget(self.table, 1)
        self.progress = ProgressRow()
        self.body.addWidget(self.progress)

        self.plan = []
        self.task = None
        self.b_preview.clicked.connect(self.preview)
        self.b_run.clicked.connect(self.run)
        self.progress.cancel_clicked.connect(lambda: self.task and self.task.cancel())
        state.library_changed.connect(lambda p: self.src.value() or self.src.set_value(p))

    def _pattern(self) -> str:
        pat = self.pattern.currentData()
        if pat == "custom":
            pat = self.custom.text().strip() or SORT_PATTERNS["Год / Месяц"]
            Settings.set("sort_pattern", pat)
        return pat

    def preview(self):
        src, dst = self.src.value(), self.dst.value()
        if not src or not Path(src).is_dir():
            return QMessageBox.warning(self, "Сортировка", "Укажите существующую папку-источник.")
        if not dst:
            return QMessageBox.warning(self, "Сортировка", "Укажите папку назначения.")
        pattern, rename, rec = self._pattern(), self.rename.currentData(), self.recursive.isChecked()
        try:
            from datetime import datetime

            from ...core.media import MediaInfo
            from ...core.sorter import target_dir

            target_dir(MediaInfo(Path("x.jpg"), "image", 0, datetime.now()), pattern)
        except Exception as e:
            return QMessageBox.warning(self, "Шаблон", f"Ошибка в шаблоне: {e}")
        self.b_preview.setEnabled(False)
        self.b_run.setEnabled(False)
        self.progress.start("Чтение дат съёмки…")

        def work(report, cancelled):
            files = list(iter_media(src, rec))
            n = len(files) or 1
            return plan_sort(files, Path(dst), pattern, rename, lambda i, name: report(i / n, f"{i}/{n}  {name}"))

        self.task = run_task(work, self._show_plan, self.progress.update, self._error)

    def _show_plan(self, plan):
        self.plan = plan
        self.b_preview.setEnabled(True)
        self.progress.finish()
        self.progress.hide()
        self._fill_table()
        pending = sum(1 for i in plan if i.status == "pending")
        self.summary.setText(f"Будет обработано: {pending} из {len(plan)}. Проверьте список и нажмите «Разложить».")
        self.b_run.setEnabled(pending > 0)

    def _fill_table(self):
        dst = Path(self.dst.value())
        self.table.setRowCount(len(self.plan))
        colors = {"pending": theme.MUTED, "done": theme.OK, "skipped": theme.WARN, "error": theme.ERR}
        names = {"pending": "ожидает", "done": "готово", "skipped": "пропущен", "error": "ошибка"}
        for r, it in enumerate(self.plan):
            self.table.setItem(r, 0, QTableWidgetItem(it.src.name))
            try:
                rel = str(it.dst.relative_to(dst))
            except ValueError:
                rel = str(it.dst)
            self.table.setItem(r, 1, QTableWidgetItem(rel))
            st = QTableWidgetItem(names[it.status] + (f": {it.message}" if it.message else ""))
            st.setForeground(QColor(colors[it.status]))
            self.table.setItem(r, 2, st)

    def run(self):
        move = self.move.isChecked()
        Settings.set("sort_mode", "move" if move else "copy")
        if move and QMessageBox.question(self, "Перемещение",
                                         "Файлы будут перемещены из исходной папки. Продолжить?") != QMessageBox.Yes:
            return
        self.b_run.setEnabled(False)
        self.b_preview.setEnabled(False)
        self.progress.start("Раскладываем…")
        plan = self.plan
        n = len(plan) or 1

        def work(report, cancelled):
            return execute_sort(plan, move, lambda i, name: report(i / n, f"{i}/{n}  {name}"), cancelled)

        def done(plan):
            self.b_preview.setEnabled(True)
            self._fill_table()
            ok = sum(1 for i in plan if i.status == "done")
            err = sum(1 for i in plan if i.status == "error")
            self.progress.finish(f"Готово: {ok}, ошибок: {err}")
            self.summary.setText(f"Готово: {ok} файл(ов) {'перемещено' if move else 'скопировано'}.")
            self.state.toast.emit(f"Сортировка завершена: {ok} файлов")

        self.task = run_task(work, done, self.progress.update, self._error)

    def _error(self, msg):
        self.b_preview.setEnabled(True)
        self.progress.finish("Ошибка")
        QMessageBox.critical(self, "Ошибка", msg)
