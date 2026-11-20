"""Formato del editor de preguntas para el tipo «conoces» («¿Lo conoces?»)."""

from __future__ import annotations

from typing import Any

from familygame.editor.values import Block, FormatoError, boolean

KEYS = ("barajar",)
OPTIONS = True

HELP = """
Primera línea: el enunciado, en tercera persona y sin nombres («¿Qué plato prefiere?»).
Una línea «- opción» por cada opción (de 2 a 6). No hay correcta: la elige el jugador.
barajar: no        → mantiene el orden
"""

EXAMPLE = """
¿Qué plato prefiere?
- Paella
- Tortilla de patatas
- Cocido
- Pizza

¿Qué plan de domingo elegiría?
- Sofá y peli
- Comida familiar
- Excursión al campo
- Dormir hasta tarde
"""


def to_raw(block: Block, raw: dict[str, Any]) -> None:
    """``-`` lines -> ``opciones``."""
    if not block.options:
        raise FormatoError("faltan las opciones: una línea «- opción» por cada una")
    if any(o.correct for o in block.options):
        raise FormatoError("«¿Lo conoces?» no tiene opción correcta: usa «-» en todas")
    raw["opciones"] = [o.text for o in block.options]
    if block.has("barajar"):
        raw["barajar"] = boolean(block.text("barajar"), "barajar")
