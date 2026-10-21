"""Media discovery and file information (images via Pillow, video via ffprobe)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from PIL import ExifTags, Image

try:  # HEIC/HEIF support (iPhone photos)
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:  # pragma: no cover
    HEIF_SUPPORTED = False

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif"}
RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".3gp", ".webm", ".mts", ".m2ts"}
MEDIA_EXT = IMAGE_EXT | RAW_EXT | VIDEO_EXT

# Windows: never pop a console window for ffmpeg/ffprobe.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_EXIF_TAGS = {v: k for k, v in ExifTags.TAGS.items()}


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in RAW_EXT:
        return "raw"
    if ext in VIDEO_EXT:
        return "video"
    return "other"


def is_media(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXT


def iter_media(root: Path | str, recursive: bool = True) -> Iterator[Path]:
    root = Path(root)
    if root.is_file():
        if is_media(root):
            yield root
        return
    walker = os.walk(root) if recursive else [(str(root), [], os.listdir(root))]
    for dirpath, dirnames, filenames in walker:
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            if is_media(p):
                yield p


def find_tool(name: str) -> str | None:
    """Locate an external binary: app tools/ folder first, then PATH."""
    from .settings import Settings

    local = Settings.tools_dir() / (name + (".exe" if os.name == "nt" else ""))
    if local.exists():
        return str(local)
    return shutil.which(name)


@dataclass
class MediaInfo:
    path: Path
    kind: str
    size: int
    modified: datetime
    width: int | None = None
    height: int | None = None
    taken: datetime | None = None
    camera: str | None = None
    lens: str | None = None
    duration: float | None = None
    codec: str | None = None
    fps: float | None = None
    gps: tuple[float, float] | None = None
    fmt: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def best_date(self) -> datetime:
        return self.taken or self.modified

    @property
    def resolution(self) -> str:
        return f"{self.width}×{self.height}" if self.width and self.height else "—"

    def as_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("Имя", self.path.name),
            ("Папка", str(self.path.parent)),
            ("Тип", {"image": "Фото", "raw": "RAW", "video": "Видео"}.get(self.kind, self.kind)),
            ("Формат", self.fmt or self.path.suffix.upper().lstrip(".")),
            ("Размер файла", human_size(self.size)),
            ("Разрешение", self.resolution),
        ]
        if self.width and self.height:
            rows.append(("Мегапиксели", f"{self.width * self.height / 1e6:.1f} MP"))
        if self.duration:
            rows.append(("Длительность", fmt_duration(self.duration)))
        if self.fps:
            rows.append(("Кадров/с", f"{self.fps:.2f}"))
        if self.codec:
            rows.append(("Кодек", self.codec))
        rows.append(("Дата съёмки", self.taken.strftime("%d.%m.%Y %H:%M:%S") if self.taken else "—"))
        rows.append(("Изменён", self.modified.strftime("%d.%m.%Y %H:%M:%S")))
        if self.camera:
            rows.append(("Камера", self.camera))
        if self.lens:
            rows.append(("Объектив", self.lens))
        if self.gps:
            rows.append(("GPS", f"{self.gps[0]:.6f}, {self.gps[1]:.6f}"))
        for k, v in self.extra.items():
            rows.append((k, str(v)))
        return rows


def human_size(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _parse_exif_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode(errors="ignore")
    value = str(value).strip("\x00 ")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(value[: len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


def _gps_to_deg(values, ref) -> float | None:
    try:
        d, m, s = (float(v) for v in values)
        deg = d + m / 60 + s / 3600
        return -deg if ref in ("S", "W") else deg
    except Exception:
        return None


def _fix_text(val):
    """EXIF ASCII fields are often UTF-8 in practice; Pillow decodes them as latin-1."""
    if isinstance(val, str):
        try:
            return val.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return val
    return val


def read_exif(img: Image.Image) -> dict:
    """Flattened EXIF dict {tag_name: value} including the Exif and GPS IFDs."""
    out: dict = {}
    try:
        exif = img.getexif()
    except Exception:
        return out
    for tag, val in exif.items():
        out[ExifTags.TAGS.get(tag, str(tag))] = _fix_text(val)
    try:
        for tag, val in exif.get_ifd(0x8769).items():  # Exif IFD
            out[ExifTags.TAGS.get(tag, str(tag))] = _fix_text(val)
        gps = exif.get_ifd(0x8825)
        if gps:
            out["_GPS"] = {ExifTags.GPSTAGS.get(t, str(t)): v for t, v in gps.items()}
    except Exception:
        pass
    return out


def probe_video(path: Path) -> dict:
    ffprobe = find_tool("ffprobe")
    if not ffprobe:
        return {}
    try:
        res = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=30, creationflags=NO_WINDOW,
        )
        return json.loads(res.stdout or b"{}")
    except Exception:
        return {}


def get_info(path: Path | str) -> MediaInfo:
    path = Path(path)
    st = path.stat()
    info = MediaInfo(
        path=path, kind=kind_of(path), size=st.st_size,
        modified=datetime.fromtimestamp(st.st_mtime),
    )
    if info.kind == "image":
        try:
            with Image.open(path) as img:
                info.width, info.height = img.size
                info.fmt = img.format
                exif = read_exif(img)
                info.taken = _parse_exif_date(
                    exif.get("DateTimeOriginal") or exif.get("DateTimeDigitized") or exif.get("DateTime")
                )
                make, model = str(exif.get("Make", "")).strip("\x00 "), str(exif.get("Model", "")).strip("\x00 ")
                if model:
                    info.camera = model if make and model.startswith(make) else f"{make} {model}".strip()
                if exif.get("LensModel"):
                    info.lens = str(exif["LensModel"]).strip("\x00 ")
                if exif.get("Orientation") in (5, 6, 7, 8):
                    info.width, info.height = info.height, info.width
                if exif.get("FNumber"):
                    info.extra["Диафрагма"] = f"f/{float(exif['FNumber']):.1f}"
                if exif.get("ExposureTime"):
                    et = float(exif["ExposureTime"])
                    info.extra["Выдержка"] = f"1/{round(1 / et)} с" if 0 < et < 1 else f"{et:g} с"
                if exif.get("ISOSpeedRatings"):
                    info.extra["ISO"] = exif["ISOSpeedRatings"]
                if exif.get("FocalLength"):
                    info.extra["Фокусное"] = f"{float(exif['FocalLength']):.0f} мм"
                gps = exif.get("_GPS") or {}
                if "GPSLatitude" in gps and "GPSLongitude" in gps:
                    lat = _gps_to_deg(gps["GPSLatitude"], gps.get("GPSLatitudeRef"))
                    lon = _gps_to_deg(gps["GPSLongitude"], gps.get("GPSLongitudeRef"))
                    if lat is not None and lon is not None:
                        info.gps = (lat, lon)
        except Exception as e:
            info.extra["Ошибка"] = str(e)
    elif info.kind == "video":
        data = probe_video(path)
        fmt = data.get("format", {})
        info.fmt = fmt.get("format_long_name") or fmt.get("format_name")
        if fmt.get("duration"):
            info.duration = float(fmt["duration"])
        tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
        if tags.get("creation_time"):
            try:
                info.taken = datetime.fromisoformat(tags["creation_time"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            except ValueError:
                pass
        model = tags.get("com.apple.quicktime.model") or tags.get("model")
        if model:
            info.camera = model
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and info.width is None:
                info.width, info.height = s.get("width"), s.get("height")
                info.codec = s.get("codec_name")
                rot = (s.get("tags") or {}).get("rotate") or next(
                    (d.get("rotation") for d in s.get("side_data_list", []) if "rotation" in d), None)
                if rot and abs(int(float(rot))) in (90, 270):
                    info.width, info.height = info.height, info.width
                try:
                    num, den = s.get("avg_frame_rate", "0/1").split("/")
                    info.fps = float(num) / float(den) if float(den) else None
                except Exception:
                    pass
            elif s.get("codec_type") == "audio":
                info.extra["Аудио"] = f"{s.get('codec_name')} {s.get('sample_rate', '')} Гц".strip()
        if fmt.get("bit_rate"):
            info.extra["Битрейт"] = f"{int(fmt['bit_rate']) / 1e6:.1f} Мбит/с"
    return info


def load_preview(path: Path | str, max_side: int = 512) -> Image.Image | None:
    """Return an RGB thumbnail for images and videos (first-second frame via ffmpeg)."""
    path = Path(path)
    kind = kind_of(path)
    try:
        if kind == "image":
            from PIL import ImageOps

            with Image.open(path) as img:
                img.draft("RGB", (max_side, max_side))
                img = ImageOps.exif_transpose(img)
                img.thumbnail((max_side, max_side))
                return img.convert("RGB")
        if kind == "video":
            ffmpeg = find_tool("ffmpeg")
            if not ffmpeg:
                return None
            res = subprocess.run(
                [ffmpeg, "-v", "quiet", "-ss", "1", "-i", str(path), "-frames:v", "1",
                 "-vf", f"scale={max_side}:{max_side}:force_original_aspect_ratio=decrease",
                 "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True, timeout=30, creationflags=NO_WINDOW,
            )
            if not res.stdout:  # very short clip: grab frame 0
                res = subprocess.run(
                    [ffmpeg, "-v", "quiet", "-i", str(path), "-frames:v", "1",
                     "-vf", f"scale={max_side}:{max_side}:force_original_aspect_ratio=decrease",
                     "-f", "image2pipe", "-vcodec", "png", "-"],
                    capture_output=True, timeout=30, creationflags=NO_WINDOW,
                )
            if res.stdout:
                import io

                return Image.open(io.BytesIO(res.stdout)).convert("RGB")
    except Exception:
        return None
    return None
