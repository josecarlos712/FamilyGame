"""Blueprint every question type must follow.

A question type lives in its own folder under ``question_types/<name>/`` and
contains:

* ``type.py``  – a subclass of :class:`QuestionType` (this file's blueprint).
* ``tv.js``    – ES module exporting ``renderTV(canvas, question, ctx)``.
* ``phone.js`` – ES module exporting ``renderPhone(canvas, question, ctx)``.
* ``style.css`` and any other asset (optional).

The engine never knows how a type works internally: it only calls the methods
below. Copy ``question_types/_plantilla`` to start a new type.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any, ClassVar, Mapping


class QuestionFormatError(ValueError):
    """Raised when a question in a file is malformed."""


class AnswerError(ValueError):
    """Raised when a player's submitted answer is not valid for the question."""


@dataclass(frozen=True)
class Environment:
    """What the running server can offer to question types.

    Attributes:
        internet: Whether the server could reach the internet at startup.
        google_maps_api_key: Key for the Google Maps JavaScript API ("" if none).
    """

    internet: bool = True
    google_maps_api_key: str = ""


@dataclass(frozen=True)
class Evaluation:
    """Result of checking one answer.

    Attributes:
        correct: Whether the answer counts as good.
        closeness: 0..1, how close the answer was (1 = perfect). Used to rank
            players in tie-breaks, also when nobody is correct.
        detail: Short human text shown to the player ("A 12 km del punto").
    """

    correct: bool
    closeness: float = 0.0
    detail: str = ""


DIFFICULTY_POINTS = {1: 100, 2: 150, 3: 200}


