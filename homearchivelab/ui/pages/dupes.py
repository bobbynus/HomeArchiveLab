"""Duplicates page: find exact and visually similar files, remove extras to the Recycle Bin."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QMessageBox, QSlider, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ...core.dedupe import find_duplicates, remove_files
from ...core.media import get_info, human_size, iter_media, kind_of
from ...core.settings import Settings
from .. import theme
from ..widgets import Card, FolderPicker, Page, ProgressRow, ThumbLoader, button, label, placeholder, run_task


class DupesPage(Page):
    def __init__(self, state):
        super().__init__("Дубликаты", "Найдите одинаковые и похожие снимки и освободите место", state)
        card = Card()
        row = QHBoxLayout()
        self.folder = FolderPicker("Где искать", state.library)
        self.similar = QCheckBox("Искать похожие фото (пересжатые, уменьшенные)")
        self.similar.setChecked(True)
        self.thr = QSlider(Qt.Horizontal)
        self.thr.setRange(0, 16)
        self.thr.setValue(int(Settings.get("dedupe_threshold")))
        self.thr.setFixedWidth(140)
        self.thr_lbl = label("", "Muted")
        self.thr.valueChanged.connect(self._thr_text)
        self._thr_text(self.thr.value())
        self.b_find = button("Найти дубликаты", "search", "Primary")
        row.addWidget(self.folder, 2)
        row.addWidget(self.similar)
        row.addWidget(self.thr)
        row.addWidget(self.thr_lbl)
        row.addWidget(self.b_find)
        card.lay.addLayout(row)
        self.body.addWidget(card)

        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Файл", "Размер", "Разрешение", "Папка"])
        self.tree.setIconSize(QSize(72, 72))
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 110)
        self.tree.itemChanged.connect(self._update_summary)
        self.tree.currentItemChanged.connect(self._preview)
        split.addWidget(self.tree)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        self.prev = QLabel()
        self.prev.setAlignment(Qt.AlignCenter)
        self.prev.setMinimumSize(300, 300)
        self.prev.setStyleSheet(f"background:{theme.PANEL};border:1px solid {theme.LINE};border-radius:12px;")
        sl.addWidget(self.prev, 1)
        self.prev_info = label("", "Muted", wrap=True)
        sl.addWidget(self.prev_info)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.body.addWidget(split, 1)

        row2 = QHBoxLayout()
        self.summary = label("", "Muted")
        self.b_auto = button("Отметить всё, кроме лучших", "check")
        self.b_none = button("Снять отметки")
        self.b_delete = button("Удалить отмеченные в корзину", "trash", "Danger")
        for b in (self.b_auto, self.b_none, self.b_delete):
            b.setEnabled(False)
        row2.addWidget(self.summary, 1)
        row2.addWidget(self.b_auto)
        row2.addWidget(self.b_none)
        row2.addWidget(self.b_delete)
        self.body.addLayout(row2)
        self.progress = ProgressRow()
        self.body.addWidget(self.progress)

        self.groups = []
        self.task = None
        self._items: dict[str, list[QTreeWidgetItem]] = {}
        self.b_find.clicked.connect(self.find)
        self.b_auto.clicked.connect(lambda: self._mark(auto=True))
        self.b_none.clicked.connect(lambda: self._mark(auto=False))
        self.b_delete.clicked.connect(self.delete)
        self.progress.cancel_clicked.connect(lambda: self.task and self.task.cancel())
        ThumbLoader.get().ready.connect(self._thumb)
        state.library_changed.connect(lambda p: self.folder.set_value(p))

    def _thr_text(self, v):
        word = "строго" if v <= 4 else "обычно" if v <= 10 else "мягко"
        self.thr_lbl.setText(f"Похожесть: {word} ({v})")

    def find(self):
        folder = self.folder.value()
        if not folder or not Path(folder).is_dir():
            return QMessageBox.warning(self, "Дубликаты", "Укажите папку.")
        Settings.set("dedupe_threshold", self.thr.value())
        similar, thr = self.similar.isChecked(), self.thr.value()
        self.b_find.setEnabled(False)
        self.tree.clear()
        self.progress.start("Сканирование…")

        def work(report, cancelled):
            files = list(iter_media(folder))
            report(0, f"Файлов: {len(files)}. Сравниваю…")
            return find_duplicates(files, similar, thr,
                                   lambda i, n, name: report(i / max(n, 1), f"{i}/{n}  {name}"), cancelled)

        self.task = run_task(work, self._show, self.progress.update, self._error)

    def _show(self, groups):
        self.groups = groups
        self.b_find.setEnabled(True)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items.clear()
        for gi, g in enumerate(groups):
            title = "Точные копии" if g.reason == "exact" else "Похожие фото"
            top = QTreeWidgetItem([f"{title} · {len(g.files)} шт.", "", "", ""])
            top.setForeground(0, QColor(theme.ACCENT if g.reason == "exact" else theme.ACCENT2))
            top.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(top)
            for p in g.files:
                it = QTreeWidgetItem([p.name, human_size(g.sizes.get(p, 0)),
                                      "", str(p.parent)])
                it.setData(0, Qt.UserRole, str(p))
                it.setCheckState(0, Qt.Unchecked if p == g.keep else Qt.Checked)
                if p == g.keep:
                    it.setText(0, f"{p.name}   ★ оставить")
                pm = ThumbLoader.get().request(p)
                it.setIcon(0, pm if pm else placeholder(kind_of(p), 72))
                px = g.pixels.get(p)
                if px:
                    it.setText(2, f"{px / 1e6:.1f} MP")
                top.addChild(it)
                self._items.setdefault(str(p), []).append(it)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        for b in (self.b_auto, self.b_none, self.b_delete):
            b.setEnabled(bool(groups))
        self.progress.finish(f"Найдено групп: {len(groups)}")
        if not groups:
            self.summary.setText("Дубликатов не найдено 🎉")
        self._update_summary()

    def _thumb(self, path, pm):
        for it in self._items.get(path, []):
            it.setIcon(0, pm)

    def _checked(self) -> list[Path]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch.checkState(0) == Qt.Checked:
                    out.append(Path(ch.data(0, Qt.UserRole)))
        return list(dict.fromkeys(out))

    def _update_summary(self, *_):
        if not self.groups:
            return
        checked = self._checked()
        size = 0
        for p in checked:
            try:
                size += p.stat().st_size
            except OSError:
                pass
        self.summary.setText(f"Групп: {len(self.groups)} · отмечено к удалению: {len(checked)} ({human_size(size)})")

    def _mark(self, auto: bool):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            keep = str(self.groups[i].keep)
            for j in range(top.childCount()):
                ch = top.child(j)
                ch.setCheckState(0, Qt.Checked if auto and ch.data(0, Qt.UserRole) != keep else Qt.Unchecked)
        self.tree.blockSignals(False)
        self._update_summary()

    def _preview(self, cur, _prev):
        if not cur or not cur.data(0, Qt.UserRole):
            return
        p = Path(cur.data(0, Qt.UserRole))
        pm = ThumbLoader.get().request(p)
        if pm:
            self.prev.setPixmap(pm.scaled(self.prev.size() * 0.95, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        try:
            info = get_info(p)
            self.prev_info.setText(f"{p}\n{info.resolution} · {human_size(info.size)} · "
                                   f"{info.best_date.strftime('%d.%m.%Y %H:%M')}")
        except OSError:
            pass

    def delete(self):
        checked = self._checked()
        if not checked:
            return
        # Never allow deleting every file of a group.
        for i, g in enumerate(self.groups):
            if all(p in checked for p in g.files):
                return QMessageBox.warning(self, "Дубликаты",
                                           f"В группе {i + 1} отмечены все файлы. Оставьте хотя бы один.")
        if QMessageBox.question(self, "Удаление", f"Переместить {len(checked)} файл(ов) в корзину Windows?\n"
                                "Их можно будет восстановить из корзины.") != QMessageBox.Yes:
            return
        errors = remove_files(checked)
        if errors:
            QMessageBox.warning(self, "Ошибки", "\n".join(f"{p.name}: {e}" for p, e in errors[:10]))
        removed = set(checked) - {p for p, _ in errors}
        self.groups = [g for g in self.groups if len([p for p in g.files if p not in removed]) > 1]
        for g in self.groups:
            g.files = [p for p in g.files if p not in removed]
            if g.keep not in g.files:
                g.keep = g.files[0]
        self._show(self.groups)
        self.state.toast.emit(f"В корзину перемещено: {len(removed)}")

    def _error(self, msg):
        self.b_find.setEnabled(True)
        self.progress.finish("Ошибка")
        QMessageBox.critical(self, "Ошибка", msg)
