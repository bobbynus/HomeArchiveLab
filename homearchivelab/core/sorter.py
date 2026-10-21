"""Sort media into folders using a path pattern built from file information."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .media import MediaInfo, get_info

MONTHS_RU = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
             "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
KIND_RU = {"image": "Фото", "raw": "RAW", "video": "Видео", "other": "Прочее"}

# Ready-made patterns shown in the UI.
SORT_PATTERNS = {
    "Год / Месяц": "{year}/{month:02d} {month_name}",
    "Год / Месяц / День": "{year}/{month:02d}/{day:02d}",
    "Год-Месяц-День": "{year}-{month:02d}-{day:02d}",
    "Тип / Год": "{kind}/{year}",
    "Тип / Год / Месяц": "{kind}/{year}/{month:02d} {month_name}",
    "Камера / Год": "{camera}/{year}",
    "Расширение": "{ext}",
}


@dataclass
class SortItem:
    src: Path
    dst: Path
    status: str = "pending"  # pending | done | skipped | error
    message: str = ""


def target_dir(info: MediaInfo, pattern: str) -> str:
    d = info.best_date
    fields = {
        "year": d.year, "month": d.month, "day": d.day,
        "month_name": MONTHS_RU[d.month],
        "kind": KIND_RU.get(info.kind, "Прочее"),
        "camera": _safe(info.camera or "Без камеры"),
        "ext": info.path.suffix.lower().lstrip(".").upper() or "NOEXT",
    }
    return pattern.format(**fields)


def _safe(name: str) -> str:
    return "".join("_" if c in '<>:"/\\|?*' else c for c in name).strip(" .") or "_"


def _unique(dst: Path, reserved: set[Path]) -> Path:
    if not dst.exists() and dst not in reserved:
        return dst
    i = 1
    while True:
        cand = dst.with_name(f"{dst.stem} ({i}){dst.suffix}")
        if not cand.exists() and cand not in reserved:
            return cand
        i += 1


def plan_sort(files: Iterable[Path], dest_root: Path, pattern: str, rename: str = "",
              progress: Callable[[int, str], None] | None = None) -> list[SortItem]:
    """Build a dry-run plan. `rename` may be e.g. '{year}{month:02d}{day:02d}_{hour:02d}{minute:02d}{second:02d}'."""
    plan: list[SortItem] = []
    reserved: set[Path] = set()
    for i, src in enumerate(files):
        try:
            info = get_info(src)
            folder = dest_root / target_dir(info, pattern)
            name = src.name
            if rename:
                d = info.best_date
                stem = rename.format(year=d.year, month=d.month, day=d.day, hour=d.hour,
                                     minute=d.minute, second=d.second, name=src.stem)
                name = _safe(stem) + src.suffix.lower()
            dst = folder / name
            if dst.resolve() == src.resolve():
                plan.append(SortItem(src, dst, "skipped", "уже на месте"))
            else:
                dst = _unique(dst, reserved)
                reserved.add(dst)
                plan.append(SortItem(src, dst))
        except Exception as e:
            plan.append(SortItem(src, src, "error", str(e)))
        if progress:
            progress(i + 1, src.name)
    return plan


def execute_sort(plan: list[SortItem], move: bool,
                 progress: Callable[[int, str], None] | None = None,
                 cancelled: Callable[[], bool] = lambda: False) -> list[SortItem]:
    for i, item in enumerate(plan):
        if cancelled():
            break
        if item.status != "pending":
            continue
        try:
            item.dst.parent.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(str(item.src), str(item.dst))
            else:
                shutil.copy2(item.src, item.dst)
            item.status = "done"
        except Exception as e:
            item.status, item.message = "error", str(e)
        if progress:
            progress(i + 1, item.src.name)
    return plan
