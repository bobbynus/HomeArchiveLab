"""Reusable widgets: background tasks, thumbnails, page scaffolding, crop canvas, compare view."""
from __future__ import annotations

import hashlib
import traceback
from pathlib import Path
from typing import Callable

from PIL import Image
from PySide6.QtCore import (QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal)
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..core.media import is_media, iter_media, kind_of, load_preview
from ..core.settings import Settings
from . import icons, theme


# ---------------------------------------------------------------- tasks
class _TaskSignals(QObject):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    """Run `fn(report, cancelled)` in the thread pool. `report(fraction, text)` updates the UI."""

    def __init__(self, fn: Callable, on_done=None, on_progress=None, on_error=None):
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()
        self._cancel = False
        if on_done:
            self.signals.done.connect(on_done)
        if on_progress:
            self.signals.progress.connect(on_progress)
        self.signals.failed.connect(on_error or (lambda msg: None))

    def cancel(self) -> None:
        self._cancel = True

    def cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:
        try:
            result = self.fn(lambda f, t="": self.signals.progress.emit(float(f), str(t)), self.cancelled)
            self.signals.done.emit(result)
        except Exception as e:  # pragma: no cover - surfaced in UI
            traceback.print_exc()
            self.signals.failed.emit(str(e))


_ALIVE: set[Task] = set()


def run_task(fn, on_done=None, on_progress=None, on_error=None, pool: QThreadPool | None = None) -> Task:
    t = Task(fn, on_done, on_progress, on_error)
    # Keep the task (and its signal object) alive until its queued signals reach the GUI thread,
    # otherwise Qt silently drops the done/failed callbacks.
    t.setAutoDelete(False)
    _ALIVE.add(t)
    t.signals.done.connect(lambda _r: _ALIVE.discard(t))
    t.signals.failed.connect(lambda _m: _ALIVE.discard(t))
    (pool or QThreadPool.globalInstance()).start(t)
    return t


# ---------------------------------------------------------------- thumbnails
def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    return QImage(data, img.width, img.height, QImage.Format_RGBA8888).copy()


class _ThumbSignals(QObject):
    ready = Signal(str, QImage)


class _ThumbJob(QRunnable):
    def __init__(self, path: str, size: int, signals: _ThumbSignals):
        super().__init__()
        self.path, self.size, self.signals = path, size, signals

    def run(self) -> None:
        p = Path(self.path)
        try:
            st = p.stat()
        except OSError:
            return
        key = hashlib.md5(f"{p}|{st.st_mtime}|{st.st_size}|{self.size}".encode()).hexdigest()
        cache = Settings.app_dir() / "thumbs" / f"{key}.jpg"
        qimg = QImage()
        if cache.exists():
            qimg.load(str(cache))
        if qimg.isNull():
            img = load_preview(p, self.size)
            if img is None:
                return
            cache.parent.mkdir(exist_ok=True)
            try:
                img.save(cache, "JPEG", quality=85)
            except OSError:
                pass
            qimg = pil_to_qimage(img)
        self.signals.ready.emit(self.path, qimg)


class ThumbLoader(QObject):
    """Async, disk-cached thumbnail provider shared by all pages."""

    ready = Signal(str, QPixmap)
    _instance: "ThumbLoader | None" = None

    def __init__(self):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(2, QThreadPool.globalInstance().maxThreadCount() - 1))
        self.mem: dict[str, QPixmap] = {}
        self.pending: set[str] = set()
        self._signals = _ThumbSignals()
        self._signals.ready.connect(self._on_ready)

    @classmethod
    def get(cls) -> "ThumbLoader":
        if cls._instance is None:
            cls._instance = ThumbLoader()
        return cls._instance

    def request(self, path: str | Path, size: int = 320) -> QPixmap | None:
        path = str(path)
        if path in self.mem:
            return self.mem[path]
        if path not in self.pending:
            self.pending.add(path)
            self.pool.start(_ThumbJob(path, size, self._signals))
        return None

    def clear_queue(self) -> None:
        self.pool.clear()
        self.pending.clear()

    def _on_ready(self, path: str, img: QImage) -> None:
        self.pending.discard(path)
        pm = QPixmap.fromImage(img)
        self.mem[path] = pm
        if len(self.mem) > 3000:
            self.mem.pop(next(iter(self.mem)))
        self.ready.emit(path, pm)


