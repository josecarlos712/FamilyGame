"""Choosing which question of a category to ask, avoiding repeats."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from random import Random
from typing import Callable

from familygame.categories import Category
from familygame.questions.base import QuestionType

log = logging.getLogger(__name__)


class QuestionHistory:
    """Remembers when each question was last asked, across games (JSON file).

    With ``path=None`` it only lives in memory (tests, or option disabled).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.seen: dict[str, float] = {}
        if path and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.seen = {str(k): float(v) for k, v in data.items()}
            except (OSError, ValueError, AttributeError) as exc:
                log.warning("Historial de preguntas ilegible (%s); se empieza de cero", exc)

    def mark(self, key: str, when: float) -> None:
        """Record that ``key`` was asked at ``when`` and persist."""
        self.seen[key] = when
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.seen), encoding="utf-8")
            except OSError as exc:
                log.warning("No se pudo guardar el historial: %s", exc)


def pick_question(
    category: Category,
    used: set[str],
    history: QuestionHistory,
    rng: Random,
    allowed: Callable[[QuestionType], bool] | None = None,
) -> QuestionType | None:
    """Pick a question never asked in this game.

    Among those, prefer ones never seen in previous games; if all were seen,
    pick among the third that was seen longest ago.

    Args:
        category: Where to pick from.
        used: Keys already asked in this game.
        history: When each question was last asked, across games.
        rng: Random source.
        allowed: Optional filter (e.g. no questions about a player when nobody chose).

    Returns:
        A question, or None if the category is exhausted for this game.
    """
    candidates = [q for q in category.questions if q.key not in used and (allowed is None or allowed(q))]
    if not candidates:
        return None
    unseen = [q for q in candidates if q.key not in history.seen]
    if unseen:
        return rng.choice(unseen)
    oldest = sorted(candidates, key=lambda q: history.seen[q.key])
    return rng.choice(oldest[: max(1, len(oldest) // 3)])
