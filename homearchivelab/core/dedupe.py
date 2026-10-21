"""Duplicate finder: exact (content hash) and visually similar (perceptual hash)."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .media import get_info, kind_of, load_preview


@dataclass
class DupGroup:
    files: list[Path]
    reason: str  # "exact" | "similar"
    keep: Path | None = None
    sizes: dict = field(default_factory=dict)
    pixels: dict = field(default_factory=dict)


def file_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _quick_hash(path: Path) -> str:
    """Hash of first+last 64 KB — cheap pre-filter before the full hash."""
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        h.update(f.read(65536))
        try:
            f.seek(-65536, 2)
        except OSError:
            f.seek(0)
        h.update(f.read(65536))
    return h.hexdigest()


def _choose_keep(group: DupGroup) -> Path:
    """Keep the largest resolution, then the biggest file, then the shortest path."""
    return max(group.files, key=lambda p: (group.pixels.get(p, 0), group.sizes.get(p, 0), -len(str(p))))


def find_duplicates(files: Iterable[Path], similar: bool = True, threshold: int = 8,
                    progress: Callable[[int, int, str], None] | None = None,
                    cancelled: Callable[[], bool] = lambda: False) -> list[DupGroup]:
    files = list(files)
    total = len(files) * (2 if similar else 1)
    step = 0

    # Stage 1: exact duplicates (size -> quick hash -> full hash).
    by_size: dict[int, list[Path]] = defaultdict(list)
    sizes: dict[Path, int] = {}
    for p in files:
        try:
            sizes[p] = p.stat().st_size
            by_size[sizes[p]].append(p)
        except OSError:
            pass
    groups: list[DupGroup] = []
    in_exact: set[Path] = set()
    for size, same in by_size.items():
        if cancelled():
            return groups
        if len(same) < 2:
            step += len(same)
            continue
        by_quick: dict[str, list[Path]] = defaultdict(list)
        for p in same:
            by_quick[_quick_hash(p)].append(p)
        for cand in by_quick.values():
            if len(cand) < 2:
                continue
            by_full: dict[str, list[Path]] = defaultdict(list)
            for p in cand:
                by_full[file_hash(p)].append(p)
            for dup in by_full.values():
                if len(dup) > 1:
                    g = DupGroup(sorted(dup), "exact", sizes={p: sizes[p] for p in dup})
                    groups.append(g)
                    in_exact.update(dup[1:])  # one representative stays for similarity
        step += len(same)
        if progress:
            progress(step, total, same[0].name)

    # Stage 2: visually similar images (resized, re-encoded, etc).
    if similar:
        import imagehash

        hashes: list[tuple[Path, "imagehash.ImageHash"]] = []
        pixels: dict[Path, int] = {}
        for p in files:
            step += 1
            if cancelled():
                return groups
            if p in in_exact or kind_of(p) != "image":
                continue
            img = load_preview(p, 256)
            if img is None:
                continue
            hashes.append((p, imagehash.phash(img)))
            try:
                info = get_info(p)
                pixels[p] = (info.width or 0) * (info.height or 0)
            except Exception:
                pass
            if progress and step % 5 == 0:
                progress(step, total, p.name)
        # Union-find over pairs under the Hamming threshold.
        parent = list(range(len(hashes)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(hashes)):
            for j in range(i + 1, len(hashes)):
                if hashes[i][1] - hashes[j][1] <= threshold:
                    parent[find(i)] = find(j)
        clusters: dict[int, list[Path]] = defaultdict(list)
        for i, (p, _) in enumerate(hashes):
            clusters[find(i)].append(p)
        for members in clusters.values():
            if len(members) > 1:
                groups.append(DupGroup(sorted(members), "similar",
                                       sizes={p: sizes.get(p, 0) for p in members},
                                       pixels={p: pixels.get(p, 0) for p in members}))
    for g in groups:
        if not g.pixels:
            g.pixels = {}
        g.keep = _choose_keep(g)
    if progress:
        progress(total, total, "")
    return groups


def remove_files(paths: Iterable[Path], to_trash: bool = True) -> list[tuple[Path, str]]:
    """Delete files (to Recycle Bin by default). Returns [(path, error)] for failures."""
    errors = []
    for p in paths:
        try:
            if to_trash:
                from send2trash import send2trash

                send2trash(str(p))
            else:
                p.unlink()
        except Exception as e:
            errors.append((p, str(e)))
    return errors