def placeholder(kind: str, size: int = 160) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(theme.PANEL2))
    p = QPainter(pm)
    ic = icons.pixmap("video" if kind == "video" else "image", 36, theme.MUTED)
    p.drawPixmap((size - 36) // 2, (size - 36) // 2, ic)
    p.end()
    return pm


# ---------------------------------------------------------------- scaffolding
def label(text: str, obj: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def button(text: str, icon_name: str | None = None, obj: str = "", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if icon_name:
        color = "#ffffff" if obj == "Primary" else (theme.ERR if obj == "Danger" else theme.TEXT)
        b.setIcon(icons.icon(icon_name, color))
        b.setIconSize(QSize(18, 18))
    if obj:
        b.setObjectName(obj)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 16)
        self.lay.setSpacing(10)
        if title:
            self.lay.addWidget(label(title, "H2"))
        if subtitle:
            self.lay.addWidget(label(subtitle, "Muted", wrap=True))


class Page(QWidget):
    """Page with a title row; subclasses fill `self.body`."""

    def __init__(self, title: str, subtitle: str, state=None):
        super().__init__()
        self.state = state
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(title, "PageTitle"))
        col.addWidget(label(subtitle, "PageSub"))
        head.addLayout(col)
        head.addStretch()
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        root.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        root.addLayout(self.body, 1)

    def on_show(self) -> None:
        """Called by the main window when the page becomes visible."""


class ProgressRow(QWidget):
    """Progress bar + status text + cancel button, hidden while idle."""

    cancel_clicked = Signal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.text = label("", "Muted")
        self.text.setMinimumWidth(260)
        self.text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.cancel = button("Отмена", "x")
        self.cancel.clicked.connect(self.cancel_clicked)
        lay.addWidget(self.bar, 2)
        lay.addWidget(self.text, 3)
        lay.addWidget(self.cancel)
        self.hide()

    def start(self, text: str = "") -> None:
        self.bar.setValue(0)
        self.text.setText(text)
        self.cancel.setEnabled(True)
        self.show()

    def update(self, frac: float, text: str = "") -> None:  # noqa: A003 - Qt-style name
        self.bar.setValue(int(max(0.0, min(1.0, frac)) * 1000))
        if text:
            self.text.setText(text)

    def finish(self, text: str = "") -> None:
        self.bar.setValue(1000)
        self.text.setText(text)
        self.cancel.setEnabled(False)
        QTimer.singleShot(6000, lambda: self.hide() if not self.cancel.isEnabled() else None)


class FileList(QListWidget):
    """List of files with thumbnails; accepts drag & drop of files and folders."""

    changed = Signal()

    def __init__(self, icon_size: int = 56):
        super().__init__()
        self.setAcceptDrops(True)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setUniformItemSizes(True)
        self._items: dict[str, QListWidgetItem] = {}
        ThumbLoader.get().ready.connect(self._thumb_ready)

    def paths(self) -> list[Path]:
        return [Path(self.item(i).data(Qt.UserRole)) for i in range(self.count())]

    def selected_paths(self) -> list[Path]:
        return [Path(i.data(Qt.UserRole)) for i in self.selectedItems()]

    def add_paths(self, paths) -> int:
        added = 0
        for p in paths:
            p = Path(p)
            files = list(iter_media(p)) if p.is_dir() else ([p] if is_media(p) else [])
            for f in files:
                key = str(f)
                if key in self._items:
                    continue
                it = QListWidgetItem(f.name)
                it.setData(Qt.UserRole, key)
                it.setToolTip(key)
                pm = ThumbLoader.get().request(key)
                it.setIcon(pm if pm else placeholder(kind_of(f), 64))
                self.addItem(it)
                self._items[key] = it
                added += 1
        if added:
            self.changed.emit()
        return added

    def remove_selected(self) -> None:
        for it in self.selectedItems():
            self._items.pop(it.data(Qt.UserRole), None)
            self.takeItem(self.row(it))
        self.changed.emit()

    def clear_all(self) -> None:
        self.clear()
        self._items.clear()
        self.changed.emit()

    def _thumb_ready(self, path: str, pm: QPixmap) -> None:
        it = self._items.get(path)
        if it:
            it.setIcon(pm)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):  # noqa: N802
        self.add_paths(u.toLocalFile() for u in e.mimeData().urls())


