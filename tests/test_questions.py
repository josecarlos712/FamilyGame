"""Question types, registry and category loading."""

from __future__ import annotations

from pathlib import Path
from random import Random

import pytest

from familygame.categories import load_category_file, load_library
from familygame.questions.base import AnswerError, Environment, QuestionFormatError
from familygame.questions.registry import TypeRegistry


def make(registry: TypeRegistry, **raw):
    cls = registry.get(raw.get("tipo", "test"))
    assert cls is not None
    return cls(raw, "cat:x")


# ----- registry ---------------------------------------------------------------

def test_registry_loads_builtin_types_and_skips_template(registry: TypeRegistry) -> None:
    assert set(registry.types) == {"test", "slider", "rango", "mapa", "conoces"}
    assert registry.get("Doble Slider").type_id == "rango"
    assert registry.get("TIPO TEST").type_id == "test"
    assert registry.get("plantilla") is None



def test_flash_question_gets_warning_and_full_reading_time(registry: TypeRegistry) -> None:
    raw = {"enunciado": "¿Cuántas patas tiene una araña?", "opciones": ["6", "8"], "correcta": "8"}
    flash = make(registry, **raw, tiempo=3, lectura=1.5)
    normal = make(registry, **raw, tiempo=15, lectura=1.5)
    assert flash.flash and not normal.flash
    assert normal.read_time == 1.5
    # the short «lectura» is raised to the length-based default, plus the warning
    assert flash.read_time == round(1.5 + len(raw["enunciado"]) / 25 + flash.FLASH_WARNING, 1)
    assert flash.to_public(flash.prepare(Random(1)))["flash"] is True


def test_broken_plugin_is_reported_not_fatal(tmp_path: Path) -> None:
    from familygame.questions.registry import load_question_types

    (tmp_path / "roto").mkdir()
    (tmp_path / "roto" / "type.py").write_text("raise RuntimeError('boom')", encoding="utf-8")
    (tmp_path / "vacio").mkdir()
    reg = load_question_types(tmp_path)
    assert reg.types == {}
    assert len(reg.errors) == 2


# ----- test (multiple choice) -------------------------------------------------

def test_test_question_accepts_text_or_number(registry: TypeRegistry) -> None:
    a = make(registry, enunciado="¿?", opciones=["a", "B", "c"], correcta="b")
    b = make(registry, enunciado="¿?", opciones=["a", "B", "c"], correcta=2)
    assert a.correct_index == b.correct_index == 1


@pytest.mark.parametrize(
    "raw",
    [
        {"opciones": ["solo"], "correcta": 1},
        {"opciones": ["a", "a"], "correcta": 1},
        {"opciones": ["a", "b"], "correcta": 3},
        {"opciones": ["a", "b"], "correcta": "z"},
        {"opciones": ["a", "b"]},
        {"opciones": "a, b", "correcta": 1},
    ],
)
def test_test_question_rejects_bad_data(registry: TypeRegistry, raw: dict) -> None:
    with pytest.raises(QuestionFormatError):
        make(registry, enunciado="¿?", **raw)


def test_test_question_shuffle_maps_displayed_index(registry: TypeRegistry) -> None:
    q = make(registry, enunciado="¿?", opciones=["a", "b", "c", "d"], correcta="c")
    state = q.prepare(Random(3))
    shown = q.public_data(state)["options"]
    idx = shown.index("c")
    assert q.evaluate(q.normalize_answer(idx, state), state).correct
    assert q.solution_data(state)["index"] == idx
    wrong = (idx + 1) % 4
    assert not q.evaluate(q.normalize_answer(wrong, state), state).correct
    with pytest.raises(AnswerError):
        q.normalize_answer(9, state)
    assert "correct" not in str(q.to_public(state))


def test_common_fields(registry: TypeRegistry) -> None:
    q = make(registry, enunciado="¿?", opciones=["a", "b"], correcta=1, tiempo=3, dificultad=3, raro=1)
    assert q.time_limit == 3 and q.base_points == 200
    assert any("raro" in w for w in q.warnings)
    with pytest.raises(QuestionFormatError):
        make(registry, enunciado="¿?", opciones=["a", "b"], correcta=1, tiempo=0)
    with pytest.raises(QuestionFormatError):
        make(registry, opciones=["a", "b"], correcta=1)


# ----- slider -----------------------------------------------------------------

def test_slider_tolerance_absolute_and_percent(registry: TypeRegistry) -> None:
    q = make(registry, tipo="slider", enunciado="¿?", min=0, max=100, respuesta=50, tolerancia=5)
    assert q.evaluate(55, {}).correct and not q.evaluate(55.5, {}).correct
    p = make(registry, tipo="slider", enunciado="¿?", min=0, max=1000, respuesta=200, tolerancia_pct=10)
    assert p.evaluate(220, {}).correct and not p.evaluate(221, {}).correct
    assert q.evaluate(50, {}).closeness == 1
    assert q.normalize_answer(55.4, {}) == 55  # snapped to «paso»
    fine = make(registry, tipo="slider", enunciado="¿?", min=30, max=45, paso=0.1, respuesta=36.6)
    assert fine.normalize_answer(36.6400001, {}) == 36.6
    with pytest.raises(AnswerError):
        q.normalize_answer(101, {})


@pytest.mark.parametrize(
    "raw",
    [
        {"min": 10, "max": 0, "respuesta": 5},
        {"min": 0, "max": 10, "respuesta": 11},
        {"min": 0, "max": 10, "respuesta": 5, "tolerancia": 1, "tolerancia_pct": 3},
        {"min": 0, "max": 10, "respuesta": 0, "tolerancia_pct": 5},
        {"min": 0, "max": 10, "respuesta": "5"},
    ],
)
def test_slider_rejects_bad_data(registry: TypeRegistry, raw: dict) -> None:
    with pytest.raises(QuestionFormatError):
        make(registry, tipo="slider", enunciado="¿?", **raw)


