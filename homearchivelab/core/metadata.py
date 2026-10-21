"""Read, strip and write metadata (EXIF for images, container tags for video)."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from .media import NO_WINDOW, find_tool, kind_of, read_exif

# Editable fields shown in the UI: key -> (label, EXIF IFD, tag id)
EDITABLE = {
    "Artist": ("Автор", "0th", 315),
    "Copyright": ("Авторские права", "0th", 33432),
    "ImageDescription": ("Описание", "0th", 270),
    "Make": ("Производитель", "0th", 271),
    "Model": ("Модель камеры", "0th", 272),
    "Software": ("Программа", "0th", 305),
    "DateTimeOriginal": ("Дата съёмки (ГГГГ:ММ:ДД ЧЧ:ММ:СС)", "Exif", 36867),
}
VIDEO_EDITABLE = {"title": "Название", "artist": "Автор", "comment": "Комментарий",
                  "copyright": "Авторские права", "creation_time": "Дата создания (ISO)"}


def read_all(path: Path) -> dict[str, str]:
    """Every readable tag as strings — for the info table."""
    path = Path(path)
    if kind_of(path) == "video":
        from .media import probe_video

        data = probe_video(path)
        out = {f"format.{k}": str(v) for k, v in (data.get("format", {}).get("tags") or {}).items()}
        for i, s in enumerate(data.get("streams", [])):
            for k, v in (s.get("tags") or {}).items():
                out[f"stream{i}.{k}"] = str(v)
        return out
    out = {}
    try:
        with Image.open(path) as img:
            for k, v in read_exif(img).items():
                if k == "_GPS":
                    for gk, gv in v.items():
                        out[f"GPS.{gk}"] = _fmt(gv)
                elif k not in ("MakerNote", "UserComment", "PrintImageMatching") and not isinstance(v, dict):
                    out[k] = _fmt(v)
            for k, v in (img.info or {}).items():
                if k not in ("exif", "icc_profile", "xmp") and isinstance(v, (str, int, float)):
                    out[f"info.{k}"] = str(v)
            if img.info.get("icc_profile"):
                out["ICC профиль"] = f"{len(img.info['icc_profile'])} байт"
            if img.info.get("xmp") or img.info.get("XML:com.adobe.xmp"):
                out["XMP"] = "есть"
    except Exception as e:
        out["Ошибка"] = str(e)
    return out


def _fmt(v) -> str:
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", "ignore").strip("\x00 ") or f"<{len(v)} байт>"
        except Exception:
            return f"<{len(v)} байт>"
    if isinstance(v, tuple):
        return ", ".join(_fmt(x) for x in v)
    s = str(v)
    return s if len(s) < 200 else s[:200] + "…"


def _replace(tmp: Path, path: Path, keep_mtime: bool) -> None:
    st = path.stat()
    os.replace(tmp, path)
    if keep_mtime:
        os.utime(path, (st.st_atime, st.st_mtime))


def strip_metadata(path: Path, keep_orientation: bool = True, only_gps: bool = False,
                   output: Path | None = None) -> Path:
    """Remove all metadata (or only GPS). Writes in place unless `output` is given."""
    path = Path(path)
    out = Path(output) if output else path
    tmp = out.with_name(out.stem + ".hal_tmp" + out.suffix)
    if kind_of(path) == "video":
        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg не найден")
        args = [ffmpeg, "-y", "-v", "error", "-i", str(path), "-map", "0", "-c", "copy"]
        args += ["-map_metadata", "0", "-metadata", "location=", "-metadata", "location-eng=",
                 "-metadata", "com.apple.quicktime.location.ISO6709="] if only_gps else ["-map_metadata", "-1"]
        subprocess.run(args + [str(tmp)], check=True, capture_output=True, creationflags=NO_WINDOW)
        _finish(tmp, out, in_place=output is None)
        return out

    import piexif

    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg") and output is None:
        # Lossless: edit the EXIF block without re-encoding pixels.
        if only_gps:
            exif = piexif.load(str(path))
            exif["GPS"] = {}
            piexif.insert(piexif.dump(exif), str(path))
        else:
            orient = None
            if keep_orientation:
                try:
                    orient = piexif.load(str(path))["0th"].get(piexif.ImageIFD.Orientation)
                except Exception:
                    pass
            piexif.remove(str(path))
            if orient and orient != 1:
                piexif.insert(piexif.dump({"0th": {piexif.ImageIFD.Orientation: orient}}), str(path))
        return path

    with Image.open(path) as img:
        img.load()
        exif = img.getexif()
        if only_gps:
            if 0x8825 in exif:
                del exif[0x8825]
            new_exif = exif.tobytes()
        else:
            new = Image.Exif()
            if keep_orientation and exif.get(274, 1) != 1:
                new[274] = exif[274]
            new_exif = new.tobytes() if len(new) else b""
        # Pillow only writes EXIF/XMP/text chunks that are passed explicitly to save().
        params = {"exif": new_exif} if new_exif else {}
        if img.info.get("icc_profile"):
            params["icc_profile"] = img.info["icc_profile"]
        if ext in (".jpg", ".jpeg"):
            params.update(quality=95, subsampling="keep" if img.format == "JPEG" else 0)
        img.save(tmp, format=img.format or None, **params)
    _finish(tmp, out, in_place=output is None)
    return out


def _finish(tmp: Path, out: Path, in_place: bool) -> None:
    if in_place:
        _replace(tmp, out, keep_mtime=True)
    else:
        os.replace(tmp, out)


def write_fields(path: Path, fields: dict[str, str]) -> None:
    """Set metadata fields. Empty string removes the tag."""
    path = Path(path)
    if kind_of(path) == "video":
        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg не найден")
        tmp = path.with_name(path.stem + ".hal_tmp" + path.suffix)
        args = [ffmpeg, "-y", "-v", "error", "-i", str(path), "-map", "0", "-c", "copy", "-map_metadata", "0"]
        for k, v in fields.items():
            args += ["-metadata", f"{k}={v}"]
        subprocess.run(args + [str(tmp)], check=True, capture_output=True, creationflags=NO_WINDOW)
        _replace(tmp, path, keep_mtime=True)
        return

    import piexif

    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
        try:
            exif = piexif.load(str(path))
        except Exception:
            exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        for key, value in fields.items():
            if key not in EDITABLE:
                continue
            _, ifd, tag = EDITABLE[key]
            if value:
                if key == "DateTimeOriginal":
                    datetime.strptime(value, "%Y:%m:%d %H:%M:%S")  # validate
                exif.setdefault(ifd, {})[tag] = value.encode("utf-8")
            else:
                exif.setdefault(ifd, {}).pop(tag, None)
        if not exif.get("1st"):
            exif.pop("thumbnail", None)
        data = piexif.dump(exif)
        if ext in (".jpg", ".jpeg"):
            piexif.insert(data, str(path))
            return
        with Image.open(path) as img:
            img.load()
            tmp = path.with_name(path.stem + ".hal_tmp" + path.suffix)
            img.save(tmp, format=img.format, exif=data, **({"quality": 95} if ext == ".webp" else {}))
        _replace(tmp, path, keep_mtime=True)
        return
    # PNG and others: Pillow Exif container.
    with Image.open(path) as img:
        img.load()
        exif = img.getexif()
        for key, value in fields.items():
            if key not in EDITABLE:
                continue
            _, ifd, tag = EDITABLE[key]
            target = exif.get_ifd(0x8769) if ifd == "Exif" else exif
            if value:
                target[tag] = value
            elif tag in target:
                del target[tag]
        tmp = path.with_name(path.stem + ".hal_tmp" + path.suffix)
        img.save(tmp, format=img.format, exif=exif.tobytes())
    _replace(tmp, path, keep_mtime=True)


def read_fields(path: Path) -> dict[str, str]:
    path = Path(path)
    if kind_of(path) == "video":
        from .media import probe_video

        tags = {k.lower(): v for k, v in (probe_video(path).get("format", {}).get("tags") or {}).items()}
        return {k: str(tags.get(k, "")) for k in VIDEO_EDITABLE}
    out = {k: "" for k in EDITABLE}
    try:
        with Image.open(path) as img:
            exif = read_exif(img)
        for k in EDITABLE:
            if k in exif:
                out[k] = _fmt(exif[k])
    except Exception:
        pass
    return out
