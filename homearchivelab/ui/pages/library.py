"""Library: browse a folder as a thumbnail grid with a file info panel."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QRectF, QSize, QSortFilterProxyModel, Qt, QTimer)
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListView, QMenu, QMessageBox, QPushButton, QSlider,
                               QSplitter, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...core.dedupe import remove_files
from ...core.media import get_info, human_size, iter_media, kind_of
from .. import icons, theme
from ..widgets import Page, ThumbLoader, button, label, placeholder, run_task


class MediaModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.items: list[tuple[Path, str, float, int]] = []  # path, kind, mtime, size
        self.icon_size = 160
        self._ph: dict[str, QPixmap] = {}
        self._row: dict[str, int] = {}
        ThumbLoader.get().ready.connect(self._thumb_ready)

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self._row = {str(p): i for i, (p, *_rest) in enumerate(items)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        path, kind, mtime, size = self.items[index.row()]
        if role == Qt.DisplayRole:
            return path.name
        if role == Qt.DecorationRole:
            pm = ThumbLoader.get().request(path)
            if pm:
                return pm
            if kind not in self._ph:
                self._ph[kind] = placeholder(kind, 160)
            return self._ph[kind]
        if role == Qt.ToolTipRole:
            return f"{path}\n{human_size(size)}"
        if role == Qt.UserRole:
            return str(path)
        if role == Qt.UserRole + 1:
            return kind
        if role == Qt.UserRole + 2:
            return mtime
        if role == Qt.UserRole + 3:
            return size
        return None

    def _thumb_ready(self, path: str, _pm):
        row = self._row.get(path)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])


class CardDelegate(QStyledItemDelegate):
    """Rounded thumbnail card with file name and a video badge."""

    def __init__(self, view):
        super().__init__(view)
        self.size = 150

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(self.size + 12, self.size + 36)

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(option.rect).adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        bg = QColor(theme.ACCENT) if selected else QColor(theme.PANEL2 if hover else theme.PANEL)
        if selected:
            bg.setAlpha(70)
        p.setPen(QPen(QColor(theme.ACCENT), 2) if selected else Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 12, 12)
        img_r = QRectF(r.left() + 6, r.top() + 6, r.width() - 12, r.width() - 12)
        pm = index.data(Qt.DecorationRole)
        if isinstance(pm, QPixmap) and not pm.isNull():
            path = QPainterPath()
            path.addRoundedRect(img_r, 9, 9)
            p.setClipPath(path)
            # cover-fit the square
            k = max(img_r.width() / pm.width(), img_r.height() / pm.height())
            w, h = pm.width() * k, pm.height() * k
            p.drawPixmap(QRectF(img_r.center().x() - w / 2, img_r.center().y() - h / 2, w, h), pm, QRectF(pm.rect()))
            p.setClipping(False)
        if index.data(Qt.UserRole + 1) == "video":
            badge = QRectF(img_r.left() + 6, img_r.bottom() - 26, 30, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(badge, 6, 6)
            p.drawPixmap(badge.adjusted(8, 3, -8, -3).toRect(), icons.pixmap("play", 14, "#ffffff"))
        p.setPen(QColor(theme.TEXT if selected else theme.MUTED))
        text_r = QRectF(r.left() + 8, img_r.bottom() + 4, r.width() - 16, r.bottom() - img_r.bottom() - 6)
        name = option.fontMetrics.elidedText(index.data(Qt.DisplayRole), Qt.ElideMiddle, int(text_r.width()))
        p.drawText(text_r, Qt.AlignHCenter | Qt.AlignVCenter, name)
        p.restore()


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.kind = "all"
        self.text = ""

    def filterAcceptsRow(self, row, parent):  # noqa: N802
        idx = self.sourceModel().index(row, 0, parent)
        kind = idx.data(Qt.UserRole + 1)
        if self.kind == "image" and kind not in ("image", "raw"):
            return False
        if self.kind == "video" and kind != "video":
            return False
        return not self.text or self.text in idx.data(Qt.DisplayRole).lower()


class InfoPanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setMinimumWidth(360)
        self.setMaximumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setStyleSheet(f"background:{theme.PANEL};border:1px solid {theme.LINE};border-radius:12px;")
        lay.addWidget(self.preview)
        self.title = label("Выберите файл", "H2", wrap=True)
        lay.addWidget(self.title)
        self.table = QTableWidget(0, 2)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.b_edit = button("Редактор", "edit")
        self.b_meta = button("Метаданные", "meta")
        self.b_up = button("Апскейл", "upscale")
        for b in (self.b_edit, self.b_meta, self.b_up):
            row.addWidget(b)
        lay.addLayout(row)
        self.b_edit.clicked.connect(lambda: self._send("edit"))
        self.b_meta.clicked.connect(lambda: self._send("meta"))
        self.b_up.clicked.connect(lambda: self._send("upscale"))
        self._current: Path | None = None
        self._big: dict[str, QPixmap] = {}

    def _send(self, key):
        sel = self.state.selection or ([self._current] if self._current else [])
        if sel:
            self.state.send_to.emit(key, sel)

    def show_file(self, path: Path | None, count: int = 1):
        self._current = path
        if not path:
            self.title.setText("Выберите файл")
            self.preview.clear()
            self.table.setRowCount(0)
            return
        self.title.setText(path.name if count == 1 else f"{path.name}  (+{count - 1} ещё)")
        pm = ThumbLoader.get().request(path)
        if pm:
            self.preview.setPixmap(pm.scaled(self.preview.width() - 16, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.table.setRowCount(0)
        want = str(path)

        def work(report, cancelled):
            return get_info(path)

        def done(info):
            if self._current is None or str(self._current) != want:
                return
            rows = info.as_rows()
            self.table.setRowCount(len(rows))
            for i, (k, v) in enumerate(rows):
                a = QTableWidgetItem(k)
                a.setForeground(Qt.gray)
                self.table.setItem(i, 0, a)
                self.table.setItem(i, 1, QTableWidgetItem(str(v)))
            self.table.resizeRowsToContents()

        run_task(work, done)

    def refresh_preview(self, path: str, pm: QPixmap):
        if self._current and str(self._current) == path:
            self.preview.setPixmap(pm.scaled(self.preview.width() - 16, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class LibraryPage(Page):
    def __init__(self, state):
        super().__init__("Медиатека", "Все фото и видео выбранной папки", state)
        self.b_open = button("Открыть папку", "folder", "Primary")
        self.b_refresh = button("", "refresh", tip="Обновить")
        self.actions.addWidget(self.b_refresh)
        self.actions.addWidget(self.b_open)
        self.b_open.clicked.connect(self.pick_folder)
        self.b_refresh.clicked.connect(self.reload)

        bar = QHBoxLayout()
        self.path_lbl = label("", "Muted")
        seg = QHBoxLayout()
        seg.setSpacing(2)
        self.seg_group = QButtonGroup(self)
        for i, (key, text) in enumerate((("all", "Все"), ("image", "Фото"), ("video", "Видео"))):
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setProperty("key", key)
            self.seg_group.addButton(b)
            seg.addWidget(b)
        self.seg_group.buttonClicked.connect(self._filter_kind)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по имени…")
        self.search.addAction(icons.icon("search", theme.MUTED), QLineEdit.LeadingPosition)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self._filter_text)
        self.sort_btn = button("Сортировка: дата ↓")
        self.sort_btn.clicked.connect(self._sort_menu)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(90, 280)
        self.zoom.setValue(150)
        self.zoom.setFixedWidth(120)
        self.zoom.valueChanged.connect(self._zoom)
        bar.addLayout(seg)
        bar.addWidget(self.search)
        bar.addWidget(self.sort_btn)
        bar.addStretch()
        bar.addWidget(self.path_lbl)
        bar.addWidget(QLabel("  "))
        bar.addWidget(self.zoom)
        self.body.addLayout(bar)

        self.model = MediaModel()
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.UserRole + 2)
        self.view = QListView()
        self.view.setModel(self.proxy)
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setMovement(QListView.Static)
        self.view.setUniformItemSizes(True)
        self.view.setSpacing(2)
        self.view.setMouseTracking(True)
        self.delegate = CardDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setStyleSheet("QListView::item, QListView::item:hover, QListView::item:selected "
                                "{ background: transparent; padding: 0; }")
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context)
        self.view.doubleClicked.connect(lambda idx: self._open_external(Path(idx.data(Qt.UserRole))))
        self.view.selectionModel().selectionChanged.connect(self._sel_changed)
        self._zoom(150)

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addStretch()
        big = QLabel()
        big.setPixmap(icons.pixmap("image", 64, theme.ACCENT))
        big.setAlignment(Qt.AlignCenter)
        el.addWidget(big)
        t = label("Откройте папку с фото и видео", "H2")
        t.setAlignment(Qt.AlignCenter)
        el.addWidget(t)
        s = label("Или просто перетащите папку в окно программы", "Muted")
        s.setAlignment(Qt.AlignCenter)
        el.addWidget(s)
        b = button("Выбрать папку", "folder", "Primary")
        b.clicked.connect(self.pick_folder)
        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(b)
        bl.addStretch()
        el.addLayout(bl)
        el.addStretch()

        self.info = InfoPanel(state)
        ThumbLoader.get().ready.connect(self.info.refresh_preview)
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.view)
        ll.addWidget(self.empty)
        split.addWidget(left)
        split.addWidget(self.info)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        self.body.addWidget(split, 1)
        self.stats = label("", "Muted")
        self.body.addWidget(self.stats)
        self._sort_key, self._sort_desc = "date", True
        self._scan_task = None
        state.library_changed.connect(lambda _p: self.reload())
        QTimer.singleShot(0, self.reload)

    # ---- data
    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Папка медиатеки", self.state.library or "")
        if d:
            self.state.set_library(str(Path(d)))

    def reload(self):
        lib = self.state.library
        has = bool(lib and Path(lib).is_dir())
        self.view.setVisible(has)
        self.empty.setVisible(not has)
        self.path_lbl.setText(lib if has else "")
        if not has:
            self.model.set_items([])
            self.stats.setText("")
            return
        if self._scan_task:
            self._scan_task.cancel()
        ThumbLoader.get().clear_queue()
        self.stats.setText("Сканирование…")

        def work(report, cancelled):
            items = []
            for p in iter_media(lib):
                if cancelled():
                    break
                try:
                    st = p.stat()
                    items.append((p, kind_of(p), st.st_mtime, st.st_size))
                except OSError:
                    pass
                if len(items) % 500 == 0:
                    report(0, f"Найдено {len(items)}…")
            return items

        def done(items):
            self.model.set_items(items)
            self._apply_sort()
            photos = sum(1 for i in items if i[1] in ("image", "raw"))
            videos = sum(1 for i in items if i[1] == "video")
            total = sum(i[3] for i in items)
            self.stats.setText(f"{len(items)} файлов · {photos} фото · {videos} видео · {human_size(total)}")

        self._scan_task = run_task(work, done, lambda f, t: self.stats.setText(t))

    # ---- view
    def _zoom(self, v):
        self.model.icon_size = v
        self.delegate.size = v
        self.view.setGridSize(QSize(v + 12, v + 36))
        self.view.doItemsLayout()

    def _filter_kind(self, b):
        self.proxy.kind = b.property("key")
        self.proxy.invalidateFilter()

    def _filter_text(self, t):
        self.proxy.text = t.lower().strip()
        self.proxy.invalidateFilter()

    def _sort_menu(self):
        m = QMenu(self)
        opts = [("date", True, "Дата ↓ (новые сверху)"), ("date", False, "Дата ↑"),
                ("name", False, "Имя А→Я"), ("name", True, "Имя Я→А"),
                ("size", True, "Размер ↓"), ("size", False, "Размер ↑")]
        for key, desc, text in opts:
            a = m.addAction(text)
            a.triggered.connect(lambda _=False, k=key, d=desc, t=text: self._set_sort(k, d, t))
        m.exec(self.sort_btn.mapToGlobal(self.sort_btn.rect().bottomLeft()))

    def _set_sort(self, key, desc, text):
        self._sort_key, self._sort_desc = key, desc
        self.sort_btn.setText("Сортировка: " + text.split(" (")[0].lower())
        self._apply_sort()

    def _apply_sort(self):
        role = {"date": Qt.UserRole + 2, "name": Qt.DisplayRole, "size": Qt.UserRole + 3}[self._sort_key]
        self.proxy.setSortRole(role)
        self.proxy.sort(0, Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder)

    def selected(self) -> list[Path]:
        return [Path(i.data(Qt.UserRole)) for i in self.view.selectionModel().selectedIndexes()]

    def _sel_changed(self, *_):
        sel = self.selected()
        self.state.set_selection(sel)
        self.info.show_file(sel[0] if sel else None, len(sel))

    # ---- actions
    def _open_external(self, path: Path):
        os.startfile(str(path))  # noqa: S606 - user-initiated

    def _context(self, pos):
        sel = self.selected()
        if not sel:
            return
        m = QMenu(self)
        m.addAction(icons.icon("open"), "Открыть", lambda: self._open_external(sel[0]))
        m.addAction(icons.icon("folder"), "Показать в проводнике",
                    lambda: subprocess.Popen(["explorer", "/select,", str(sel[0])]))
        m.addSeparator()
        m.addAction(icons.icon("edit"), "Редактировать / кроп", lambda: self.state.send_to.emit("edit", sel))
        m.addAction(icons.icon("batch"), f"Пакетная обработка ({len(sel)})", lambda: self.state.send_to.emit("batch", sel))
        m.addAction(icons.icon("upscale"), "Апскейл", lambda: self.state.send_to.emit("upscale", sel))
        m.addAction(icons.icon("meta"), "Метаданные", lambda: self.state.send_to.emit("meta", sel))
        m.addSeparator()
        act = QAction(icons.icon("trash", theme.ERR), f"В корзину ({len(sel)})", m)
        act.triggered.connect(lambda: self._delete(sel))
        m.addAction(act)
        m.exec(self.view.viewport().mapToGlobal(pos))

    def _delete(self, paths):
        if QMessageBox.question(self, "Удаление", f"Переместить {len(paths)} файл(ов) в корзину?") != QMessageBox.Yes:
            return
        errors = remove_files(paths)
        if errors:
            QMessageBox.warning(self, "Ошибка", "\n".join(f"{p.name}: {e}" for p, e in errors[:10]))
        self.reload()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Delete and self.selected():
            self._delete(self.selected())
        else:
            super().keyPressEvent(e)
