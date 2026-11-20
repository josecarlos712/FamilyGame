"""Single-value slider question (tipo = "slider")."""

from __future__ import annotations

from typing import Any

from familygame.questions.base import (
    AnswerError,
    Evaluation,
    FieldReader,
    QuestionFormatError,
    QuestionType,
    format_number,
)


class SliderQuestion(QuestionType):
    """Pick a number on a slider; good if it is within the tolerance.

    File fields:
        min, max: slider limits.
        paso: step (default 1).
        unidad: unit text shown next to the number (default "").
        respuesta: the correct value.
        tolerancia: accepted margin, absolute (respuesta ± tolerancia), or
        tolerancia_pct: accepted margin as a percentage of the answer.
        Without either, only the exact value is good.
    """

    type_id = "slider"
    aliases = ("deslizador", "numero")
    display_name = "Slider"
    default_time = 20
    tiebreak_priority = 10

    def parse(self, fields: FieldReader) -> None:
        self.minimum = fields.number("min")
        self.maximum = fields.number("max")
        if self.maximum <= self.minimum:
            raise QuestionFormatError("«max» debe ser mayor que «min»")
        span = self.maximum - self.minimum
        self.step = fields.number("paso", 1, minimum=0)
        if self.step <= 0 or self.step > span:
            raise QuestionFormatError("«paso» debe ser > 0 y menor que el recorrido")
        self.unit = fields.text("unidad", "", max_len=20)
        self.answer = fields.number("respuesta", minimum=self.minimum, maximum=self.maximum)
        if fields.has("tolerancia") and fields.has("tolerancia_pct"):
            raise QuestionFormatError("usa «tolerancia» o «tolerancia_pct», no las dos")
        if fields.has("tolerancia_pct"):
            pct = fields.number("tolerancia_pct", minimum=0, maximum=100)
            if self.answer == 0 and pct > 0:
                raise QuestionFormatError("«tolerancia_pct» no sirve si la respuesta es 0")
            self.tolerance = abs(self.answer) * pct / 100
        else:
            self.tolerance = fields.number("tolerancia", 0, minimum=0)
        self.start = fields.number(
            "inicio", self.minimum + span / 2, minimum=self.minimum, maximum=self.maximum
        )

    def public_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "unit": self.unit,
            "start": self.start,
        }

    def normalize_answer(self, raw: Any, state: dict[str, Any]) -> float:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise AnswerError("respuesta no válida")
        value = float(raw)
        if not self.minimum <= value <= self.maximum:
            raise AnswerError("valor fuera del slider")
        return value

    def evaluate(self, answer: float, state: dict[str, Any]) -> Evaluation:
        diff = abs(answer - self.answer)
        span = self.maximum - self.minimum
        correct = diff <= self.tolerance + 1e-9
        detail = "¡Clavado!" if diff < 1e-9 else f"Te has desviado {format_number(diff, self.unit)}"
        return Evaluation(correct, max(0.0, 1 - diff / span), detail)

    def solution_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "value": self.answer,
            "low": max(self.minimum, self.answer - self.tolerance),
            "high": min(self.maximum, self.answer + self.tolerance),
            "text": format_number(self.answer, self.unit),
        }
