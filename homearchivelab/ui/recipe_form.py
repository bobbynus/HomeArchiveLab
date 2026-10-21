"""Form for output settings (preset, size, fit mode, shape, format) shared by the editor and batch pages."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFormLayout, QHBoxLayout, QPushButton, QSlider,
                               QSpinBox, QWidget)

from ..core.presets import PRESETS, Preset, groups
from ..core.settings import Settings
from ..core.transform import FORMATS, RESIZE_MODES, SHAPES, Recipe
from . import icons


def _spin(maximum=20000, special="авто") -> QSpinBox:
    s = QSpinBox()
    s.setRange(0, maximum)
    s.setSpecialValueText(special)
    s.setSuffix(" px")
    s.setButtonSymbols(QSpinBox.NoButtons)
    return s


class RecipeForm(QWidget):
    changed = Signal()
    preset_selected = Signal(object)  # Preset | None

    def __init__(self, show_preset: bool = True):
        super().__init__()
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignLeft)

        self.group = QComboBox()
        self.group.addItem("Без пресета", None)
        for g in groups():
            self.group.addItem(g, g)
        self.preset = QComboBox()
        self.group.currentIndexChanged.connect(self._fill_presets)
        self.preset.currentIndexChanged.connect(self._preset_chosen)
        if show_preset:
            form.addRow("Соцсеть", self.group)
            form.addRow("Формат", self.preset)
        self.preset.setVisible(show_preset)

        size = QHBoxLayout()
        self.w = _spin()
        self.h = _spin()
        swap = QPushButton()
        swap.setIcon(icons.icon("fliph"))
        swap.setFixedWidth(38)
        swap.setToolTip("Поменять местами")
        swap.clicked.connect(self._swap)
        size.addWidget(self.w)
        size.addWidget(swap)
        size.addWidget(self.h)
        form.addRow("Размер", size)
        self.long_edge = _spin(special="—")
        self.long_edge.setToolTip("Альтернатива: ограничить длинную сторону (если ширина и высота «авто»)")
        form.addRow("Длинная сторона", self.long_edge)

        self.mode = QComboBox()
        for k, v in RESIZE_MODES.items():
            self.mode.addItem(v, k)
        form.addRow("Вписывание", self.mode)

        self.shape = QComboBox()
        for k, v in SHAPES.items():
            self.shape.addItem(v, k)
        self.radius = QSlider(Qt.Horizontal)
        self.radius.setRange(2, 50)
        self.radius.setValue(8)
        self.radius.setVisible(False)
        self.shape.currentIndexChanged.connect(lambda: self.radius.setVisible(self.shape.currentData() == "rounded"))
        form.addRow("Форма", self.shape)
        form.addRow("", self.radius)

        self.color = QPushButton()
        self._color = "#000000"
        self._paint_color()
        self.color.clicked.connect(self._pick_color)
        form.addRow("Цвет полей", self.color)

        fmt = QHBoxLayout()
        self.fmt = QComboBox()
        for k, v in FORMATS.items():
            self.fmt.addItem(v, k)
        self.quality = QSpinBox()
        self.quality.setRange(40, 100)
        self.quality.setValue(int(Settings.get("jpeg_quality")))
        self.quality.setPrefix("кач. ")
        self.quality.setButtonSymbols(QSpinBox.NoButtons)
        fmt.addWidget(self.fmt, 2)
        fmt.addWidget(self.quality, 1)
        form.addRow("Файл", fmt)

        self.strip = QCheckBox("Удалить метаданные (EXIF, GPS)")
        self.no_up = QCheckBox("Не увеличивать маленькие")
        form.addRow("", self.strip)
        form.addRow("", self.no_up)

        for w in (self.w, self.h, self.long_edge, self.quality):
            w.valueChanged.connect(self.changed)
        for w in (self.mode, self.shape, self.fmt):
            w.currentIndexChanged.connect(self.changed)
        self.radius.valueChanged.connect(self.changed)
        self.strip.toggled.connect(self.changed)
        self.no_up.toggled.connect(self.changed)
        self._fill_presets()

    def _fill_presets(self):
        g = self.group.currentData()
        self.preset.blockSignals(True)
        self.preset.clear()
        if g:
            for p in PRESETS:
                if p.group == g:
                    self.preset.addItem(p.label, p)
        if not g:
            self.preset.addItem("—", None)
        self.preset.setEnabled(bool(g))
        self.preset.blockSignals(False)
        self._preset_chosen()

    def _preset_chosen(self):
        p: Preset | None = self.preset.currentData()
        if p:
            self.w.setValue(p.width)
            self.h.setValue(p.height)
            self.long_edge.setValue(0)
        self.preset_selected.emit(p)
        self.changed.emit()

    def _swap(self):
        w, h = self.w.value(), self.h.value()
        self.w.setValue(h)
        self.h.setValue(w)

    def _paint_color(self):
        self.color.setText(self._color.upper())
        self.color.setStyleSheet(f"background:{self._color};color:{'#000' if QColor(self._color).lightness() > 128 else '#fff'};")

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Цвет полей")
        if c.isValid():
            self._color = c.name()
            self._paint_color()
            self.changed.emit()

    def recipe(self) -> Recipe:
        return Recipe(width=self.w.value(), height=self.h.value(), long_edge=self.long_edge.value(),
                      mode=self.mode.currentData(), pad_color=self._color, shape=self.shape.currentData(),
                      corner_radius=self.radius.value(), fmt=self.fmt.currentData(), quality=self.quality.value(),
                      strip_meta=self.strip.isChecked(), no_upscale=self.no_up.isChecked())

    def target_aspect(self) -> float | None:
        if self.w.value() and self.h.value():
            return self.w.value() / self.h.value()
        return None
