"""Formato del editor de preguntas para el tipo «slider» (un número)."""

from __future__ import annotations

from typing import Any

from familygame.editor.values import Block, FormatoError, number, number_pair

KEYS = ("respuesta", "escala", "min", "max", "paso", "unidad", "tolerancia", "inicio")
ALIASES = {"minimo": "min", "maximo": "max", "margen": "tolerancia", "solucion": "respuesta"}

HELP = """
Primera línea: el enunciado.
respuesta: 1969              → el valor correcto
escala: 1950 - 2000          → mínimo y máximo del slider (o «min:» y «max:» por separado)
tolerancia: 2                → vale 1967..1971; «tolerancia: 10%» = ±10 % de la respuesta
paso: 0,1                    → opcional (por defecto 1)
unidad: km                   → opcional, texto tras el número
inicio: 1975                 → opcional, dónde empieza el selector
Decimales con coma o punto; no uses punto de miles (1000000 o 1 000 000).
"""

EXAMPLE = """
¿En qué año llegó el ser humano a la Luna?
respuesta: 1969
escala: 1950 - 2000
tolerancia: 2

¿Cuántos metros mide el Everest?
respuesta: 8849
escala: 5000 - 10000
paso: 10
unidad: m
tolerancia: 3%
"""


def to_raw(block: Block, raw: dict[str, Any]) -> None:
    """Fill ``min``, ``max``, ``paso``, ``unidad``, ``respuesta``, ``tolerancia``…"""
    if block.has("escala"):
        if block.has("min") or block.has("max"):
            raise FormatoError("usa «escala: desde - hasta» o «min:»/«max:», no las dos")
        raw["min"], raw["max"] = number_pair(block.text("escala"), "escala")
    else:
        if not block.has("min") or not block.has("max"):
            raise FormatoError("falta la escala del slider: «escala: 1950 - 2000»")
        raw["min"] = number(block.text("min"), "min")
        raw["max"] = number(block.text("max"), "max")
    if block.has("paso"):
        raw["paso"] = number(block.text("paso"), "paso")
    if block.has("unidad"):
        raw["unidad"] = block.text("unidad")
    if not block.has("respuesta"):
        raise FormatoError("falta «respuesta:» con el valor correcto")
    raw["respuesta"] = number(block.text("respuesta"), "respuesta")
    if block.has("tolerancia"):
        written = block.text("tolerancia").lstrip("±").strip()
        if written.endswith("%"):
            raw["tolerancia_pct"] = number(written[:-1], "tolerancia")
        else:
            raw["tolerancia"] = number(written, "tolerancia")
    if block.has("inicio"):
        raw["inicio"] = number(block.text("inicio"), "inicio")