class FieldReader:
    """Reads and validates fields of a raw question table with clear errors."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = raw
        self.used: set[str] = set()

    def has(self, key: str) -> bool:
        return key in self.raw

    def get(self, key: str, default: Any = None) -> Any:
        self.used.add(key)
        return self.raw.get(key, default)

    def text(self, key: str, default: str | None = None, max_len: int = 400) -> str:
        """Return a non-empty string field."""
        value = self.get(key, default)
        if value is None:
            raise QuestionFormatError(f"falta el campo «{key}»")
        if not isinstance(value, str):
            raise QuestionFormatError(f"«{key}» debe ser un texto entre comillas")
        value = value.strip()
        if not value and default is None:
            raise QuestionFormatError(f"«{key}» está vacío")
        if len(value) > max_len:
            raise QuestionFormatError(f"«{key}» es demasiado largo (máx. {max_len})")
        return value

    def number(
        self,
        key: str,
        default: float | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        """Return a numeric field, optionally bounded."""
        value = self.get(key, default)
        if value is None:
            raise QuestionFormatError(f"falta el campo numérico «{key}»")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise QuestionFormatError(f"«{key}» debe ser un número (sin comillas)")
        value = float(value)
        if not math.isfinite(value):
            raise QuestionFormatError(f"«{key}» no es un número válido")
        if minimum is not None and value < minimum:
            raise QuestionFormatError(f"«{key}» debe ser ≥ {minimum:g}")
        if maximum is not None and value > maximum:
            raise QuestionFormatError(f"«{key}» debe ser ≤ {maximum:g}")
        return value

    def integer(
        self,
        key: str,
        default: int | None = None,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        """Return an integer field, optionally bounded."""
        value = self.number(key, default, minimum, maximum)
        if not value.is_integer():
            raise QuestionFormatError(f"«{key}» debe ser un número entero")
        return int(value)

    def boolean(self, key: str, default: bool) -> bool:
        """Return a true/false field."""
        value = self.get(key, default)
        if not isinstance(value, bool):
            raise QuestionFormatError(f"«{key}» debe ser true o false")
        return value

    def choice(self, key: str, options: tuple[str, ...], default: str) -> str:
        """Return a text field restricted to ``options``."""
        value = self.text(key, default).lower()
        if value not in options:
            raise QuestionFormatError(f"«{key}» debe ser uno de: {', '.join(options)}")
        return value

    def unknown(self) -> list[str]:
        """Keys present in the table that nobody read."""
        return sorted(k for k in self.raw if k not in self.used)


class QuestionType(ABC):
    """Base class (blueprint) for every kind of question.

    Subclasses set the class attributes and override the abstract methods.
    Methods receive ``state``: a dict created by :meth:`prepare` each time the
    question is asked, so a question object can be reused between games
    (e.g. to shuffle options differently every time).

    Common fields read here for every type:
        enunciado (str, required), tiempo (seconds), lectura (seconds before
        answers open), dificultad (1-3), puntos (base points), explicacion,
        imagen (path relative to the questions folder), id.
    """

    type_id: ClassVar[str] = ""
    """Value of ``tipo`` in the questions file."""
    aliases: ClassVar[tuple[str, ...]] = ()
    display_name: ClassVar[str] = ""
    default_time: ClassVar[int] = 20
    requires_internet: ClassVar[bool] = False
    tiebreak_priority: ClassVar[int] = 0
    """Higher = preferred for sudden-death tie-breaks (closest-wins types)."""
    assets_dir: ClassVar[Path | None] = None
    """Set by the registry: folder holding tv.js / phone.js / style.css."""

    MIN_TIME: ClassVar[int] = 2
    MAX_TIME: ClassVar[int] = 300

    def __init__(self, raw: Mapping[str, Any], key: str = "") -> None:
        """Validate the raw table from the file.

        Args:
            raw: The ``[[pregunta]]`` table as read from TOML.
            key: Stable identifier (category + hash) assigned by the loader.

        Raises:
            QuestionFormatError: If any field is missing or invalid.
        """
        fields = FieldReader(raw)
        fields.get("tipo")
        self.key = key
        self.prompt = fields.text("enunciado", max_len=300)
        self.time_limit = fields.integer(
            "tiempo", self.default_time, self.MIN_TIME, self.MAX_TIME
        )
        default_read = round(min(6.0, max(2.0, 1.5 + len(self.prompt) / 25)), 1)
        self.read_time = fields.number("lectura", default_read, 0, 30)
        self.difficulty = fields.integer("dificultad", 1, 1, 3)
        self.base_points = fields.integer(
            "puntos", DIFFICULTY_POINTS[self.difficulty], 0, 10000
        )
        self.explanation = fields.text("explicacion", "", max_len=400)
        self.image = fields.text("imagen", "", max_len=200)
        if self.image and (".." in self.image or self.image.startswith(("/", "\\"))):
            raise QuestionFormatError("«imagen» debe ser una ruta dentro de la carpeta preguntas")
        explicit_id = fields.get("id")
        if explicit_id is not None:
            self.key = f"{key.split(':', 1)[0]}:{explicit_id}"
        self.parse(fields)
        self.warnings = [f"campo desconocido «{k}» (se ignora)" for k in fields.unknown()]

    # ----- methods each type overrides -------------------------------------------

    @abstractmethod
    def parse(self, fields: FieldReader) -> None:
        """Read and validate the type-specific fields.

        Raises:
            QuestionFormatError: On invalid data.
        """

    def prepare(self, rng: Random) -> dict[str, Any]:
        """Create per-ask state (shuffles, random picks). Default: none."""
        return {}

    @abstractmethod
    def public_data(self, state: dict[str, Any]) -> dict[str, Any]:
        """Type-specific data sent to the TV and phones. Must NOT leak the answer."""

    @abstractmethod
    def normalize_answer(self, raw: Any, state: dict[str, Any]) -> Any:
        """Validate a phone's answer and convert it to the internal form.

        Raises:
            AnswerError: If ``raw`` is not a valid answer.
        """

    @abstractmethod
    def evaluate(self, answer: Any, state: dict[str, Any]) -> Evaluation:
        """Decide whether a normalized answer is good."""

    @abstractmethod
    def solution_data(self, state: dict[str, Any]) -> dict[str, Any]:
        """Data revealing the correct answer (sent after time is up)."""

    def answer_for_display(self, answer: Any, state: dict[str, Any]) -> Any:
        """How a player's answer is shown on the TV at reveal time."""
        return answer

    def is_available(self, env: Environment) -> tuple[bool, str]:
        """Whether this question can be asked right now, and why not."""
        if self.requires_internet and not env.internet:
            return False, "necesita conexión a internet"
        return True, ""

    # ----- final helpers (do not override) ---------------------------------------

    def to_public(self, state: dict[str, Any]) -> dict[str, Any]:
        """Full public payload: common fields + :meth:`public_data`."""
        return {
            "key": self.key,
            "type": self.type_id,
            "prompt": self.prompt,
            "time": self.time_limit,
            "read": self.read_time,
            "difficulty": self.difficulty,
            "points": self.base_points,
            "image": f"/media/{self.image}" if self.image else "",
            "data": self.public_data(state),
        }

    def to_reveal(self, state: dict[str, Any]) -> dict[str, Any]:
        """Payload revealing the solution."""
        return {"explanation": self.explanation, "solution": self.solution_data(state)}


def snap_to_step(value: float, minimum: float, maximum: float, step: float) -> float:
    """Round ``value`` to the nearest slider step, staying within the limits."""
    steps = round((value - minimum) / step)
    decimals = max(0, -math.floor(math.log10(step))) if step < 1 else 0
    return round(min(maximum, max(minimum, minimum + steps * step)), decimals + 2)


def format_number(value: float, unit: str = "") -> str:
    """Format a number the Spanish way (1.234,5) with an optional unit."""
    if float(value).is_integer():
        text = f"{int(value):,}".replace(",", ".")
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
        text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {unit}".strip()