def file_list_toolbar(fl: FileList, parent: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    add_files = button("Файлы", "plus")
    add_dir = button("Папка", "folder")
    rem = button("Убрать", "x")
    clr = button("Очистить")
    count = label("", "Muted")

    def pick_files():
        files, _ = QFileDialog.getOpenFileNames(parent, "Выберите файлы", Settings.get("library") or "",
                                                "Медиа (*.jpg *.jpeg *.png *.webp *.heic *.heif *.tif *.tiff *.bmp *.gif "
                                                "*.mp4 *.mov *.m4v *.avi *.mkv *.webm *.3gp *.mts);;Все файлы (*)")
        fl.add_paths(files)

    def pick_dir():
        d = QFileDialog.getExistingDirectory(parent, "Выберите папку", Settings.get("library") or "")
        if d:
            fl.add_paths([d])

    add_files.clicked.connect(pick_files)
    add_dir.clicked.connect(pick_dir)
    rem.clicked.connect(fl.remove_selected)
    clr.clicked.connect(fl.clear_all)
    fl.changed.connect(lambda: count.setText(f"{fl.count()} файл(ов)"))
    for w in (add_files, add_dir, rem, clr):
        row.addWidget(w)
    row.addStretch()
    row.addWidget(count)
    return row


class FolderPicker(QWidget):
    changed = Signal(str)

    def __init__(self, placeholder_text: str = "Не выбрано", value: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QLineEdit

        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText(placeholder_text)
        self.edit.textChanged.connect(self.changed)
        b = button("", "folder", tip="Выбрать папку")
        b.clicked.connect(self._pick)
        lay.addWidget(self.edit, 1)
        lay.addWidget(b)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите папку", self.edit.text() or Settings.get("library") or "")
        if d:
            self.edit.setText(str(Path(d)))

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str) -> None:
        self.edit.setText(v)


# ---------------------------------------------------------------- crop canvas
class CropCanvas(QWidget):
    """Shows an image and an interactive crop rectangle (stored as fractions 0..1)."""

    changed = Signal()
    HANDLE = 9

    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.pix: QPixmap | None = None
        self.crop = QRectF(0, 0, 1, 1)
        self.aspect: float | None = None  # w/h in source pixels
        self.enabled_crop = True
        self.shape = "none"
        self._drag: str | None = None
        self._start = QPointF()
        self._start_crop = QRectF()

    def set_image(self, pix: QPixmap | None) -> None:
        self.pix = pix
        self.crop = QRectF(0, 0, 1, 1)
        self._apply_aspect()
        self.update()

    def set_aspect(self, aspect: float | None) -> None:
        self.aspect = aspect
        self._apply_aspect()
        self.update()
        self.changed.emit()

    def reset(self) -> None:
        self.crop = QRectF(0, 0, 1, 1)
        self._apply_aspect()
        self.update()
        self.changed.emit()

    def _img_rect(self) -> QRectF:
        if not self.pix:
            return QRectF()
        pw, ph = self.pix.width() / self.pix.devicePixelRatio(), self.pix.height() / self.pix.devicePixelRatio()
        k = min((self.width() - 24) / pw, (self.height() - 24) / ph)
        w, h = pw * k, ph * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _apply_aspect(self) -> None:
        if not self.pix or not self.aspect:
            return
        iw, ih = self.pix.width(), self.pix.height()
        # aspect in fraction space
        a = self.aspect * ih / iw
        c = self.crop.center()
        w = self.crop.width()
        h = w / a
        if h > self.crop.height():
            h = self.crop.height()
            w = h * a
        if w > 1:
            w, h = 1, 1 / a
        if h > 1:
            h, w = 1, a
        r = QRectF(0, 0, w, h)
        r.moveCenter(c)
        self.crop = self._clamp(r)

    @staticmethod
    def _clamp(r: QRectF) -> QRectF:
        r = QRectF(r)
        if r.left() < 0:
            r.moveLeft(0)
        if r.top() < 0:
            r.moveTop(0)
        if r.right() > 1:
            r.moveRight(1)
        if r.bottom() > 1:
            r.moveBottom(1)
        return r

    def _crop_px(self) -> QRectF:
        ir = self._img_rect()
        return QRectF(ir.x() + self.crop.x() * ir.width(), ir.y() + self.crop.y() * ir.height(),
                      self.crop.width() * ir.width(), self.crop.height() * ir.height())

    def _hit(self, pos: QPointF) -> str | None:
        r = self._crop_px()
        hs = self.HANDLE + 4
        corners = {"tl": r.topLeft(), "tr": r.topRight(), "bl": r.bottomLeft(), "br": r.bottomRight()}
        for name, pt in corners.items():
            if abs(pos.x() - pt.x()) < hs and abs(pos.y() - pt.y()) < hs:
                return name
        if not self.aspect:
            if abs(pos.x() - r.left()) < 6 and r.top() < pos.y() < r.bottom():
                return "l"
            if abs(pos.x() - r.right()) < 6 and r.top() < pos.y() < r.bottom():
                return "r"
            if abs(pos.y() - r.top()) < 6 and r.left() < pos.x() < r.right():
                return "t"
            if abs(pos.y() - r.bottom()) < 6 and r.left() < pos.x() < r.right():
                return "b"
        if r.contains(pos):
            return "move"
        return None

    def mousePressEvent(self, e):  # noqa: N802
        if not self.pix or not self.enabled_crop:
            return
        self._drag = self._hit(e.position())
        self._start = e.position()
        self._start_crop = QRectF(self.crop)

    def mouseMoveEvent(self, e):  # noqa: N802
        if not self.pix:
            return
        if not self._drag:
            cursors = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                       "bl": Qt.SizeBDiagCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
                       "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor, "move": Qt.SizeAllCursor}
            self.setCursor(cursors.get(self._hit(e.position()), Qt.ArrowCursor))
            return
        ir = self._img_rect()
        dx = (e.position().x() - self._start.x()) / ir.width()
        dy = (e.position().y() - self._start.y()) / ir.height()
        r = QRectF(self._start_crop)
        if self._drag == "move":
            r.translate(dx, dy)
            self.crop = self._clamp(r)
        else:
            if "l" in self._drag:
                r.setLeft(min(max(0, r.left() + dx), r.right() - 0.02))
            if "r" in self._drag:
                r.setRight(max(min(1, r.right() + dx), r.left() + 0.02))
            if "t" in self._drag:
                r.setTop(min(max(0, r.top() + dy), r.bottom() - 0.02))
            if "b" in self._drag:
                r.setBottom(max(min(1, r.bottom() + dy), r.top() + 0.02))
            if self.aspect:
                a = self.aspect * self.pix.height() / self.pix.width()
                h = r.width() / a
                if "t" in self._drag:
                    r.setTop(r.bottom() - h)
                else:
                    r.setBottom(r.top() + h)
                if r.top() < 0 or r.bottom() > 1:
                    # height overflow: shrink width instead
                    h = (r.bottom() if r.top() < 0 else 1 - r.top())
                    h = min(h, 1.0)
                    w = h * a
                    if "l" in self._drag:
                        r.setLeft(r.right() - w)
                    else:
                        r.setRight(r.left() + w)
                    if "t" in self._drag:
                        r.setTop(r.bottom() - h)
                    else:
                        r.setBottom(r.top() + h)
            self.crop = r.normalized().intersected(QRectF(0, 0, 1, 1))
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = None

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(theme.BG))
        if not self.pix:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Перетащите сюда фото или видео\nили нажмите «Открыть»")
            return
        ir = self._img_rect()
        p.drawPixmap(ir.toRect(), self.pix)
        if not self.enabled_crop:
            return
        cr = self._crop_px()
        shade = QPainterPath()
        shade.addRect(ir)
        hole = QPainterPath()
        if self.shape == "circle":
            s = min(cr.width(), cr.height())
            hole.addEllipse(QRectF(cr.center().x() - s / 2, cr.center().y() - s / 2, s, s))
        elif self.shape == "ellipse":
            hole.addEllipse(cr)
        elif self.shape == "rounded":
            rad = min(cr.width(), cr.height()) * 0.08
            hole.addRoundedRect(cr, rad, rad)
        else:
            hole.addRect(cr)
        p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 150))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
        p.drawRect(cr)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        for i in (1, 2):
            x = cr.left() + cr.width() * i / 3
            y = cr.top() + cr.height() * i / 3
            p.drawLine(QPointF(x, cr.top()), QPointF(x, cr.bottom()))
            p.drawLine(QPointF(cr.left(), y), QPointF(cr.right(), y))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        for pt in (cr.topLeft(), cr.topRight(), cr.bottomLeft(), cr.bottomRight()):
            p.drawEllipse(pt, self.HANDLE / 2 + 1, self.HANDLE / 2 + 1)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()


