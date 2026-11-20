"""Question editor: text format, review with the real types and writing to files."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from familygame.editor import toml_out
from familygame.editor.app import create_editor_app
from familygame.editor.service import EditorError, EditorPaths, EditorService, category_filename
from familygame.editor.values import FormatoError, coordinates, number, number_pair

ROOT = Path(__file__).resolve().parents[1]

HISTORIA = """# comentario que debe quedarse
[categoria]
nombre = "Historia"
icono = "🏛️"

[[pregunta]]
enunciado = "¿En qué año llegó Colón a América?"
opciones = ["1453", "1492"]
correcta = "1492"
"""


@pytest.fixture
def service(tmp_path: Path) -> EditorService:
    questions = tmp_path / "preguntas"
    questions.mkdir()
    (questions / "historia.toml").write_text(HISTORIA, encoding="utf-8")
    (questions / "_borrador.toml").write_text(HISTORIA, encoding="utf-8")
    return EditorService(EditorPaths(questions, ROOT / "question_types", tmp_path / "copias"))


# ----- values ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1969", 1969), ("-3,5", -3.5), ("36.6", 36.6), ("1 000 000", 1_000_000),
     ("1.000.000", 1_000_000), ("1.234,5", 1234.5), ("0,1", 0.1)],
)
def test_number_formats(text: str, expected: float) -> None:
    assert number(text, "x") == expected


def test_number_units_and_errors() -> None:
    assert number("25 km", "radio", {"": 1, "km": 1000, "m": 1}) == 25_000
    with pytest.raises(FormatoError, match="no entiendo"):
        number("25 millas", "radio", {"km": 1000})
    with pytest.raises(FormatoError, match="número"):
        number("mucho", "respuesta")


@pytest.mark.parametrize("text", ["1936 - 1939", "1936-1939", "1936 a 1939", "1936..1939", "1936 – 1939"])
def test_number_pair(text: str) -> None:
    assert number_pair(text, "respuesta") == [1936, 1939]


def test_number_pair_negative_and_decimal() -> None:
    assert number_pair("-5 - 5", "escala") == [-5, 5]
    assert number_pair("36,1 - 37,2", "respuesta") == [36.1, 37.2]


def test_coordinates() -> None:
    assert coordinates("48.8584, 2.2945", "punto") == (48.8584, 2.2945)
    with pytest.raises(FormatoError):
        coordinates("48,8584", "punto")
    with pytest.raises(FormatoError):
        coordinates("100, 2", "punto")


# ----- formats of every type -------------------------------------------------------------------


def test_every_type_has_a_format_and_its_example_is_valid(service: EditorService) -> None:
    assert not service.formats.errors
    for info in service.types():
        assert info["custom"], f"{info['id']} sin editor.py"
        items = service.review(info["example"], info["id"])
        assert items, info["id"]
        for item in items:
            real = [e for e in item["errors"] if not e.startswith("ya existe")]
            assert not real and item["toml"], (info["id"], item["errors"])
            assert item["type"] == info["id"]


def test_test_type_marks(service: EditorService) -> None:
    item = service.review("¿Capital de Francia?\n- Roma\n+ París\n- Berlín\ntiempo: 10 s", "test")[0]
    assert item["ok"]
    assert item["raw"] == {"enunciado": "¿Capital de Francia?", "opciones": ["Roma", "París", "Berlín"], "correcta": "París", "tiempo": 10}

    none = service.review("¿Capital?\n- Roma\n- París", "test")[0]
    assert not none["ok"] and "exactamente una" in none["errors"][0]
    two = service.review("¿Capital?\n+ Roma\n+ París", "test")[0]
    assert "hay 2" in two["errors"][0]
    by_number = service.review("¿Capital?\n- Roma\n- París\ncorrecta: 2", "test")[0]
    assert by_number["raw"]["correcta"] == 2 and by_number["ok"]


def test_conoces_rejects_correct_marks(service: EditorService) -> None:
    item = service.review("¿Qué prefiere?\n+ Mar\n- Montaña", "conoces")[0]
    assert "no tiene opción correcta" in item["errors"][0]


def test_validation_comes_from_the_real_type(service: EditorService) -> None:
    item = service.review("¿Año?\nrespuesta: 3000\nescala: 1900 - 2000", "slider")[0]
    assert not item["ok"]
    assert "respuesta" in item["errors"][0]


def test_map_radius_and_zone(service: EditorService) -> None:
    item = service.review("Señala Madrid\npunto: 40.4168, -3.7038\nradio: 50 km", "mapa")[0]
    assert item["ok"]
    assert item["raw"]["respuesta"] == {"lat": 40.4168, "lng": -3.7038}
    assert item["raw"]["radio"] == 50_000
    zone = service.review("Toca Ibiza\nzona: 39.1, 1.2; 38.9, 1.6; 38.8, 1.3", "mapa")[0]
    assert zone["ok"] and len(zone["raw"]["zona"]) == 3


def test_type_header_and_inline_type(service: EditorService) -> None:
    text = (
        "¿Test?\n- a\n+ b\n\n"
        "tipo: rango\n\n"
        "¿Rango?\nrespuesta: 1 - 2\nescala: 0 - 10\n\n"
        "¿Número?\ntipo: slider\nrespuesta: 5\nescala: 0 - 10\n\n"
        "¿Otro rango?\nrespuesta: 3 - 4\nescala: 0 - 10"
    )
    types = [i["type"] for i in service.review(text, "test")]
    assert types == ["test", "rango", "slider", "rango"]


def test_aliases_accents_and_continuation(service: EditorService) -> None:
    text = "Pregunta: ¿Cuál es\nmás alta?\n- A\n+ B\nExplicación: Dato\nque sigue\nDificultad: 2"
    item = service.review(text, "test")[0]
    assert item["ok"], item["errors"]
    assert item["raw"]["enunciado"] == "¿Cuál es más alta?"
    assert item["raw"]["explicacion"] == "Dato que sigue"
    assert item["raw"]["dificultad"] == 2


def test_prompt_with_colon_and_unknown_key(service: EditorService) -> None:
    ok = service.review("Completa la frase: «Más vale tarde…»\n- que nunca\n+ que nunca jamás", "test")[0]
    assert ok["prompt"].startswith("Completa la frase:")
    bad = service.review("¿Algo?\n- a\n+ b\ncolor: rojo", "test")[0]
    assert "no conozco la clave «color»" in bad["errors"][0]


def test_unknown_type_and_options_not_allowed(service: EditorService) -> None:
    assert "desconocido" in service.review("¿Algo?\ntipo: ruleta", "test")[0]["errors"][0]
    assert "no usa opciones" in service.review("¿Año?\n- 1\nrespuesta: 1\nescala: 0 - 2", "slider")[0]["errors"][0]


def test_duplicates(service: EditorService) -> None:
    items = service.review(
        "¿En qué año llegó Colón a América?\n- 1\n+ 2\n\n¿Nueva?\n- a\n+ b\n\n¿nueva?\n- c\n+ d", "test"
    )
    assert items[0]["errors"] == ["ya existe en historia.toml"]
    assert items[1]["ok"]
    assert "línea 5" in items[2]["errors"][0]


def test_toml_round_trip(service: EditorService) -> None:
    text = service.types()[3]["example"]  # mapa: inline tables and nested lists
    for item in service.review(text, "mapa"):
        assert tomllib.loads(item["toml"])["pregunta"][0] == item["raw"]
    tricky = {"enunciado": 'Comillas "dobles", barra \\ y\nsalto', "x": 1.5, "b": False}
    assert tomllib.loads(toml_out.question(tricky))["pregunta"][0] == tricky


# ----- writing -----------------------------------------------------------------------------------


def test_add_appends_and_keeps_the_rest(service: EditorService) -> None:
    text = "¿Nueva 1?\n- a\n+ b\n\ntipo: slider\n\n¿Mala?\nrespuesta: x\nescala: 0 - 1\n\n¿Número?\nrespuesta: 5\nescala: 0 - 10"
    result = service.add(text, "test", target="historia.toml")
    assert result["added"] == 2 and result["total"] == 3
    written = (service.paths.questions / "historia.toml").read_text(encoding="utf-8")
    assert written.startswith("# comentario que debe quedarse")
    assert "Añadidas con el editor" in written
    assert result["backup"] and (service.paths.backups / result["backup"]).read_text(encoding="utf-8") == HISTORIA
    # The failed slider keeps its type although its header line is gone.
    assert result["remaining"].startswith("tipo: slider\n¿Mala?")
    again = service.review(result["remaining"], "test")
    assert again[0]["type"] == "slider"


def test_add_refuses_nothing_valid_and_bad_targets(service: EditorService) -> None:
    with pytest.raises(EditorError, match="ninguna"):
        service.add("¿Mala?\n- a", "test", target="historia.toml")
    for bad in ("../fuera.toml", "_borrador.toml", "no_existe.toml", None):
        with pytest.raises(EditorError):
            service.add("¿Buena?\n- a\n+ b", "test", target=bad)


def test_add_new_category(service: EditorService) -> None:
    result = service.add("¿Buena?\n- a\n+ b", "test", new={"nombre": "Música y Baile", "icono": "🎵", "color": "#FF0000"})
    assert result["file"] == "musica_y_baile.toml"
    data = tomllib.loads((service.paths.questions / "musica_y_baile.toml").read_text(encoding="utf-8"))
    assert data["categoria"] == {"nombre": "Música y Baile", "icono": "🎵", "color": "#ff0000"}
    assert len(data["pregunta"]) == 1
    with pytest.raises(EditorError, match="ya existe"):
        service.add("¿Otra?\n- a\n+ b", "test", new={"nombre": "Música y baile"})
    with pytest.raises(EditorError, match="color"):
        service.add("¿Otra?\n- a\n+ b", "test", new={"nombre": "Cine", "color": "rojo"})
    assert category_filename("¡Cine y TV!") == "cine_y_tv.toml"


def test_categories_skip_drafts(service: EditorService) -> None:
    cats = service.categories()
    assert [c["file"] for c in cats] == ["historia.toml"]
    assert cats[0]["count"] == 1 and cats[0]["byType"] == {"test": 1}


# ----- HTTP --------------------------------------------------------------------------------------


def test_http_api(tmp_path: Path) -> None:
    questions = tmp_path / "preguntas"
    questions.mkdir()
    (questions / "historia.toml").write_text(HISTORIA, encoding="utf-8")
    app = create_editor_app(ROOT, EditorPaths(questions, ROOT / "question_types", tmp_path / "copias"))
    client = TestClient(app)
    assert client.get("/").status_code == 200

    state = client.get("/api/estado").json()
    assert state["categories"][0]["file"] == "historia.toml"
    assert [t["id"] for t in state["types"]][:2] == ["test", "slider"]

    form = client.post("/api/revisar", data={"text": "x"})
    assert form.status_code == 400  # not JSON: blocks cross-site form posts

    review = client.post("/api/revisar", json={"text": "¿Hola?\n- a\n+ b", "tipo": "test"}).json()
    assert review["items"][0]["ok"]

    added = client.post("/api/anadir", json={"text": "¿Hola?\n- a\n+ b", "tipo": "test", "archivo": "historia.toml"})
    assert added.status_code == 200 and added.json()["added"] == 1
    again = client.post("/api/anadir", json={"text": "¿Hola?\n- a\n+ b", "tipo": "test", "archivo": "historia.toml"})
    assert again.status_code == 400 and "ninguna" in again.json()["error"]
