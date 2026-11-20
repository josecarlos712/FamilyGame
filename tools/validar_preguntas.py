"""Comprueba uno o varios archivos de preguntas con el cargador real del juego.

Uso:
    .venv\\Scripts\\python tools\\validar_preguntas.py preguntas\\historia.toml [otro.toml ...]

Muestra cuántas preguntas válidas hay por tipo, los errores y avisos, y los enunciados que se
repiten entre los archivos indicados.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from familygame.categories import load_category_file  # noqa: E402
from familygame.questions.base import Environment  # noqa: E402
from familygame.questions.registry import load_question_types  # noqa: E402


def main(paths: list[str]) -> int:
    """Valida los archivos y devuelve 1 si alguno tiene errores o avisos."""
    registry = load_question_types(ROOT / "question_types")
    env = Environment(google_maps_api_key="validacion")
    seen: dict[str, str] = {}
    bad = 0
    for raw in paths:
        path = Path(raw)
        cat = load_category_file(path, registry, env)
        kinds = Counter(type(q).__name__ for q in cat.questions)
        print(f"{path.name}: {len(cat.questions)} preguntas {dict(kinds)}")
        for msg in [*cat.errors, *cat.warnings]:
            print(f"  ! {msg}")
            bad = 1
        for q in cat.questions:
            prompt = q.prompt.strip().lower()
            if prompt in seen and seen[prompt] != path.name:
                print(f"  ! repetida con {seen[prompt]}: {q.prompt}")
            seen.setdefault(prompt, path.name)
    return bad


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
