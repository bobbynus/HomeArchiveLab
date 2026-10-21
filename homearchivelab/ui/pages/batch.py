"""Batch page: apply one recipe (or several social presets at once) to many files in parallel."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ...core.media import kind_of
from ...core.presets import PRESETS
from ...core.transform import Recipe, output_path, process
from ..recipe_form import RecipeForm
from ..widgets import Card, FileList, FolderPicker, Page, ProgressRow, button, file_list_toolbar, label, run_task


def _safe(name: str) -> str:
    return "".join("_" if c in '<>:"/\\|?*' else c for c in name).strip()


class BatchPage(Page):
    def __init__(self, state):
        super().__init__("Пакетная обработка", "Одни настройки — сотни файлов. Можно сразу под несколько соцсетей", state)
        main = QHBoxLayout()
        left = QVBoxLayout()
        self.files = FileList()
        left.addLayout(file_list_toolbar(self.files, self))
        left.addWidget(self.files, 1)
        b_sel = button("Добавить выбранное в медиатеке", "library")
        b_sel.clicked.connect(lambda: self.files.add_paths(self.state.selection))
        left.addWidget(b_sel)
        main.addLayout(left, 3)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 6, 0)
        self.tabs = QTabWidget()
        single = QWidget()
        sl = QVBoxLayout(single)
        self.form = RecipeForm()
        sl.addWidget(self.form)
        sl.addStretch()
        self.tabs.addTab(single, "Один вариант")
        multi = QWidget()
        ml = QVBoxLayout(multi)
        ml.addWidget(label("Отметьте форматы — для каждого будет создана своя папка.", "Muted", wrap=True))
        self.presets = QListWidget()
        for p in PRESETS:
            it = QListWidgetItem(f"{p.group}: {p.label}")
            it.setData(Qt.UserRole, p)
            it.setCheckState(Qt.Unchecked)
            self.presets.addItem(it)
        ml.addWidget(self.presets, 1)
        self.multi_form = RecipeForm(show_preset=False)
        self.multi_form.w.setEnabled(False)
        self.multi_form.h.setEnabled(False)
        self.multi_form.long_edge.setEnabled(False)
        ml.addWidget(self.multi_form)
        self.tabs.addTab(multi, "Несколько соцсетей")
        card = Card("Настройки")
        card.lay.addWidget(self.tabs)
        pl.addWidget(card)

        out = Card("Куда сохранять")
        of = QFormLayout()
        self.out_dir = FolderPicker("Рядом с исходниками (по умолчанию)")
        self.suffix = QLineEdit("_out")
        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        self.workers.setValue(4)
        self.keep_tree = QCheckBox("Сохранять структуру подпапок")
        of.addRow("Папка", self.out_dir)
        of.addRow("Суффикс имени", self.suffix)
        of.addRow("Потоков", self.workers)
        of.addRow("", self.keep_tree)
        out.lay.addLayout(of)
        pl.addWidget(out)
        self.b_run = button("Запустить обработку", "play", "Primary")
        pl.addWidget(self.b_run)
        self.progress = ProgressRow()
        pl.addWidget(self.progress)
        self.log = label("", "Muted", wrap=True)
        pl.addWidget(self.log)
        pl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(430)
        main.addWidget(scroll)
        self.body.addLayout(main, 1)

        self.task = None
        self.b_run.clicked.connect(self.run)
        self.progress.cancel_clicked.connect(lambda: self.task and self.task.cancel())
        state.send_to.connect(self._receive)

    def _receive(self, key, items):
        if key == "batch":
            self.files.add_paths(items)
        elif key == "batch_recipe" and items:
            self._load_recipe(items[0])

    def _load_recipe(self, r: Recipe):
        f = self.form
        f.group.setCurrentIndex(0)
        f.w.setValue(r.width)
        f.h.setValue(r.height)
        f.long_edge.setValue(r.long_edge)
        f.mode.setCurrentIndex(max(0, f.mode.findData(r.mode)))
        f.shape.setCurrentIndex(max(0, f.shape.findData(r.shape)))
        f.fmt.setCurrentIndex(max(0, f.fmt.findData(r.fmt)))
        f.quality.setValue(r.quality)
        f.strip.setChecked(r.strip_meta)
        self._extra = {"rotate": r.rotate, "flip_h": r.flip_h, "flip_v": r.flip_v}
        self.tabs.setCurrentIndex(0)

    def _jobs(self) -> list[tuple[Recipe, str]]:
        """List of (recipe, subfolder) variants."""
        if self.tabs.currentIndex() == 0:
            r = self.form.recipe()
            for k, v in getattr(self, "_extra", {}).items():
                setattr(r, k, v)
            return [(r, "")]
        base = self.multi_form.recipe()
        jobs = []
        for i in range(self.presets.count()):
            it = self.presets.item(i)
            if it.checkState() == Qt.Checked:
                p = it.data(Qt.UserRole)
                r = copy.deepcopy(base)
                r.width, r.height, r.long_edge = p.width, p.height, 0
                jobs.append((r, _safe(f"{p.group} - {p.name} {p.width}x{p.height}")))
        return jobs

    def run(self):
        files = self.files.paths()
        if not files:
            return QMessageBox.information(self, "Пакетная обработка", "Добавьте файлы — кнопкой или перетаскиванием.")
        jobs = self._jobs()
        if not jobs:
            return QMessageBox.information(self, "Пакетная обработка", "Отметьте хотя бы один формат.")
        out_root = Path(self.out_dir.value()) if self.out_dir.value() else None
        if out_root is None and len(jobs) > 1:
            out_root = files[0].parent / "Home Archive Lab export"
        suffix, workers, keep_tree = self.suffix.text(), self.workers.value(), self.keep_tree.isChecked()
        common = files[0].parent
        if keep_tree:
            import os

            try:
                common = Path(os.path.commonpath([str(f.parent) for f in files]))
            except ValueError:  # files on different drives
                keep_tree = False
        tasks = []
        for src in files:
            for r, sub in jobs:
                folder = out_root
                if folder is not None:
                    if sub:
                        folder = folder / sub
                    if keep_tree:
                        folder = folder / src.parent.relative_to(common)
                tasks.append((src, r, folder))
        total = len(tasks)
        self.b_run.setEnabled(False)
        self.progress.start(f"0 / {total}")
        self.log.setText("")

        def one(src, r, folder):
            dst = output_path(src, folder, suffix, r)
            return process(src, dst, r)

        def work(report, cancelled):
            done, errors = 0, []
            # Videos are encoded one at a time (ffmpeg is already multi-threaded).
            images = [t for t in tasks if kind_of(t[0]) != "video"]
            videos = [t for t in tasks if kind_of(t[0]) == "video"]
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(one, *t): t for t in images}
                for fut in as_completed(futures):
                    if cancelled():
                        ex.shutdown(cancel_futures=True)
                        break
                    done += 1
                    try:
                        fut.result()
                    except Exception as e:
                        errors.append(f"{futures[fut][0].name}: {e}")
                    report(done / total, f"{done} / {total}  {futures[fut][0].name}")
            for src, r, folder in videos:
                if cancelled():
                    break
                try:
                    dst = output_path(src, folder, suffix, r)
                    from ...core.transform import process_video

                    process_video(src, dst, r, lambda f, d=done: report((d + f) / total,
                                                                        f"{d} / {total}  {src.name} {int(f * 100)}%"))
                except Exception as e:
                    errors.append(f"{src.name}: {e}")
                done += 1
                report(done / total, f"{done} / {total}")
            return done, errors

        def finished(res):
            done, errors = res
            self.b_run.setEnabled(True)
            self.progress.finish(f"Готово: {done - len(errors)} из {total}" + (f", ошибок: {len(errors)}" if errors else ""))
            where = str(out_root) if out_root else "рядом с исходниками"
            self.log.setText(f"Результат: {where}" + ("\n\nОшибки:\n" + "\n".join(errors[:15]) if errors else ""))
            self.state.toast.emit(f"Пакетная обработка завершена: {done - len(errors)} файлов")

        def failed(msg):
            self.b_run.setEnabled(True)
            self.progress.finish("Ошибка")
            QMessageBox.critical(self, "Ошибка", msg)

        self.task = run_task(work, finished, self.progress.update, failed)
