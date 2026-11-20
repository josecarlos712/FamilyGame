"""Formato del editor de preguntas para el tipo «mapa»."""

from __future__ import annotations

import re
from typing import Any

from familygame.editor.values import Block, FormatoError, coordinates, number

KEYS = ("punto", "radio", "zona", "vista")
ALIASES = {"respuesta": "punto", "lugar": "punto", "zoom": "vista"}

HELP = """
Primera línea: el enunciado («Señala dónde está la Torre Eiffel»).
Respuesta con un punto y un radio…
  punto: 48.8584, 2.2945     → latitud, longitud (clic derecho en Google Maps las copia así)
  radio: 25 km               → «km» o «m» (sin unidad: metros)
…o con una zona (polígono de 3 o más puntos), un punto por línea:
  zona:
  39.96, 2.80
  39.92, 3.20
  39.30, 3.20
vista: 46, 2, 5              → opcional: latitud, longitud y zoom (1-20) iniciales
Las coordenadas llevan punto decimal y se separan con coma.
"""

EXAMPLE = """
Señala dónde está la Torre Eiffel
punto: 48.8584, 2.2945
radio: 25 km
vista: 46, 2, 5

Toca dentro de la isla de Mallorca
zona:
39.96, 2.80
39.92, 3.20
39.80, 3.50
39.30, 3.20
39.35, 2.40
39.70, 2.30
vista: 40, 2, 6
"""

_VIEW = re.compile(r"^(.+?)\s*[,;]\s*(?:zoom\s*)?(\d+(?:[.,]\d+)?)\s*$", re.IGNORECASE)


def to_raw(block: Block, raw: dict[str, Any]) -> None:
    """Fill ``respuesta`` + ``radio`` or ``zona``, and ``vista``."""
    if not block.has("punto") and not block.has("zona"):
        raise FormatoError("falta la respuesta: «punto: lat, lng» + «radio:», o una «zona:»")
    if block.has("punto"):
        lat, lng = coordinates(block.text("punto"), "punto")
        raw["respuesta"] = {"lat": lat, "lng": lng}
        if not block.has("radio"):
            raise FormatoError("con «punto:» hace falta «radio:», p. ej. «radio: 25 km»")
        raw["radio"] = number(block.text("radio"), "radio", {"": 1, "m": 1, "km": 1000})
    elif block.has("radio"):
        raise FormatoError("«radio:» solo sirve con «punto:»")
    if block.has("zona"):
        parts = [p for line in block.lines("zona") for p in line.split(";") if p.strip()]
        raw["zona"] = [list(coordinates(p, "zona")) for p in parts]
    if block.has("vista"):
        match = _VIEW.match(block.text("vista"))
        if not match:
            raise FormatoError("«vista» debe ser «latitud, longitud, zoom», p. ej. «46, 2, 5»")
        lat, lng = coordinates(match.group(1), "vista")
        raw["vista"] = {"lat": lat, "lng": lng, "zoom": number(match.group(2), "zoom de la vista")}
