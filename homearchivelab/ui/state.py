"""Shared application state passed to every page."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core.settings import Settings


class AppState(QObject):
    library_changed = Signal(str)
    selection_changed = Signal(list)
    send_to = Signal(str, list)  # (page key, [Path]) — "edit", "batch", "upscale", "meta"
    toast = Signal(str)

    def __init__(self):
        super().__init__()
        self.library: str = Settings.get("library") or ""
        self.selection: list[Path] = []

    def set_library(self, path: str) -> None:
        self.library = path
        Settings.set("library", path)
        self.library_changed.emit(path)

    def set_selection(self, paths: list[Path]) -> None:
        self.selection = paths
        self.selection_changed.emit(paths)
