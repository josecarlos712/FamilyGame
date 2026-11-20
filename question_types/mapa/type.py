"""Map question: tap a place on an embedded Google Map (tipo = "mapa")."""

from __future__ import annotations

import math
from typing import Any

from familygame.questions.base import (
    AnswerError,
    Environment,
    Evaluation,
    FieldReader,
    QuestionFormatError,
    QuestionType,
)

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def point_in_polygon(lat: float, lng: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting test on the lat/lng plane (fine for regions < ~1000 km)."""
    inside = False
    j = len(polygon) - 1
    for i, (yi, xi) in enumerate(polygon):
        yj, xj = polygon[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point(value: Any, name: str) -> tuple[float, float]:
    if isinstance(value, dict):
        lat, lng = value.get("lat"), value.get("lng")
    elif isinstance(value, list) and len(value) == 2:
        lat, lng = value
    else:
        raise QuestionFormatError(f"«{name}» debe ser {{ lat = .., lng = .. }} o [lat, lng]")
    for v in (lat, lng):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise QuestionFormatError(f"«{name}» necesita lat y lng numéricos")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise QuestionFormatError(f"«{name}» tiene coordenadas fuera de rango")
    return float(lat), float(lng)


class MapQuestion(QuestionType):
    """Answer by placing a pin on the map.

    File fields (one of the two):
        respuesta = { lat = 40.4168, lng = -3.7038 } and radio = metres
            (good if the pin is within «radio» metres of the point), or
        zona = [[lat, lng], [lat, lng], [lat, lng], ...] (good if inside the polygon).
    Optional:
        vista = { lat = .., lng = .., zoom = .. } initial map view.

    Needs internet and a Google Maps key in config.toml; otherwise the question
    is not offered (it stays listed as "no disponible" in the lobby).
    """

    type_id = "mapa"
    aliases = ("map", "google maps")
    display_name = "Mapa"
    default_time = 45
    requires_internet = True
    tiebreak_priority = 5

    def parse(self, fields: FieldReader) -> None:
        self.point: tuple[float, float] | None = None
        self.radius = 0.0
        self.zone: list[tuple[float, float]] = []
        if fields.has("zona"):
            zone = fields.get("zona")
            if not isinstance(zone, list) or len(zone) < 3:
                raise QuestionFormatError("«zona» necesita al menos 3 puntos [lat, lng]")
            self.zone = [_point(p, "zona") for p in zone]
        if fields.has("respuesta"):
            self.point = _point(fields.get("respuesta"), "respuesta")
            if not fields.has("radio"):
                raise QuestionFormatError("con «respuesta» hace falta «radio» en metros")
            self.radius = fields.number("radio", minimum=1, maximum=5_000_000)
        if self.point is None and not self.zone:
            raise QuestionFormatError("define «respuesta» + «radio» o una «zona»")
        if self.point is None:
            lat = sum(p[0] for p in self.zone) / len(self.zone)
            lng = sum(p[1] for p in self.zone) / len(self.zone)
            self.target = (lat, lng)
        else:
            self.target = self.point
        view = fields.get("vista", {"lat": 30.0, "lng": 0.0, "zoom": 2})
        lat, lng = _point(view, "vista")
        zoom = view.get("zoom", 2) if isinstance(view, dict) else 2
        if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not 1 <= zoom <= 20:
            raise QuestionFormatError("«vista.zoom» debe estar entre 1 y 20")
        self.view = {"lat": lat, "lng": lng, "zoom": zoom}

    def is_available(self, env: Environment) -> tuple[bool, str]:
        if not env.google_maps_api_key:
            return False, "falta la clave de Google Maps en config.toml"
        return super().is_available(env)

    def public_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"view": self.view}

    def normalize_answer(self, raw: Any, state: dict[str, Any]) -> tuple[float, float]:
        try:
            return _point(raw, "respuesta")
        except QuestionFormatError as exc:
            raise AnswerError("punto no válido") from exc

    def evaluate(self, answer: tuple[float, float], state: dict[str, Any]) -> Evaluation:
        dist = haversine_m(*answer, *self.target)
        if self.zone:
            correct = point_in_polygon(*answer, self.zone)
        else:
            correct = dist <= self.radius
        km = dist / 1000
        detail = f"A {km:.0f} km" if km >= 10 else f"A {km:.1f} km".replace(".", ",")
        return Evaluation(correct, max(0.0, 1 - dist / 20_000_000), detail)

    def solution_data(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "point": {"lat": self.target[0], "lng": self.target[1]},
            "radius": self.radius,
            "zone": [{"lat": a, "lng": b} for a, b in self.zone],
        }

    def answer_for_display(self, answer: tuple[float, float], state: dict[str, Any]) -> dict[str, float]:
        return {"lat": answer[0], "lng": answer[1]}
