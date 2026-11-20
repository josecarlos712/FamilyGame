"""PLANTILLA del formato del editor de preguntas (opcional).

El editor (``editor.bat``) convierte texto plano en bloques ``[[pregunta]]``. Este
archivo dice cómo se escribe tu tipo. Sin él, el editor usa un formato genérico: cada
``clave: valor`` pasa tal cual y las líneas ``- opción`` van a ``opciones``.

El enunciado (primera línea) y los campos comunes (tiempo, lectura, dificultad,
puntos, explicacion, imagen, id) los lee el editor; aquí solo los propios del tipo.
Después, el editor valida el resultado con tu ``type.py``, así que no repitas aquí
sus comprobaciones: basta con convertir el texto al tipo de dato correcto.
"""

from __future__ import annotations

from typing import Any

from familygame.editor.values import Block, FormatoError

KEYS = ("respuesta",)  # claves que acepta este tipo (además de las comunes)
ALIASES = {"solucion": "respuesta"}  # otros nombres para las mismas claves (opcional)
OPTIONS = False  # True si se usan líneas «- opción» / «+ correcta»

HELP = """
Primera línea: el enunciado.
respuesta: texto   → la respuesta correcta
"""

EXAMPLE = """
¿Cómo se llama el perro de Tintín?
respuesta: Milú
"""


def to_raw(block: Block, raw: dict[str, Any]) -> None:
    """Rellena ``raw`` (la tabla que se escribirá) con los campos del tipo.

    ``block.text("clave")`` da el valor; ``block.lines("clave")`` sus líneas;
    ``block.options`` las opciones. En ``familygame.editor.values`` hay ayudas:
    ``number``, ``boolean``, ``number_pair``, ``coordinates``, ``percent``.

    Raises:
        FormatoError: con un mensaje claro si falta o sobra algo.
    """
    if not block.has("respuesta"):
        raise FormatoError("falta «respuesta:»")
    raw["respuesta"] = block.text("respuesta")