# ---------------------------------------------------------------- before/after compare
class CompareView(QWidget):
    """Wipe comparison: drag the divider to compare before/after."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(280)
        self.before: QPixmap | None = None
        self.after: QPixmap | None = None
        self.split = 0.5
        self.setCursor(Qt.SizeHorCursor)

    def set_images(self, before: QPixmap | None, after: QPixmap | None) -> None:
        self.before, self.after = before, after
        self.update()

    def _rect(self) -> QRectF:
        ref = self.after or self.before
        if not ref:
            return QRectF()
        k = min(self.width() / ref.width(), self.height() / ref.height())
        w, h = ref.width() * k, ref.height() * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def mouseMoveEvent(self, e):  # noqa: N802
        r = self._rect()
        if r.width() and e.buttons():
            self.split = min(1, max(0, (e.position().x() - r.left()) / r.width()))
            self.update()

    mousePressEvent = mouseMoveEvent

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(theme.BG))
        r = self._rect()
        if not r.width():
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Здесь появится сравнение «до / после»")
            return
        x = r.left() + r.width() * self.split
        if self.before:
            p.save()
            p.setClipRect(QRectF(r.left(), r.top(), x - r.left(), r.height()))
            p.drawPixmap(r.toRect(), self.before)
            p.restore()
        if self.after:
            p.save()
            p.setClipRect(QRectF(x, r.top(), r.right() - x, r.height()))
            p.drawPixmap(r.toRect(), self.after)
            p.restore()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("white"), 2))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(QPointF(x, r.center().y()), 10, 10)
        p.setPen(QColor("white"))
        p.drawText(QRectF(r.left() + 8, r.top() + 6, 80, 20), "ДО")
        p.drawText(QRectF(r.right() - 80, r.top() + 6, 72, 20), Qt.AlignRight, "ПОСЛЕ")
