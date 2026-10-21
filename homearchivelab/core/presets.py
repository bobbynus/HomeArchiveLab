"""Social network and common size presets."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    group: str
    name: str
    width: int
    height: int
    note: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} — {self.width}×{self.height}"

    @property
    def ratio(self) -> float:
        return self.width / self.height


PRESETS: list[Preset] = [
    Preset("Instagram", "Пост квадрат", 1080, 1080),
    Preset("Instagram", "Пост вертикальный 4:5", 1080, 1350),
    Preset("Instagram", "Пост 3:4", 1080, 1440, "новая сетка профиля"),
    Preset("Instagram", "Пост горизонтальный", 1080, 566),
    Preset("Instagram", "Stories / Reels", 1080, 1920),
    Preset("Instagram", "Аватар", 320, 320),
    Preset("TikTok", "Видео / фото", 1080, 1920),
    Preset("TikTok", "Аватар", 200, 200),
    Preset("YouTube", "Видео Full HD", 1920, 1080),
    Preset("YouTube", "Видео 4K", 3840, 2160),
    Preset("YouTube", "Shorts", 1080, 1920),
    Preset("YouTube", "Превью (thumbnail)", 1280, 720),
    Preset("YouTube", "Баннер канала", 2560, 1440),
    Preset("YouTube", "Аватар", 800, 800),
    Preset("VK", "Пост", 1080, 1080),
    Preset("VK", "Клипы / истории", 1080, 1920),
    Preset("VK", "Обложка сообщества", 1920, 768),
    Preset("VK", "Аватар", 400, 400),
    Preset("Telegram", "Аватар", 640, 640),
    Preset("Telegram", "Стикер", 512, 512),
    Preset("Telegram", "Пост с картинкой", 1280, 720),
    Preset("Facebook", "Пост", 1200, 630),
    Preset("Facebook", "Обложка", 851, 315),
    Preset("Facebook", "Stories", 1080, 1920),
    Preset("X (Twitter)", "Пост 16:9", 1600, 900),
    Preset("X (Twitter)", "Шапка профиля", 1500, 500),
    Preset("X (Twitter)", "Аватар", 400, 400),
    Preset("LinkedIn", "Пост", 1200, 627),
    Preset("LinkedIn", "Баннер", 1584, 396),
    Preset("Pinterest", "Пин 2:3", 1000, 1500),
    Preset("WhatsApp", "Статус", 1080, 1920),
    Preset("Печать", "10×15 см, 300 dpi", 1800, 1200),
    Preset("Печать", "13×18 см, 300 dpi", 2100, 1500),
    Preset("Печать", "A4, 300 dpi", 3508, 2480),
    Preset("Экран", "Full HD", 1920, 1080),
    Preset("Экран", "4K UHD", 3840, 2160),
    Preset("Экран", "Обои телефона", 1170, 2532),
]

# Aspect ratios for the free crop tool: label -> (w, h) or None for free.
ASPECTS = {
    "Свободно": None,
    "Оригинал": "orig",
    "1:1": (1, 1),
    "4:5": (4, 5),
    "3:4": (3, 4),
    "2:3": (2, 3),
    "9:16": (9, 16),
    "16:9": (16, 9),
    "3:2": (3, 2),
    "4:3": (4, 3),
    "21:9": (21, 9),
}


def groups() -> list[str]:
    seen: list[str] = []
    for p in PRESETS:
        if p.group not in seen:
            seen.append(p.group)
    return seen
