"""Players, their colours and name rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

TV_BACKGROUND = "#14151c"
"""Darkest background the TV draws player names on."""

PALETTE: tuple[tuple[str, str], ...] = (
    ("#ff6b6b", "Rojo"),
    ("#ffa94d", "Naranja"),
    ("#ffd43b", "Amarillo"),
    ("#a9e34b", "Lima"),
    ("#51cf66", "Verde"),
    ("#3bc9db", "Turquesa"),
    ("#4dabf7", "Azul"),
    ("#9c8cff", "Violeta"),
    ("#e599f7", "Lila"),
    ("#f783ac", "Rosa"),
    ("#ced4da", "Plata"),
    ("#d9a066", "Canela"),
)
"""Fixed palette: every colour keeps ≥ 4.5:1 contrast on the TV background,
so names are always legible (no free colour picker)."""

PALETTE_COLORS = tuple(c for c, _ in PALETTE)
MAX_NAME = 16


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two #rrggbb colours."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_color_for(background: str) -> str:
    """Black or white, whichever reads better on ``background``."""
    return "#111318" if contrast_ratio(background, "#111318") >= contrast_ratio(background, "#ffffff") else "#ffffff"


def clean_name(raw: Any) -> str:
    """Trim, collapse spaces and drop control characters."""
    if not isinstance(raw, str):
        return ""
    text = "".join(ch for ch in raw if unicodedata.category(ch)[0] != "C")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_NAME].strip()


def name_key(name: str) -> str:
    """Comparison key: «Ána», «ana» and « ANA » are the same name."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch) and not ch.isspace())


@dataclass
class Player:
    """One participant, identified by ``id`` and reconnecting with ``token``."""

    id: str
    token: str
    name: str
    color: str
    avatar: dict[str, Any]
    connected: bool = True
    points: int = 0
    position: int = 0
    closed: list[str] = field(default_factory=list)
    progress: dict[str, int] = field(default_factory=dict)
    double_next: bool = False
    correct_count: int = 0
    asked_count: int = 0
    photo_version: int = 0
    asked: dict[str, int] = field(default_factory=dict)  # per category, this match
    right: dict[str, int] = field(default_factory=dict)

    def reset_scores(self) -> None:
        """Back to the start for a new game (profile is kept)."""
        self.asked = {}
        self.right = {}
        self.points = 0
        self.position = 0
        self.closed = []
        self.progress = {}
        self.double_next = False
        self.correct_count = 0
        self.asked_count = 0

    def public(self) -> dict[str, Any]:
        """Data any screen may show."""
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "textColor": text_color_for(self.color),
            "avatar": self.avatar,
            "connected": self.connected,
            "points": self.points,
            "position": self.position,
            "closed": list(self.closed),
            "progress": dict(self.progress),
            "double": self.double_next,
            "correct": self.correct_count,
            "asked": self.asked_count,
        }
