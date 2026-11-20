"""The party circuit: a ring of spaces every player moves around."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

START, NORMAL, EVENT, DUEL, STAR = "start", "normal", "event", "duel", "star"

BOARD_SIZE = 28
"""Perimeter of a 10 x 6 grid, drawn as a rectangle on the TV."""
STAR_COUNT, EVENT_COUNT, DUEL_COUNT = 4, 7, 3


@dataclass
class Board:
    """Ring of spaces; index 0 is the start."""

    spaces: list[str]

    @classmethod
    def generate(cls, rng: Random, size: int = BOARD_SIZE) -> Board:
        """Spread stars evenly, then scatter events and duels.

        Stars are never next to the start or to each other, so closing a
        category always takes a little luck.
        """
        spaces = [NORMAL] * size
        spaces[0] = START
        gap = size // STAR_COUNT
        offset = rng.randint(3, gap - 2)
        for i in range(STAR_COUNT):
            spaces[offset + i * gap] = STAR
        free = [i for i, s in enumerate(spaces) if s == NORMAL and i not in (1, size - 1)]
        rng.shuffle(free)
        for i in free[:EVENT_COUNT]:
            spaces[i] = EVENT
        for i in free[EVENT_COUNT : EVENT_COUNT + DUEL_COUNT]:
            spaces[i] = DUEL
        return cls(spaces)

    def __len__(self) -> int:
        return len(self.spaces)

    def path(self, start: int, steps: int) -> list[int]:
        """Positions visited when moving ``steps`` (negative = backwards)."""
        size = len(self.spaces)
        direction = 1 if steps >= 0 else -1
        return [(start + direction * i) % size for i in range(1, abs(steps) + 1)]

    def passes_start(self, start: int, steps: int) -> bool:
        """True if moving forward crosses or lands on the start."""
        return steps > 0 and start + steps >= len(self.spaces)
