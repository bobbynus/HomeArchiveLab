"""Editor: interactive crop, rotate/flip, shapes and social presets with live result preview."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from ...core.media import get_info, kind_of, load_preview
from ...core.presets import ASPECTS
from ...core.transform import apply_image, output_path, process
from .. import icons, theme
from ..recipe_form import RecipeForm
from ..widgets import Card, CropCanvas, Page, ProgressRow, button, label, pil_to_qimage, run_task


class EditorPage(Page):
    def __init__(self, state):
        super().__init__("Редактор", "Кроп, поворот, форма и размеры для соцсетей", state)
        self.files: list[Path] = []
        self.index = 0
        self.rotate = 0
        self.flip_h = self.flip_v = False
        self.base_pix: QPixmap | None = None
        self.source_img = None  # PIL preview, orientation-corrected
        self.info = None

        b_open = button("Открыть", "folder")
        b_open.clicked.connect(self.open_dialog)
        self.b_prev = button("◀", tip="Предыдущий файл")
        self.b_next = button("▶", tip="Следующий файл")
        self.counter = label("", "Muted")
        self.b_prev.clicked.connect(lambda: self.load_index(self.index - 1))
        self.b_next.clicked.connect(lambda: self.load_index(self.index + 1))
        for w in (self.counter, self.b_prev, self.b_next, b_open):
            self.actions.addWidget(w)

        main = QHBoxLayout()
        left = QVBoxLayout()
        tools = QHBoxLayout()
        tools.setSpacing(6)
        for name, tip, fn in (("rotl", "Повернуть влево", lambda: self._rotate(-90)),
                              ("rotr", "Повернуть вправо", lambda: self._rotate(90)),
                              ("fliph", "Отразить по горизонтали", lambda: self._flip("h")),
                              ("flipv", "Отразить по вертикали", lambda: self._flip("v"))):
            tb = QToolButton()
            tb.setIcon(icons.icon(name))
            tb.setIconSize(QSize(20, 20))
            tb.setToolTip(tip)
            tb.clicked.connect(fn)
            tools.addWidget(tb)
        tools.addStretch()
        b_reset = button("Сброс")
        b_reset.clicked.connect(self._reset)
        tools.addWidget(b_reset)
        left.addLayout(tools)
        aspects = QHBoxLayout()
        aspects.setSpacing(4)
        aspects.addWidget(label("Пропорции:", "Muted"))
        self.aspect_group = QButtonGroup(self)
        self.aspect_group.setExclusive(True)
        for i, name in enumerate(ASPECTS):
            b = QPushButton(name)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.aspect_group.addButton(b)
            aspects.addWidget(b)
        self.aspect_group.buttonClicked.connect(self._aspect_clicked)
        aspects.addStretch()
        left.addLayout(aspects)
        self.canvas = CropCanvas()
        self.canvas.setAcceptDrops(True)
        self.canvas.dropEvent = self._drop  # type: ignore[assignment]
        self.canvas.changed.connect(self._schedule_preview)
        left.addWidget(self.canvas, 1)
        self.crop_info = label("", "Muted")
        left.addWidget(self.crop_info)
        main.addLayout(left, 3)

        # ---- right panel
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 6, 0)
        out = Card("Результат")
        self.form = RecipeForm()
        self.form.changed.connect(self._schedule_preview)
        self.form.preset_selected.connect(self._preset)
        self.form.shape.currentIndexChanged.connect(self._shape)
        out.lay.addWidget(self.form)
        pl.addWidget(out)

        self.video_card = Card("Видео")
        vf = QFormLayout()
        self.t_start = QDoubleSpinBox()
        self.t_end = QDoubleSpinBox()
        for s in (self.t_start, self.t_end):
            s.setRange(0, 1e6)
            s.setSuffix(" с")
            s.setDecimals(1)
            s.setButtonSymbols(QDoubleSpinBox.NoButtons)
        trim = QHBoxLayout()
        trim.addWidget(self.t_start)
        trim.addWidget(QLabel("—"))
        trim.addWidget(self.t_end)
        vf.addRow("Обрезка", trim)
        self.mute = QCheckBox("Без звука")
        vf.addRow("", self.mute)
        self.video_card.lay.addLayout(vf)
        self.video_card.hide()
        pl.addWidget(self.video_card)

        prev_card = Card("Предпросмотр")
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.preview.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #232733, stop:1 #191c24); border-radius:10px;")
        prev_card.lay.addWidget(self.preview)
        self.out_info = label("", "Muted")
        prev_card.lay.addWidget(self.out_info)
        pl.addWidget(prev_card)

        save = QGridLayout()
        self.b_save = button("Сохранить копию", "download", "Primary")
        self.b_save_as = button("Сохранить как…")
        self.b_batch = button("Применить к пачке", "batch")
        self.b_save.setToolTip("Сохранить рядом с оригиналом с суффиксом _edit")
        save.addWidget(self.b_save, 0, 0, 1, 2)
        save.addWidget(self.b_save_as, 1, 0)
        save.addWidget(self.b_batch, 1, 1)
        pl.addLayout(save)
        self.progress = ProgressRow()
        pl.addWidget(self.progress)
        pl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(400)
        main.addWidget(scroll)
        self.body.addLayout(main, 1)

        self.b_save.clicked.connect(lambda: self.save(ask=False))
        self.b_save_as.clicked.connect(lambda: self.save(ask=True))
        self.b_batch.clicked.connect(self._to_batch)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._render_preview)
        state.send_to.connect(self._receive)
        self._update_nav()

    # ---- loading
    def _receive(self, key, paths):
        if key == "edit":
            self.set_files(paths)

    def _drop(self, e):
        self.set_files([Path(u.toLocalFile()) for u in e.mimeData().urls()])

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Открыть", self.state.library or "",
                                                "Медиа (*.jpg *.jpeg *.png *.webp *.heic *.tif *.tiff *.bmp "
                                                "*.mp4 *.mov *.m4v *.avi *.mkv *.webm)")
        if files:
            self.set_files([Path(f) for f in files])

    def set_files(self, files):
        self.files = [Path(f) for f in files if kind_of(Path(f)) in ("image", "video")]
        self.load_index(0)

    def _update_nav(self):
        n = len(self.files)
        self.counter.setText(f"{self.index + 1} / {n}" if n > 1 else "")
        self.b_prev.setVisible(n > 1)
        self.b_next.setVisible(n > 1)

    def load_index(self, i):
        if not self.files:
            return
        self.index = i % len(self.files)
        path = self.files[self.index]
        self._update_nav()
        self.rotate = 0
        self.flip_h = self.flip_v = False
        self.crop_info.setText("Загрузка…")

        def work(report, cancelled):
            return load_preview(path, 1600), get_info(path)

        def done(res):
            img, info = res
            if path != self.files[self.index]:
                return
            self.source_img, self.info = img, info
            is_video = info.kind == "video"
            self.video_card.setVisible(is_video)
            if is_video:
                self.t_start.setValue(0)
                self.t_end.setValue(info.duration or 0)
            self.base_pix = QPixmap.fromImage(pil_to_qimage(img)) if img else None
            self._apply_orientation(reset_crop=True)

        run_task(work, done, on_error=lambda m: QMessageBox.warning(self, "Ошибка", m))

    # ---- orientation & crop
    def _apply_orientation(self, reset_crop=False):
        if not self.base_pix:
            self.canvas.set_image(None)
            return
        t = QTransform().rotate(self.rotate).scale(-1 if self.flip_h else 1, -1 if self.flip_v else 1)
        crop = self.canvas.crop
        self.canvas.set_image(self.base_pix.transformed(t, Qt.SmoothTransformation))
        if not reset_crop:
            self.canvas.crop = crop
        self._aspect_clicked(self.aspect_group.checkedButton())

    def _rotate(self, deg):
        self.rotate = (self.rotate + deg) % 360
        self._apply_orientation(reset_crop=True)

    def _flip(self, axis):
        if axis == "h":
            self.flip_h = not self.flip_h
        else:
            self.flip_v = not self.flip_v
        self._apply_orientation()

    def _aspect_clicked(self, b):
        if not b:
            return
        val = ASPECTS[b.text()]
        if val == "orig" and self.canvas.pix:
            self.canvas.set_aspect(self.canvas.pix.width() / self.canvas.pix.height())
        elif isinstance(val, tuple):
            self.canvas.set_aspect(val[0] / val[1])
        else:
            self.canvas.set_aspect(None)

    def _preset(self, preset):
        if preset is None:
            return
        # Lock the crop frame to the preset's proportions for a "what you see is what you get" result.
        for b in self.aspect_group.buttons():
            b.setChecked(False)
        self.aspect_group.setExclusive(False)
        self.aspect_group.setExclusive(True)
        self.canvas.set_aspect(preset.ratio)

    def _shape(self):
        shape = self.form.shape.currentData()
        self.canvas.shape = shape
        if shape == "circle":
            self.canvas.set_aspect(1.0)
        self.canvas.update()

    def _reset(self):
        self.rotate = 0
        self.flip_h = self.flip_v = False
        self._apply_orientation(reset_crop=True)
        self.canvas.reset()

    # ---- recipe & preview
    def recipe(self):
        r = self.form.recipe()
        c = self.canvas.crop
        if not (c.x() <= 0.0005 and c.y() <= 0.0005 and c.width() >= 0.999 and c.height() >= 0.999):
            r.crop = (c.x(), c.y(), c.width(), c.height())
        r.rotate, r.flip_h, r.flip_v = self.rotate, self.flip_h, self.flip_v
        if self.info and self.info.kind == "video":
            if self.t_start.value() > 0 or (self.info.duration and self.t_end.value() < self.info.duration - 0.05):
                r.video_trim = (self.t_start.value(), self.t_end.value())
            r.video_mute = self.mute.isChecked()
        return r

    def _schedule_preview(self):
        c = self.canvas.crop
        if self.info and self.info.width:
            w, h = self.info.width, self.info.height
            if self.rotate in (90, 270):
                w, h = h, w
            self.crop_info.setText(f"Исходник {w}×{h} · кадр {round(c.width() * w)}×{round(c.height() * h)}")
        self._timer.start()

    def _render_preview(self):
        if self.source_img is None:
            return
        r = self.recipe()
        src = self.source_img
        # Preview uses the downscaled image; scale sizes proportionally for speed.
        full_w = (self.info.width or src.width) if self.info else src.width
        k = src.width / full_w if full_w else 1
        tw, th, le = r.width, r.height, r.long_edge
        r.width, r.height, r.long_edge = int(r.width * k), int(r.height * k), int(r.long_edge * k)
        r.no_upscale = False
        try:
            out = apply_image(src.copy(), r)
        except Exception as e:  # pragma: no cover
            self.out_info.setText(f"Ошибка: {e}")
            return
        pm = QPixmap.fromImage(pil_to_qimage(out))
        self.preview.setPixmap(pm.scaled(self.preview.width() - 12, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if tw and th:
            size = f"{tw}×{th}"
        else:
            size = f"≈{round(out.width / k)}×{round(out.height / k)}"
        self.out_info.setText(f"Итог: {size} px")

    # ---- saving
    def save(self, ask: bool):
        if not self.files:
            return
        src = self.files[self.index]
        r = self.recipe()
        dst = output_path(src, None, "_edit", r)
        if ask:
            f, _ = QFileDialog.getSaveFileName(self, "Сохранить как", str(dst))
            if not f:
                return
            dst = Path(f)
        self.b_save.setEnabled(False)
        self.progress.start(f"Сохранение {dst.name}…")

        def work(report, cancelled):
            return process(src, dst, r, lambda f: report(f, f"Кодирование видео… {int(f * 100)}%"))

        def done(p):
            self.b_save.setEnabled(True)
            self.progress.finish(f"Сохранено: {p.name}")
            self.state.toast.emit(f"Сохранено: {p.name}")

        def err(m):
            self.b_save.setEnabled(True)
            self.progress.finish("Ошибка")
            QMessageBox.critical(self, "Ошибка", m)

        run_task(work, done, self.progress.update, err)

    def _to_batch(self):
        """Send the current settings (without the per-photo crop) to the batch page."""
        r = self.recipe()
        r.crop = None
        self.state.send_to.emit("batch_recipe", [r])
        if self.files:
            self.state.send_to.emit("batch", self.files)
