"""Building blocks shared by the text parser and the per-type ``editor.py`` hooks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class FormatoError(ValueError):
    """A line of the editor text cannot be understood."""


@dataclass
class Option:
    """One ``- texto`` / ``+ texto`` line.

    Attributes:
        text: Option text.
        correct: True when the line started with ``+`` or ``*``.
        line: 1-based line number in the pasted text.
    """

    text: str
    correct: bool
    line: int


@dataclass
class Block:
    """One question as written in the editor (a paragraph of text).

    Attributes:
        line: First line of the block (1-based).
        end: Last line of the block (1-based).
        source: The original lines, to give back the ones that could not be added.
        type_id: Question type that applies to the block.
        values: Normalized key -> value lines (``enunciado`` holds the prompt).
        options: Option lines in order.
        errors: Problems found while splitting the block into fields.
    """

    line: int
    end: int
    source: list[str]
    type_id: str = "test"
    values: dict[str, list[str]] = field(default_factory=dict)
    options: list[Option] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def has(self, key: str) -> bool:
        """Whether the block wrote ``key``."""
        return key in self.values

    def text(self, key: str, joiner: str = " ") -> str:
        """Value of ``key`` with its lines joined (``""`` if missing)."""
        return joiner.join(part.strip() for part in self.values.get(key, [])).strip()

    def lines(self, key: str) -> list[str]:
        """Non-empty value lines of ``key``."""
        return [part.strip() for part in self.values.get(key, []) if part.strip()]


_NUMBER = re.compile(r"^([-+−]?[\d.,  ]*\d)\s*(.*)$")


def number(text: str, key: str, units: dict[str, float] | None = None) -> int | float:
    """Read a number written the Spanish or the English way.

    ``1969``, ``-3,5``, ``36.6``, ``1 000 000``, ``1.000.000`` and ``1.234,5`` are
    all accepted. With ``units`` a trailing unit multiplies the value
    (``{"km": 1000, "m": 1}``); without it any trailing text is an error.

    Args:
        text: The value as written.
        key: Field name, for error messages.
        units: Accepted units and their multiplier ("" means no unit).

    Returns:
        An ``int`` when the value is whole, otherwise a ``float``.

    Raises:
        FormatoError: If the text is not a number.
    """
    raw = text.strip()
    match = _NUMBER.match(raw)
    if not match:
        raise FormatoError(f"«{key}» debe ser un número (está «{raw}»)")
    digits, unit = match.group(1), match.group(2).strip()
    digits = digits.replace("−", "-").replace(" ", "").replace(" ", "")
    if "," in digits and "." in digits:
        digits = digits.replace(".", "").replace(",", ".")
    elif digits.count(".") > 1:
        digits = digits.replace(".", "")
    elif digits.count(",") > 1:
        digits = digits.replace(",", "")
    else:
        digits = digits.replace(",", ".")
    try:
        value = float(digits)
    except ValueError as exc:
        raise FormatoError(f"«{key}» debe ser un número (está «{raw}»)") from exc
    if unit:
        factors = {k.casefold(): v for k, v in (units or {}).items()}
        if unit.casefold() not in factors:
            accepted = ", ".join(u for u in (units or {}) if u)
            hint = f" (unidades válidas: {accepted})" if accepted else ""
            raise FormatoError(f"«{key}»: no entiendo «{unit}» tras el número{hint}")
        value *= factors[unit.casefold()]
    return int(value) if value.is_integer() else value


_BOOLS = {
    "si": True, "sí": True, "true": True, "verdadero": True, "1": True, "s": True,
    "no": False, "false": False, "falso": False, "0": False, "n": False,
}


def boolean(text: str, key: str) -> bool:
    """``sí``/``no`` (also true/false, 1/0)."""
    value = _BOOLS.get(text.strip().casefold())
    if value is None:
        raise FormatoError(f"«{key}» debe ser sí o no (está «{text.strip()}»)")
    return value


_PAIR = re.compile(
    r"^\s*(.+?)\s*(?:\.\.|…|–|—|(?<=\d)\s*-|\sa\s|\shasta\s)\s*(.+?)\s*$", re.IGNORECASE
)


def number_pair(text: str, key: str) -> list[int | float]:
    """``1936 - 1939``, ``1936 a 1939``, ``36,1..37,2`` -> ``[1936, 1939]``."""
    match = _PAIR.match(text.strip())
    if not match:
        raise FormatoError(f"«{key}» debe ser «desde - hasta», p. ej. «1936 - 1939»")
    return [number(match.group(1), key), number(match.group(2), key)]


_COORD = re.compile(r"^\s*\(?\s*([-+]?\d+(?:\.\d+)?)\s*[,;\s]\s*([-+]?\d+(?:\.\d+)?)\s*\)?\s*$")


def coordinates(text: str, key: str) -> tuple[float, float]:
    """``48.8584, 2.2945`` (como lo copia Google Maps) -> ``(48.8584, 2.2945)``."""
    match = _COORD.match(text.strip())
    if not match:
        raise FormatoError(
            f"«{key}» debe ser «latitud, longitud» con punto decimal, p. ej. «48.8584, 2.2945»"
        )
    lat, lng = float(match.group(1)), float(match.group(2))
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise FormatoError(f"«{key}»: latitud entre -90 y 90 y longitud entre -180 y 180")
    return lat, lng


def percent(text: str, key: str) -> int | float:
    """``50`` or ``50 %`` -> ``50``."""
    return number(text, key, {"%": 1, "": 1})
