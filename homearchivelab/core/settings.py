"""Persistent JSON settings stored in %APPDATA%/HomeArchiveLab."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "library": "",
    "theme": "dark",
    "sort_pattern": "{year}/{month:02d} {month_name}",
    "sort_mode": "copy",
    "dedupe_threshold": 8,
    "jpeg_quality": 92,
    "upscale_model": "realesrgan-x4plus",
    "upscale_gpu": 0,
    "lan_port": 8765,
    "lan_pin": "",
    "lan_allow_upload": True,
    "device_name": os.environ.get("COMPUTERNAME", "Home Archive Lab"),
}


class Settings:
    _data: dict | None = None

    @staticmethod
    def app_dir() -> Path:
        base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
        d = base / "HomeArchiveLab"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def tools_dir(cls) -> Path:
        d = cls.app_dir() / "tools"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _file(cls) -> Path:
        return cls.app_dir() / "settings.json"

    @classmethod
    def _load(cls) -> dict:
        if cls._data is None:
            data = dict(DEFAULTS)
            try:
                data.update(json.loads(cls._file().read_text("utf-8")))
            except Exception:
                pass
            cls._data = data
        return cls._data

    @classmethod
    def get(cls, key: str, default=None):
        return cls._load().get(key, DEFAULTS.get(key, default))

    @classmethod
    def set(cls, key: str, value) -> None:
        cls._load()[key] = value
        cls._file().write_text(json.dumps(cls._data, ensure_ascii=False, indent=2), "utf-8")
