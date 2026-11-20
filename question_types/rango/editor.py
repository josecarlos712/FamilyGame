"""Formato del editor de preguntas para el tipo «rango» (doble slider)."""

from __future__ import annotations

from typing import Any

from familygame.editor.values import Block, FormatoError, number, number_pair, percent

KEYS = (
    "respuesta", "escala", "min", "max", "paso", "unidad",
    "criterio", "solape_min", "ancho_max", "margen",
)
ALIASES = {"minimo": "min", "maximo": "max", "solape": "solape_min", "ancho": "ancho_max", "solucion": "respuesta"}

HELP = """
Primera línea: el enunciado.
respuesta: 1936 - 1939       → el rango correcto (desde - hasta)
escala: 1900 - 1960          → mínimo y máximo del slider (o «min:» y «max:»)
criterio: solapar            → solapar (por defecto) · contener · coincidir
  solapar   → solape: 50%    (mínimo de intersección ÷ unión, por defecto 50 %)
  contener  → ancho: 20      (ancho máximo del rango del jugador, opcional)
  coincidir → margen: 1      (error permitido en cada extremo, por defecto 0)
paso: 0,1 · unidad: °C       → opcionales
"""

EXAMPLE = """
¿Entre qué años duró la Guerra Civil española?
respuesta: 1936 - 1939
escala: 1900 - 1960
criterio: coincidir
margen: 0

Marca la temperatura del cuerpo humano sano
respuesta: 36,1 - 37,2
escala: 30 - 45
paso: 0,1
unidad: °C
solape: 50%
"""


def to_raw(block: Block, raw: dict[str, Any]) -> None:
    """Fill ``min``, ``max``, ``respuesta`` and the scoring criterion."""
    if block.has("escala"):
        if block.has("min") or block.has("max"):
            raise FormatoError("usa «escala: desde - hasta» o «min:»/«max:», no las dos")
        raw["min"], raw["max"] = number_pair(block.text("escala"), "escala")
    else:
        if not block.has("min") or not block.has("max"):
            raise FormatoError("falta la escala del slider: «escala: 1900 - 1960»")
        raw["min"] = number(block.text("min"), "min")
        raw["max"] = number(block.text("max"), "max")
    if block.has("paso"):
        raw["paso"] = number(block.text("paso"), "paso")
    if block.has("unidad"):
        raw["unidad"] = block.text("unidad")
    if not block.has("respuesta"):
        raise FormatoError("falta «respuesta: desde - hasta» con el rango correcto")
    raw["respuesta"] = number_pair(block.text("respuesta"), "respuesta")
    if block.has("criterio"):
        raw["criterio"] = block.text("criterio").lower()
    if block.has("solape_min"):
        raw["solape_min"] = percent(block.text("solape_min"), "solape")
    if block.has("ancho_max"):
        raw["ancho_max"] = number(block.text("ancho_max"), "ancho")
    if block.has("margen"):
        raw["margen"] = number(block.text("margen").lstrip("±").strip(), "margen")