# ----- rango ------------------------------------------------------------------

def test_range_criteria(registry: TypeRegistry) -> None:
    base = dict(tipo="rango", enunciado="¿?", min=0, max=100, respuesta=[40, 60])
    overlap = make(registry, **base, criterio="solapar", solape_min=50)
    assert overlap.evaluate((40, 60), {}).correct
    assert overlap.evaluate((45, 65), {}).correct  # 15/25 = 60 %
    assert not overlap.evaluate((0, 100), {}).correct  # 20 % – no giant ranges
    contain = make(registry, **base, criterio="contener", ancho_max=30)
    assert contain.evaluate((35, 62), {}).correct
    assert not contain.evaluate((0, 100), {}).correct
    assert not contain.evaluate((45, 70), {}).correct
    match = make(registry, **base, criterio="coincidir", margen=2)
    assert match.evaluate((41, 62), {}).correct and not match.evaluate((37, 60), {}).correct
    assert overlap.normalize_answer([60, 40], {}) == (40, 60)


def test_range_rejects_bad_data(registry: TypeRegistry) -> None:
    with pytest.raises(QuestionFormatError):
        make(registry, tipo="rango", enunciado="¿?", min=0, max=10, respuesta=[8, 2])
    with pytest.raises(QuestionFormatError):
        make(registry, tipo="rango", enunciado="¿?", min=0, max=10, respuesta=[2, 8], criterio="cerca")


# ----- mapa -------------------------------------------------------------------

def test_map_point_radius_and_zone(registry: TypeRegistry, env: Environment) -> None:
    q = make(registry, tipo="mapa", enunciado="¿?", respuesta={"lat": 40.4168, "lng": -3.7038}, radio=40000)
    assert q.evaluate((40.45, -3.60), {}).correct  # ~10 km
    assert not q.evaluate((41.39, 2.17), {}).correct  # Barcelona
    zone = make(
        registry, tipo="mapa", enunciado="¿?",
        zona=[[39.96, 2.80], [39.92, 3.20], [39.80, 3.50], [39.30, 3.20], [39.35, 2.40], [39.70, 2.30]],
    )
    assert zone.evaluate((39.6, 2.9), {}).correct
    assert not zone.evaluate((38.9, 1.4), {}).correct  # Ibiza
    assert q.is_available(env)[0]
    assert not q.is_available(Environment(internet=True, google_maps_api_key=""))[0]
    assert not q.is_available(Environment(internet=False, google_maps_api_key="k"))[0]


def test_map_requires_a_number(registry: TypeRegistry) -> None:
    with pytest.raises(QuestionFormatError):  # «cerca» sin número no se puede puntuar
        make(registry, tipo="mapa", enunciado="¿?", respuesta={"lat": 1, "lng": 2})


# ----- files ------------------------------------------------------------------

def test_malformed_file_and_partial_errors(tmp_path: Path, registry: TypeRegistry, env: Environment) -> None:
    bad = tmp_path / "rota.toml"
    bad.write_text("[categoria\nnombre = 'x'", encoding="utf-8")
    cat = load_category_file(bad, registry, env)
    assert not cat.playable and cat.errors

    mixed = tmp_path / "mixta.toml"
    mixed.write_text(
        """
[categoria]
nombre = "Mixta"
color = "rojo"
[[pregunta]]
enunciado = "Buena"
opciones = ["a", "b"]
correcta = "a"
[[pregunta]]
enunciado = "Mala"
opciones = ["a", "b"]
correcta = "z"
[[pregunta]]
tipo = "inventado"
enunciado = "Tipo raro"
[[pregunta]]
enunciado = "Buena"
opciones = ["a", "b"]
correcta = "b"
""",
        encoding="utf-8",
    )
    cat = load_category_file(mixed, registry, env)
    assert cat.name == "Mixta" and len(cat.questions) == 1
    assert len(cat.errors) == 2
    assert any("repetida" in w for w in cat.warnings)
    assert any("color" in w for w in cat.warnings)

    empty = tmp_path / "vacia.toml"
    empty.write_text("[categoria]\nnombre = 'Vacía'\n", encoding="utf-8")
    assert not load_category_file(empty, registry, env).playable


def test_bundled_question_files_are_valid(root: Path, registry: TypeRegistry, env: Environment) -> None:
    library = load_library(root / "preguntas", registry, env)
    assert len(library.categories) >= 6
    for cat in library.categories.values():
        assert not cat.errors, (cat.name, cat.errors)
        assert not cat.warnings, (cat.name, cat.warnings)
    no_maps = load_library(root / "preguntas", registry, Environment(google_maps_api_key=""))
    assert any(c.unavailable for c in no_maps.categories.values())  # map questions need the key
    assert all(c.playable for c in no_maps.categories.values())


def test_template_works_when_copied(tmp_path: Path, root: Path) -> None:
    import shutil

    from familygame.questions.registry import load_question_types

    shutil.copytree(root / "question_types" / "_plantilla", tmp_path / "ejemplo")
    reg = load_question_types(tmp_path)
    assert not reg.errors and "plantilla" in reg.types
    q = reg.get("plantilla")({"enunciado": "¿Color del cielo?", "respuesta": "Azul"}, "c:1")
    assert q.public_data({}) == {"letters": 4}
    assert q.evaluate(q.normalize_answer(" azul ", {}), {}).correct
