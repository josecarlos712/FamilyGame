"""Multiple-choice question (tipo = "test")."""

from __future__ import annotations

from random import Random
from typing import Any

from familygame.questions.base import (
    AnswerError,
    Evaluation,
    FieldReader,
    QuestionFormatError,
    QuestionType,
)


class TestQuestion(QuestionType):
    """Classic trivia question with 2-8 options and one correct answer.

    File fields:
        opciones: list of 2-8 texts.
        correcta: the correct option, as its text or its position (1 = first).
        barajar: shuffle options every time it is asked (default true).
    """

    __test__ = False  # stop pytest from collecting this class
    type_id = "test"
    aliases = ("opciones", "multiple", "tipo test")
    display_name = "Tipo test"
    default_time = 20

    def parse(self, fields: FieldReader) -> None:
        options = fields.get("opciones")
        if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
            raise QuestionFormatError("«opciones» debe ser una lista de textos: [\"A\", \"B\"]")
        options = [o.strip() for o in options]
        if not 2 <= len(options) <= 8:
            raise QuestionFormatError("«opciones» debe tener entre 2 y 8 opciones")
        if any(not o for o in options):
            raise QuestionFormatError("hay una opción vacía")
        lowered = [o.casefold() for o in options]
        if len(set(lowered)) != len(lowered):
            raise QuestionFormatError("hay opciones repetidas")
        correct = fields.get("correcta")
        if isinstance(correct, bool) or correct is None:
            raise QuestionFormatError("falta «correcta» (texto de la opción o su número)")
        if isinstance(correct, int):
            if not 1 <= correct <= len(options):
                raise QuestionFormatError(f"«correcta» debe estar entre 1 y {len(options)}")
            self.correct_index = correct - 1
        elif isinstance(correct, str):
            try:
                self.correct_index = lowered.index(correct.strip().casefold())
            except ValueError as exc:
                raise QuestionFormatError(
                    f"«correcta» = \"{correct}\" no coincide con ninguna opción"
                ) from exc
        else:
            raise QuestionFormatError("«correcta» debe ser un texto o un número")
        self.options = options
        self.shuffle = fields.boolean("barajar", True)

    def prepare(self, rng: Random) -> dict[str, Any]:
        order = list(range(len(self.options)))
        if self.shuffle:
            rng.shuffle(order)
        return {"order": order}

    def public_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"options": [self.options[i] for i in state["order"]]}

    def normalize_answer(self, raw: Any, state: dict[str, Any]) -> int:
        """Phones send the displayed index; store the original option index."""
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise AnswerError("respuesta no válida")
        if not 0 <= raw < len(self.options):
            raise AnswerError("opción fuera de rango")
        return state["order"][raw]

    def evaluate(self, answer: int, state: dict[str, Any]) -> Evaluation:
        correct = answer == self.correct_index
        return Evaluation(correct, 1.0 if correct else 0.0)

    def solution_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "index": state["order"].index(self.correct_index),
            "text": self.options[self.correct_index],
        }

    def answer_for_display(self, answer: int, state: dict[str, Any]) -> int:
        return state["order"].index(answer)
