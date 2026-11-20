"""«¿Lo conoces?»: a question about the player who chose the category (tipo = "conoces")."""

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


class KnowMeQuestion(QuestionType):
    """There is no right answer in the file: the subject picks their own preference
    and the others try to guess it.

    File fields:
        opciones: list of 2-6 texts.
        barajar: shuffle options every time it is asked (default true).

    Scoring (done by the engine for every ``about_chooser`` type): a friend who
    guesses gets 100; the subject gets +100 per friend who guessed and −50 per
    friend who missed.
    """

    type_id = "conoces"
    aliases = ("lo conoces", "¿lo conoces?", "conocido", "preferencia")
    display_name = "¿Lo conoces?"
    default_time = 20
    about_chooser = True

    def parse(self, fields: FieldReader) -> None:
        options = fields.get("opciones")
        if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
            raise QuestionFormatError("«opciones» debe ser una lista de textos: [\"A\", \"B\"]")
        options = [o.strip() for o in options]
        if not 2 <= len(options) <= 6:
            raise QuestionFormatError("«opciones» debe tener entre 2 y 6 opciones")
        if any(not o for o in options):
            raise QuestionFormatError("hay una opción vacía")
        if any(len(o) > 80 for o in options):
            raise QuestionFormatError("hay una opción demasiado larga (máx. 80)")
        lowered = [o.casefold() for o in options]
        if len(set(lowered)) != len(lowered):
            raise QuestionFormatError("hay opciones repetidas")
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
        reference = state.get("reference")
        correct = reference is not None and answer == reference
        return Evaluation(correct, 1.0 if correct else 0.0)

    def solution_data(self, state: dict[str, Any]) -> dict[str, Any]:
        reference = state.get("reference")
        if reference is None:  # the subject never chose: the question was void
            return {"index": None, "text": ""}
        return {"index": state["order"].index(reference), "text": self.options[reference]}

    def answer_for_display(self, answer: int, state: dict[str, Any]) -> int:
        return state["order"].index(answer)
