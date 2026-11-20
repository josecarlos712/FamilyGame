"""Load categories from ``preguntas/*.toml`` (one file = one category)."""

from __future__ import annotations

import hashlib
import logging
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from familygame.questions.base import Environment, QuestionFormatError, QuestionType
from familygame.questions.registry import TypeRegistry, normalize_key

log = logging.getLogger(__name__)

DEFAULT_COLORS = (
    "#ff6b6b", "#ffa94d", "#ffd43b", "#69db7c", "#38d9a9",
    "#4dabf7", "#748ffc", "#b197fc", "#f783ac", "#e599f7",
)
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class Category:
    """A category loaded from one file.

    Attributes:
        id: File name without extension, normalized.
        name: Name shown in the game.
        icon: Emoji shown next to the name.
        color: Accent colour (#rrggbb).
        questions: Valid questions.
        unavailable: (question, reason) pairs valid but not playable now.
        errors: Human-readable problems (file or per-question).
        warnings: Non-blocking remarks (unknown fields, duplicates).
    """

    id: str
    name: str
    icon: str
    color: str
    description: str
    source: Path
    questions: list[QuestionType] = field(default_factory=list)
    unavailable: list[tuple[QuestionType, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def playable(self) -> bool:
        """True if at least one question can be asked."""
        return bool(self.questions)

    def summary(self) -> dict[str, Any]:
        """Public info for lobby screens."""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "description": self.description,
            "count": len(self.questions),
            "unavailable": len(self.unavailable),
            "unavailableReasons": sorted({reason for _, reason in self.unavailable}),
            "errors": self.errors[:8],
            "errorCount": len(self.errors),
            "warnings": self.warnings[:8],
            "playable": self.playable,
            "file": self.source.name,
        }


@dataclass
class CategoryLibrary:
    """Every category found in the questions folder."""

    categories: dict[str, Category] = field(default_factory=dict)

    def playable(self) -> list[Category]:
        """Categories with at least one playable question."""
        return [c for c in self.categories.values() if c.playable]


def slugify(text: str) -> str:
    """``"Cine y TV"`` -> ``"cine-y-tv"``."""
    return re.sub(r"[^a-z0-9]+", "-", normalize_key(text)).strip("-") or "categoria"


def question_key(category_id: str, prompt: str) -> str:
    """Stable id for a question, used to avoid repeats across games."""
    digest = hashlib.sha1(normalize_key(prompt).encode("utf-8")).hexdigest()[:12]
    return f"{category_id}:{digest}"


def _short(text: Any) -> str:
    text = str(text or "").strip().replace("\n", " ")
    return text if len(text) <= 40 else text[:37] + "…"


def load_category_file(
    path: Path, registry: TypeRegistry, env: Environment, index: int = 0
) -> Category:
    """Parse one TOML file into a Category; never raises for bad content.

    Args:
        path: The .toml file.
        registry: Available question types.
        env: Used to decide which questions are playable now.
        index: Position of the file, picks a default colour.

    Returns:
        The category, possibly with errors and no questions.
    """
    cat_id = slugify(path.stem)
    category = Category(
        id=cat_id,
        name=path.stem.replace("_", " ").strip().capitalize(),
        icon="❓",
        color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
        description="",
        source=path,
    )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        category.errors.append(f"El archivo no se puede leer (formato TOML): {exc}")
        return category
    except (OSError, UnicodeDecodeError) as exc:
        category.errors.append(f"No se pudo abrir el archivo: {exc}")
        return category

    meta = data.get("categoria", {})
    if not isinstance(meta, dict):
        category.errors.append("[categoria] debe ser una tabla")
        meta = {}
    name = meta.get("nombre")
    if isinstance(name, str) and name.strip():
        category.name = name.strip()[:40]
    icon = meta.get("icono")
    if isinstance(icon, str) and icon.strip():
        category.icon = icon.strip()[:4]
    color = meta.get("color")
    if isinstance(color, str):
        if HEX_COLOR.match(color.strip()):
            category.color = color.strip().lower()
        else:
            category.warnings.append(f"color «{color}» no válido (usa #rrggbb)")
    desc = meta.get("descripcion")
    if isinstance(desc, str):
        category.description = desc.strip()[:120]

    raw_questions = data.get("pregunta", [])
    if not isinstance(raw_questions, list):
        category.errors.append("Las preguntas deben ir en bloques [[pregunta]]")
        return category
    if not raw_questions:
        category.errors.append("No hay ninguna pregunta ([[pregunta]])")

    seen: set[str] = set()
    for number, raw in enumerate(raw_questions, start=1):
        label = f"Pregunta {number}"
        if not isinstance(raw, dict):
            category.errors.append(f"{label}: no es un bloque válido")
            continue
        label = f"Pregunta {number} («{_short(raw.get('enunciado'))}»)"
        type_name = raw.get("tipo", "test")
        if not isinstance(type_name, str):
            category.errors.append(f"{label}: «tipo» debe ser un texto")
            continue
        cls = registry.get(type_name)
        if cls is None:
            category.errors.append(f"{label}: tipo «{type_name}» desconocido")
            continue
        prompt = raw.get("enunciado")
        key = question_key(cat_id, prompt if isinstance(prompt, str) else str(number))
        try:
            question = cls(raw, key)
        except QuestionFormatError as exc:
            category.errors.append(f"{label}: {exc}")
            continue
        if question.key in seen:
            category.warnings.append(f"{label}: repetida, se ignora")
            continue
        seen.add(question.key)
        category.warnings.extend(f"{label}: {w}" for w in question.warnings)
        ok, reason = question.is_available(env)
        if ok:
            category.questions.append(question)
        else:
            category.unavailable.append((question, reason))
    return category


def load_library(folder: Path, registry: TypeRegistry, env: Environment) -> CategoryLibrary:
    """Load every ``*.toml`` under ``folder`` (files starting with ``_`` are skipped).

    Two files with the same name in different subfolders get distinct ids.
    """
    library = CategoryLibrary()
    if not folder.is_dir():
        return library
    files = sorted(
        p for p in folder.rglob("*.toml")
        if not p.name.startswith(("_", ".")) and not any(part.startswith("_") for part in p.relative_to(folder).parts[:-1])
    )
    for index, path in enumerate(files):
        category = load_category_file(path, registry, env, index)
        base_id, n = category.id, 2
        while category.id in library.categories:
            category.id = f"{base_id}-{n}"
            n += 1
        if category.id != base_id:
            for q in category.questions:
                q.key = q.key.replace(f"{base_id}:", f"{category.id}:", 1)
        library.categories[category.id] = category
        log.info("Categoría %s: %d preguntas, %d errores", category.name, len(category.questions), len(category.errors))
    return library
