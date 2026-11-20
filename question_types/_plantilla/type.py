"""PLANTILLA de tipo de pregunta.

Cómo crear un tipo nuevo:
1. Copia esta carpeta ``_plantilla`` y renómbrala sin guion bajo (p. ej. ``ordenar``).
   Las carpetas que empiezan por ``_`` no se cargan.
2. Cambia ``type_id``: es lo que se escribe en ``tipo = "..."`` del archivo de preguntas.
3. Rellena los métodos marcados con TODO.
4. Edita ``tv.js`` (lo que se ve en la tele) y ``phone.js`` (cómo responde cada móvil).
5. Reinicia el servidor (o pulsa «Recargar preguntas» en el lobby).

Los campos comunes (enunciado, tiempo, lectura, dificultad, puntos, explicacion,
imagen, id) ya los lee la clase base; aquí solo los propios de tu tipo.
"""

from __future__ import annotations

from random import Random
from typing import Any

from familygame.questions.base import (
    AnswerError,
    Environment,
    Evaluation,
    FieldReader,
    QuestionFormatError,
    QuestionType,
)


class TemplateQuestion(QuestionType):
    """Ejemplo: el jugador escribe una palabra y vale si coincide."""

    type_id = "plantilla"           # TODO: valor de «tipo» en el archivo
    aliases = ()                    # otros nombres aceptados en «tipo»
    display_name = "Plantilla"
    default_time = 20               # segundos si la pregunta no pone «tiempo»
    requires_internet = False       # True si el tipo necesita red (mapas, vídeos...)
    tiebreak_priority = 0           # >0 si sirve bien para desempates «el más cercano»

    def parse(self, fields: FieldReader) -> None:
        """TODO: lee y valida tus campos. Lanza QuestionFormatError si algo está mal."""
        self.answer = fields.text("respuesta")
        if len(self.answer) > 40:
            raise QuestionFormatError("«respuesta» es demasiado larga")

    def prepare(self, rng: Random) -> dict[str, Any]:
        """Opcional: estado aleatorio de esta vez que se pregunta (barajar, etc.)."""
        return {}

    def public_data(self, state: dict[str, Any]) -> dict[str, Any]:
        """TODO: lo que reciben tele y móviles. ¡Nunca la respuesta!"""
        return {"letters": len(self.answer)}

    def normalize_answer(self, raw: Any, state: dict[str, Any]) -> Any:
        """TODO: valida lo que manda el móvil con ctx.submit(valor)."""
        if not isinstance(raw, str) or not raw.strip():
            raise AnswerError("escribe algo")
        return raw.strip()[:40]

    def evaluate(self, answer: Any, state: dict[str, Any]) -> Evaluation:
        """TODO: ¿es buena? closeness 0..1 sirve para desempatar."""
        correct = answer.casefold() == self.answer.casefold()
        return Evaluation(correct, 1.0 if correct else 0.0)

    def solution_data(self, state: dict[str, Any]) -> dict[str, Any]:
        """TODO: datos para mostrar la solución al acabar el tiempo."""
        return {"text": self.answer}

    def answer_for_display(self, answer: Any, state: dict[str, Any]) -> Any:
        """Opcional: cómo se enseña en la tele la respuesta de cada jugador."""
        return answer

    def is_available(self, env: Environment) -> tuple[bool, str]:
        """Opcional: devuelve (False, motivo) si ahora no se puede preguntar."""
        return super().is_available(env)
