"""Minimal TOML writer for question tables (tomllib only reads)."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Mapping

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def value(item: Any) -> str:
    """Serialize one value: text, number, bool, list or inline table.

    Raises:
        TypeError: For values TOML cannot hold (None, NaN...).
    """
    if isinstance(item, bool):
        return "true" if item else "false"
    if isinstance(item, int):
        return str(item)
    if isinstance(item, float):
        if not math.isfinite(item):
            raise TypeError("TOML no admite NaN ni infinito")
        return str(int(item)) + ".0" if item.is_integer() else repr(item)
    if isinstance(item, str):
        return json.dumps(item, ensure_ascii=False)
    if isinstance(item, (list, tuple)):
        return "[" + ", ".join(value(v) for v in item) + "]"
    if isinstance(item, Mapping):
        return "{ " + ", ".join(f"{key(k)} = {value(v)}" for k, v in item.items()) + " }"
    raise TypeError(f"no se puede escribir {type(item).__name__} en TOML")


def key(name: str) -> str:
    """A bare key when possible, otherwise a quoted one."""
    return name if _BARE_KEY.match(name) else json.dumps(name, ensure_ascii=False)


def table(header: str, data: Mapping[str, Any]) -> str:
    """``[header]`` or ``[[header]]`` followed by ``key = value`` lines."""
    lines = [header]
    lines.extend(f"{key(k)} = {value(v)}" for k, v in data.items())
    return "\n".join(lines) + "\n"


def question(data: Mapping[str, Any]) -> str:
    """One ``[[pregunta]]`` block."""
    return table("[[pregunta]]", data)
