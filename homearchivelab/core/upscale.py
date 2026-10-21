"""GPU upscaling via Real-ESRGAN (ncnn/Vulkan — works on NVIDIA, AMD and Intel GPUs).

The portable Real-ESRGAN build is downloaded on request into the app tools folder.
When it is missing, a CPU Lanczos + sharpen fallback is used.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageFilter

from .media import NO_WINDOW, find_tool, get_info, kind_of
from .settings import Settings
from .transform import run_ffmpeg

REALESRGAN_URL = ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
                  "realesrgan-ncnn-vulkan-20220424-windows.zip")

MODELS = {
    "realesrgan-x4plus": ("Фото (универсальная)", (4,)),
    "realesrnet-x4plus": ("Фото (мягкая, без артефактов)", (4,)),
    "realesrgan-x4plus-anime": ("Рисунки / аниме", (4,)),
    "realesr-animevideov3": ("Видео / анимация (быстрая)", (2, 3, 4)),
}


def engine_dir() -> Path:
    return Settings.tools_dir() / "realesrgan"


def engine_exe() -> Path | None:
    exe = engine_dir() / "realesrgan-ncnn-vulkan.exe"
    if exe.exists():
        return exe
    found = shutil.which("realesrgan-ncnn-vulkan")
    return Path(found) if found else None


def is_available() -> bool:
    return engine_exe() is not None


def download_engine(progress=None) -> Path:
    """Fetch the official portable Real-ESRGAN release from GitHub."""
    with urllib.request.urlopen(REALESRGAN_URL, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        while chunk := resp.read(1 << 16):
            buf.write(chunk)
            if progress and total:
                progress(buf.tell() / total)
    target = engine_dir()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(buf) as zf:
        for member in zf.namelist():
            # the archive may or may not have a top-level folder
            rel = Path(member)
            if rel.is_absolute() or ".." in rel.parts:
                continue
            out = target / rel
            if member.endswith("/"):
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(member))
    exe = next(target.rglob("realesrgan-ncnn-vulkan.exe"), None)
    if exe and exe.parent != target:  # flatten
        for item in exe.parent.iterdir():
            shutil.move(str(item), str(target / item.name))
    if not engine_exe():
        raise RuntimeError("В архиве не найден realesrgan-ncnn-vulkan.exe")
    return engine_exe()  # type: ignore[return-value]


def list_gpus() -> list[str]:
    """Best-effort GPU names (Windows)."""
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_VideoController).Name"],
                             capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        names = [n.strip() for n in res.stdout.splitlines() if n.strip()]
        return names or ["GPU 0"]
    except Exception:
        return ["GPU 0"]


def _run_engine(src: Path, dst: Path, scale: int, model: str, gpu: int, tile: int = 0) -> None:
    exe = engine_exe()
    if not exe:
        raise RuntimeError("Real-ESRGAN не установлен")
    allowed = MODELS.get(model, ("", (4,)))[1]
    native = scale if scale in allowed else max(allowed)
    args = [str(exe), "-i", str(src), "-o", str(dst), "-n", model, "-s", str(native),
            "-g", str(gpu), "-m", str(exe.parent / "models"), "-f", "png"]
    if tile:
        args += ["-t", str(tile)]
    res = subprocess.run(args, capture_output=True, text=True, cwd=exe.parent,
                         creationflags=NO_WINDOW, encoding="utf-8", errors="ignore")
    if res.returncode != 0 or not dst.exists():
        raise RuntimeError((res.stderr or res.stdout or "Real-ESRGAN error").strip()[-500:])


def upscale_image(src: Path, dst: Path, scale: int = 4, model: str = "realesrgan-x4plus",
                  gpu: int = 0, force_cpu: bool = False) -> Path:
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        from PIL import ImageOps

        im = ImageOps.exif_transpose(im)
        target = (im.width * scale, im.height * scale)
        if force_cpu or not is_available():
            out = im.convert("RGB").resize(target, Image.LANCZOS)
            out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
        else:
            with tempfile.TemporaryDirectory() as td:
                tmp_in, tmp_out = Path(td) / "in.png", Path(td) / "out.png"
                im.convert("RGBA" if "A" in im.getbands() else "RGB").save(tmp_in)
                _run_engine(tmp_in, tmp_out, scale, model, gpu)
                with Image.open(tmp_out) as res:
                    out = res.copy()
            if out.size != target:
                out = out.resize(target, Image.LANCZOS)
        params = {"quality": 95} if dst.suffix.lower() in (".jpg", ".jpeg", ".webp") else {}
        if dst.suffix.lower() in (".jpg", ".jpeg") and out.mode == "RGBA":
            out = out.convert("RGB")
        out.save(dst, **params)
    return dst


def upscale_video(src: Path, dst: Path, scale: int = 2, model: str = "realesr-animevideov3",
                  gpu: int = 0, progress=None, cancelled=lambda: False) -> Path:
    """Frame-by-frame upscale: extract → Real-ESRGAN on folder → re-encode with original audio."""
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg не найден")
    if not is_available():
        raise RuntimeError("Для видео нужен Real-ESRGAN (GPU). Установите его на вкладке «Апскейл».")
    info = get_info(src)
    fps = info.fps or 30
    with tempfile.TemporaryDirectory(prefix="hal_up_") as td:
        frames, out_frames = Path(td) / "in", Path(td) / "out"
        frames.mkdir()
        out_frames.mkdir()
        if progress:
            progress(0.02, "Извлечение кадров…")
        subprocess.run([ffmpeg, "-v", "error", "-i", str(src), "-vsync", "0", str(frames / "%08d.png")],
                       check=True, capture_output=True, creationflags=NO_WINDOW)
        if cancelled():
            raise RuntimeError("Отменено")
        if progress:
            progress(0.1, "Апскейл кадров на GPU…")
        exe = engine_exe()
        allowed = MODELS.get(model, ("", (4,)))[1]
        native = scale if scale in allowed else max(allowed)
        total = len(list(frames.glob("*.png")))
        proc = subprocess.Popen([str(exe), "-i", str(frames), "-o", str(out_frames), "-n", model,
                                 "-s", str(native), "-g", str(gpu), "-m", str(exe.parent / "models"),
                                 "-f", "png"], cwd=exe.parent, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        import time

        while proc.poll() is None:
            if cancelled():
                proc.kill()
                raise RuntimeError("Отменено")
            done = len(list(out_frames.glob("*.png")))
            if progress and total:
                progress(0.1 + 0.8 * done / total, f"Кадр {done}/{total}")
            time.sleep(0.5)
        if proc.returncode != 0:
            raise RuntimeError("Real-ESRGAN завершился с ошибкой")
        if progress:
            progress(0.9, "Сборка видео…")
        tw, th = (info.width or 0) * scale // 2 * 2, (info.height or 0) * scale // 2 * 2
        args = [ffmpeg, "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
                "-framerate", f"{fps}", "-i", str(out_frames / "%08d.png"), "-i", str(src),
                "-map", "0:v", "-map", "1:a?", "-c:a", "copy",
                "-vf", f"scale={tw}:{th}" if tw and th else "null",
                "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(dst)]
        dst.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(args, info.duration or 0, (lambda f: progress(0.9 + 0.1 * f, "Сборка видео…")) if progress else None)
    return dst


def upscale(src: Path, dst: Path, scale: int, model: str, gpu: int, progress=None, cancelled=lambda: False) -> Path:
    if kind_of(Path(src)) == "video":
        return upscale_video(src, dst, scale, model, gpu, progress, cancelled)
    return upscale_image(src, dst, scale, model, gpu)
