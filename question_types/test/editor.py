"""Formato del editor de preguntas para el tipo «test»."""

from __future__ import annotations

from typing import Any

from familygame.editor.values import Block, FormatoError, boolean, number

KEYS = ("correcta", "barajar")
OPTIONS = True

HELP = """
Primera línea: el enunciado.
Una línea por opción (de 2 a 8): «- opción» las falsas y «+ opción» la correcta.
barajar: no        → mantiene el orden (Verdadero/Falso, «Todas las anteriores»)
"""

EXAMPLE = """
¿En qué año llegó Colón a América?
- 1453
+ 1492
- 1512
- 1588
tiempo: 10
explicacion: Llegó a la isla de Guanahaní el 12 de octubre.

¿El Sol es una estrella?
+ Verdadero
- Falso
barajar: no
"""


def to_raw(block: Block, raw: dict[str, Any]) -> None:
    """``- / +`` lines -> ``opciones`` and ``correcta``."""
    if not block.options:
        raise FormatoError("faltan las opciones: una línea «- opción» por cada una y «+ opción» la correcta")
    raw["opciones"] = [o.text for o in block.options]
    marked = [o.text for o in block.options if o.correct]
    if block.has("correcta"):
        if marked:
            raise FormatoError("marca la correcta con «+» o con «correcta:», no con las dos")
        written = block.text("correcta")
        try:
            raw["correcta"] = int(number(written, "correcta"))
        except FormatoError:
            raw["correcta"] = written
    elif len(marked) != 1:
        raise FormatoError(f"marca con «+» exactamente una opción correcta (hay {len(marked)})")
    else:
        raw["correcta"] = marked[0]
    if block.has("barajar"):
        raw["barajar"] = boolean(block.text("barajar"), "barajar")
