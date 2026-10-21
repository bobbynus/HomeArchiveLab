"""Image/video transforms: crop, resize, shape masks, format conversion.

A `Recipe` describes the whole pipeline so the same settings can be applied to
one file in the editor or to thousands in a batch.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .media import NO_WINDOW, find_tool, get_info, kind_of

RESIZE_MODES = {
    "fill": "Заполнить (обрезать лишнее)",
    "fit_pad": "Вписать с полями",
    "fit_blur": "Вписать на размытом фоне",
    "fit": "Вписать (без полей)",
    "stretch": "Растянуть",
}
SHAPES = {"none": "Без изменений", "rounded": "Скруглённые углы", "circle": "Круг", "ellipse": "Овал"}
FORMATS = {"keep": "Как у исходника", "jpg": "JPEG", "png": "PNG", "webp": "WebP"}


@dataclass
class Recipe:
    # crop as fractions of the (orientation-corrected) source: x, y, w, h in 0..1
    crop: tuple[float, float, float, float] | None = None
    rotate: int = 0  # 0/90/180/270 clockwise
    flip_h: bool = False
    flip_v: bool = False
    width: int = 0  # 0 = no resize
    height: int = 0
    long_edge: int = 0  # alternative to width/height
    scale: float = 0.0  # alternative: percent of original, e.g. 50.0
    mode: str = "fill"
    pad_color: str = "#000000"
    shape: str = "none"
    corner_radius: int = 8  # percent of the short side for "rounded"
    fmt: str = "keep"
    quality: int = 92
    strip_meta: bool = False
    no_upscale: bool = False  # never enlarge small images
    # video only
    video_crf: int = 20
    video_trim: tuple[float, float] | None = None
    video_mute: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Recipe":
        r = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        if r.crop:
            r.crop = tuple(r.crop)
        if r.video_trim:
            r.video_trim = tuple(r.video_trim)
        return r


def _hex(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else (0, 0, 0)


def _target_size(w: int, h: int, r: Recipe) -> tuple[int, int] | None:
    if r.width and r.height:
        return r.width, r.height
    if r.long_edge:
        k = r.long_edge / max(w, h)
        return max(1, round(w * k)), max(1, round(h * k))
    if r.scale:
        return max(1, round(w * r.scale / 100)), max(1, round(h * r.scale / 100))
    if r.width:
        return r.width, max(1, round(h * r.width / w))
    if r.height:
        return max(1, round(w * r.height / h)), r.height
    return None


def apply_image(img: Image.Image, r: Recipe) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    # Orientation first, so the crop box refers to what the user sees in the editor.
    if r.rotate:
        img = img.rotate(-r.rotate, expand=True)
    if r.flip_h:
        img = ImageOps.mirror(img)
    if r.flip_v:
        img = ImageOps.flip(img)
    if r.crop:
        x, y, w, h = r.crop
        W, H = img.size
        box = (round(x * W), round(y * H), round((x + w) * W), round((y + h) * H))
        img = img.crop(box)

    size = _target_size(*img.size, r)
    if size:
        tw, th = size
        if r.no_upscale and (tw > img.width and th > img.height) and r.mode in ("fit", "stretch"):
            pass
        elif r.mode == "stretch":
            img = img.resize((tw, th), Image.LANCZOS)
        elif r.mode == "fit":
            img = ImageOps.contain(img, (tw, th), Image.LANCZOS)
        elif r.mode == "fill":
            img = ImageOps.fit(img, (tw, th), Image.LANCZOS)
        elif r.mode in ("fit_pad", "fit_blur"):
            inner = ImageOps.contain(img, (tw, th), Image.LANCZOS)
            if r.mode == "fit_blur":
                bg = ImageOps.fit(img.convert("RGB"), (tw, th), Image.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(max(tw, th) / 30))
                bg = Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)), 0.25)
            else:
                bg = Image.new("RGB", (tw, th), _hex(r.pad_color))
            if inner.mode == "RGBA":
                bg = bg.convert("RGBA")
            bg.paste(inner, ((tw - inner.width) // 2, (th - inner.height) // 2), inner if inner.mode == "RGBA" else None)
            img = bg

    if r.shape != "none":
        img = apply_shape(img, r.shape, r.corner_radius)
    return img


def apply_shape(img: Image.Image, shape: str, radius_pct: int = 8) -> Image.Image:
    """Mask the image into a shape (transparent outside). Supersampled for smooth edges."""
    w, h = img.size
    ss = 4
    mask = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(mask)
    if shape == "circle":
        s = min(w, h)
        img = ImageOps.fit(img, (s, s), Image.LANCZOS)
        w = h = s
        mask = Image.new("L", (s * ss, s * ss), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, s * ss - 1, s * ss - 1), fill=255)
    elif shape == "ellipse":
        d.ellipse((0, 0, w * ss - 1, h * ss - 1), fill=255)
    elif shape == "rounded":
        rad = int(min(w, h) * radius_pct / 100) * ss
        d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=rad, fill=255)
    else:
        return img
    mask = mask.resize((w, h), Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def output_path(src: Path, out_dir: Path | None, suffix: str, r: Recipe) -> Path:
    ext = src.suffix.lower()
    if kind_of(src) == "image":
        if r.fmt != "keep":
            ext = "." + r.fmt
        elif r.shape != "none" and ext in (".jpg", ".jpeg", ".bmp"):
            ext = ".png"  # transparency needs an alpha-capable format
        elif ext in (".heic", ".heif", ".tif", ".tiff", ".bmp"):
            ext = ".jpg"
    else:
        ext = ".mp4"
    folder = out_dir or src.parent
    dst = folder / f"{src.stem}{suffix}{ext}"
    i = 1
    while dst.exists():
        dst = folder / f"{src.stem}{suffix} ({i}){ext}"
        i += 1
    return dst


def save_image(img: Image.Image, dst: Path, r: Recipe, src_img: Image.Image | None = None) -> None:
    ext = dst.suffix.lower()
    params: dict = {}
    if ext in (".jpg", ".jpeg"):
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, _hex(r.pad_color))
            bg.paste(img, mask=img.split()[3])
            img = bg
        params.update(quality=r.quality, optimize=True, progressive=True)
    elif ext == ".webp":
        params.update(quality=r.quality, method=5)
    elif ext == ".png":
        params.update(optimize=True)
    if src_img is not None and not r.strip_meta:
        exif = src_img.getexif()
        if 274 in exif:
            exif[274] = 1  # pixels are already rotated
        if len(exif):
            params["exif"] = exif.tobytes()
        if src_img.info.get("icc_profile"):
            params["icc_profile"] = src_img.info["icc_profile"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, **params)


def process_image(src: Path, dst: Path, r: Recipe) -> Path:
    with Image.open(src) as im:
        out = apply_image(im, r)
        save_image(out, dst, r, src_img=im)
    return dst


def video_filters(src_w: int, src_h: int, r: Recipe) -> list[str]:
    vf: list[str] = []
    w, h = src_w, src_h
    rot = {90: "transpose=1", 180: "transpose=1,transpose=1", 270: "transpose=2"}.get(r.rotate)
    if rot:
        vf.append(rot)
        if r.rotate in (90, 270):
            w, h = h, w
    if r.flip_h:
        vf.append("hflip")
    if r.flip_v:
        vf.append("vflip")
    if r.crop:
        x, y, cw, ch = r.crop
        cw_px, ch_px = int(cw * w) // 2 * 2, int(ch * h) // 2 * 2
        vf.append(f"crop={cw_px}:{ch_px}:{int(x * w)}:{int(y * h)}")
        w, h = cw_px, ch_px
    size = _target_size(w, h, r)
    if size:
        tw, th = (size[0] // 2 * 2, size[1] // 2 * 2)
        if r.mode == "stretch":
            vf.append(f"scale={tw}:{th}")
        elif r.mode == "fit":
            vf.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2")
        elif r.mode == "fill":
            vf.append(f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}")
        elif r.mode == "fit_pad":
            vf.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                      f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color={r.pad_color}")
        elif r.mode == "fit_blur":
            vf.append(f"split[a][b];[a]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},"
                      f"boxblur=20:2[bg];[b]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
                      f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    vf.append("setsar=1")
    return vf


def process_video(src: Path, dst: Path, r: Recipe, progress=None, use_gpu: bool = True) -> Path:
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg не найден. Установите ffmpeg или положите ffmpeg.exe в папку tools.")
    info = get_info(src)
    vf = video_filters(info.width or 1920, info.height or 1080, r)
    args = [ffmpeg, "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    if r.video_trim:
        args += ["-ss", str(r.video_trim[0])]
    args += ["-i", str(src)]
    if r.video_trim:
        args += ["-t", str(max(0.1, r.video_trim[1] - r.video_trim[0]))]
    args += ["-filter_complex" if "[" in ";".join(vf) else "-vf", ",".join(vf)]
    encoder = ["-c:v", "libx264", "-preset", "medium", "-crf", str(r.video_crf), "-pix_fmt", "yuv420p"]
    if use_gpu and _has_nvenc(ffmpeg):
        encoder = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(r.video_crf), "-pix_fmt", "yuv420p"]
    args += encoder
    args += ["-an"] if r.video_mute else ["-c:a", "aac", "-b:a", "192k"]
    args += ["-map_metadata", "-1"] if r.strip_meta else ["-map_metadata", "0"]
    args += ["-movflags", "+faststart", str(dst)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    total = (r.video_trim[1] - r.video_trim[0]) if r.video_trim else (info.duration or 0)
    run_ffmpeg(args, total, progress)
    return dst


_NVENC: bool | None = None


def _has_nvenc(ffmpeg: str) -> bool:
    global _NVENC
    if _NVENC is None:
        try:
            res = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                                  "-c:v", "h264_nvenc", "-f", "null", "-"],
                                 capture_output=True, timeout=20, creationflags=NO_WINDOW)
            _NVENC = res.returncode == 0
        except Exception:
            _NVENC = False
    return _NVENC


def run_ffmpeg(args: list[str], total_sec: float, progress=None) -> None:
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            creationflags=NO_WINDOW, encoding="utf-8", errors="ignore")
    for line in proc.stdout:  # type: ignore[union-attr]
        if progress and line.startswith("out_time_us=") and total_sec:
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1e6 / total_sec))
            except ValueError:
                pass
    err = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(err.strip() or "ffmpeg завершился с ошибкой")


def process(src: Path, dst: Path, r: Recipe, progress=None) -> Path:
    if kind_of(src) == "video":
        return process_video(src, dst, r, progress)
    return process_image(src, dst, r)
