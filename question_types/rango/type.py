"""Double slider question: the player answers with a range (tipo = "rango")."""

from __future__ import annotations

from typing import Any

from familygame.questions.base import (
    AnswerError,
    Evaluation,
    FieldReader,
    QuestionFormatError,
    QuestionType,
    format_number,
    snap_to_step,
)

CRITERIA = ("solapar", "contener", "coincidir")


class RangeQuestion(QuestionType):
    """Pick a [desde, hasta] range with two handles.

    File fields:
        min, max, paso, unidad: like the slider.
        respuesta: [desde, hasta], the correct range.
        criterio: how the player's range is judged:
            "solapar"   – overlap (intersection / union) ≥ solape_min % (default 50).
            "contener"  – the player's range contains the correct one and is not
                          wider than ancho_max (default: twice the correct width,
                          or 10 % of the slider if that is larger).
            "coincidir" – both ends within ± margen (default 0) of the correct ones.
    """

    type_id = "rango"
    aliases = ("doble slider", "doble_slider", "range")
    display_name = "Doble slider"
    default_time = 25
    tiebreak_priority = 8

    def parse(self, fields: FieldReader) -> None:
        self.minimum = fields.number("min")
        self.maximum = fields.number("max")
        if self.maximum <= self.minimum:
            raise QuestionFormatError("«max» debe ser mayor que «min»")
        self.span = self.maximum - self.minimum
        self.step = fields.number("paso", 1, minimum=0)
        if self.step <= 0 or self.step > self.span:
            raise QuestionFormatError("«paso» debe ser > 0 y menor que el recorrido")
        self.unit = fields.text("unidad", "", max_len=20)
        answer = fields.get("respuesta")
        if (
            not isinstance(answer, list)
            or len(answer) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in answer)
        ):
            raise QuestionFormatError("«respuesta» debe ser [desde, hasta] con dos números")
        self.low, self.high = float(answer[0]), float(answer[1])
        if self.low > self.high:
            raise QuestionFormatError("en «respuesta», «desde» no puede ser mayor que «hasta»")
        if self.low < self.minimum or self.high > self.maximum:
            raise QuestionFormatError("«respuesta» se sale de min/max")
        self.criterion = fields.choice("criterio", CRITERIA, "solapar")
        self.min_overlap = fields.number("solape_min", 50, 1, 100)
        self.margin = fields.number("margen", 0, minimum=0)
        default_width = max(2 * (self.high - self.low), 0.1 * self.span)
        self.max_width = fields.number("ancho_max", default_width, minimum=self.high - self.low)

    def public_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "unit": self.unit,
            "criterion": self.criterion,
            "minOverlap": self.min_overlap,
            "maxWidth": self.max_width if self.criterion == "contener" else None,
        }

    def normalize_answer(self, raw: Any, state: dict[str, Any]) -> tuple[float, float]:
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw)
        ):
            raise AnswerError("respuesta no válida")
        low, high = sorted((float(raw[0]), float(raw[1])))
        if low < self.minimum or high > self.maximum:
            raise AnswerError("rango fuera del slider")
        snap = lambda v: snap_to_step(v, self.minimum, self.maximum, self.step)  # noqa: E731
        return snap(low), snap(high)

    def overlap_ratio(self, low: float, high: float) -> float:
        """Intersection over union of the player's and the correct range (0..1)."""
        inter = max(0.0, min(high, self.high) - max(low, self.low))
        union = max(high, self.high) - min(low, self.low)
        if union <= 0:  # both ranges are the same single point
            return 1.0
        if inter == 0 and self.high == self.low and low <= self.low <= high:
            # correct "range" is a single point inside the player's range
            return 1.0 / max(1.0, (high - low) / self.step)
        return inter / union

    def evaluate(self, answer: tuple[float, float], state: dict[str, Any]) -> Evaluation:
        low, high = answer
        eps = 1e-9
        ratio = self.overlap_ratio(low, high)
        if self.criterion == "contener":
            contains = low <= self.low + eps and high >= self.high - eps
            correct = contains and (high - low) <= self.max_width + eps
            detail = (
                "Lo contiene" if correct else
                "Demasiado ancho" if contains else "No contiene el rango correcto"
            )
        elif self.criterion == "coincidir":
            correct = abs(low - self.low) <= self.margin + eps and abs(high - self.high) <= self.margin + eps
            detail = "Coincide" if correct else "No coincide"
        else:
            correct = ratio * 100 >= self.min_overlap - eps
            detail = f"Solape del {round(ratio * 100)} %"
        dist = abs(low - self.low) + abs(high - self.high)
        closeness = max(ratio, max(0.0, 1 - dist / (2 * self.span)) * 0.5)
        return Evaluation(correct, closeness, detail)

    def solution_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "text": f"{format_number(self.low)} – {format_number(self.high, self.unit)}",
        }

    def answer_for_display(self, answer: tuple[float, float], state: dict[str, Any]) -> list[float]:
        return list(answer)
