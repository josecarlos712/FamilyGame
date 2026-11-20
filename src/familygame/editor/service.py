"""Editor logic: review pasted text with the real question types and append it to a category."""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from familygame.categories import HEX_COLOR, load_category_file, question_key
from familygame.editor import toml_out
from familygame.editor.parser import Formats, ParsedQuestion, load_formats, parse_text
from familygame.questions.base import Environment, QuestionFormatError
from familygame.questions.registry import TypeRegistry, load_question_types, normalize_key

# Every question counts as playable while reviewing (maps included).
REVIEW_ENV = Environment(internet=True, google_maps_api_key="editor")


class EditorError(ValueError):
    """A request to the editor cannot be done (bad file name, existing category...)."""


@dataclass(frozen=True)
class EditorPaths:
    """Folders the editor works with."""

    questions: Path
    types: Path
    backups: Path

    @classmethod
    def from_root(cls, root: Path) -> EditorPaths:
        return cls(root / "preguntas", root / "question_types", root / "data" / "editor_copias")


def category_filename(name: str) -> str:
    """``"Cine y TV"`` -> ``"cine_y_tv.toml"``."""
    stem = re.sub(r"[^a-z0-9]+", "_", normalize_key(name)).strip("_")
    if not stem:
        raise EditorError("el nombre de la categoría necesita letras o números")
    return f"{stem}.toml"


class EditorService:
    """Loads the question types and categories, reviews text and writes questions."""

    def __init__(self, paths: EditorPaths) -> None:
        self.paths = paths
        self.registry = TypeRegistry()
        self.formats = Formats()
        self.reload()

    def reload(self) -> None:
        """Read the question types (and their editor formats) again."""
        self.registry = load_question_types(self.paths.types)
        self.formats = load_formats(self.registry)

    # ----- categories ---------------------------------------------------------------

    def category_files(self) -> list[Path]:
        """Category files the game loads (names starting with ``_`` are skipped)."""
        root = self.paths.questions
        if not root.is_dir():
            return []
        return sorted(
            p for p in root.rglob("*.toml")
            if not p.name.startswith(("_", "."))
            and not any(part.startswith("_") for part in p.relative_to(root).parts[:-1])
        )

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.paths.questions).as_posix()

    def resolve(self, name: str) -> Path:
        """Path of a category file given its name relative to ``preguntas/``.

        Raises:
            EditorError: If the name is not one of the category files.
        """
        for path in self.category_files():
            if self._relative(path) == name:
                return path
        raise EditorError(f"no existe la categoría «{name}»")

    def categories(self) -> list[dict[str, Any]]:
        """Summary of every category for the editor's list."""
        out = []
        for index, path in enumerate(self.category_files()):
            cat = load_category_file(path, self.registry, REVIEW_ENV, index)
            counts: dict[str, int] = {}
            for q in [*cat.questions, *(q for q, _ in cat.unavailable)]:
                counts[q.type_id] = counts.get(q.type_id, 0) + 1
            out.append({
                "file": self._relative(path),
                "name": cat.name,
                "icon": cat.icon,
                "color": cat.color,
                "count": sum(counts.values()),
                "byType": counts,
                "errors": len(cat.errors),
            })
        return out

    def known_prompts(self) -> dict[str, str]:
        """Normalized prompt -> category file, for every existing question."""
        known: dict[str, str] = {}
        for path in self.category_files():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
            except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
                continue
            for raw in data.get("pregunta", []) if isinstance(data.get("pregunta"), list) else []:
                prompt = raw.get("enunciado") if isinstance(raw, dict) else None
                if isinstance(prompt, str):
                    known.setdefault(normalize_key(prompt), self._relative(path))
        return known

    def types(self) -> list[dict[str, Any]]:
        """Question types with their editor format, for the mechanic picker."""
        order = ["test", "slider", "rango", "mapa", "conoces"]
        ids = sorted(self.registry.types, key=lambda t: (order.index(t) if t in order else 99, t))
        out = []
        for type_id in ids:
            fmt = self.formats.by_type[type_id]
            cls = self.registry.types[type_id]
            out.append({
                "id": type_id,
                "name": fmt.name,
                "help": fmt.help,
                "example": fmt.example,
                "custom": fmt.custom,
                "defaultTime": cls.default_time,
                "needsInternet": cls.requires_internet,
            })
        return out

    # ----- review and write ---------------------------------------------------------

    def review(self, text: str, default_type: str) -> list[dict[str, Any]]:
        """Parse and validate every question of ``text`` without writing anything.

        Returns:
            One item per question: line range, type, the table to write, its TOML,
            errors (blocking) and warnings.
        """
        known = self.known_prompts()
        seen_here: dict[str, int] = {}
        items = []
        cls = self.registry.get(default_type)
        default_id = cls.type_id if cls else "test"
        for parsed in parse_text(text, default_type, self.registry, self.formats):
            item = self._review_one(parsed, known, seen_here)
            item["source"] = parsed.standalone_source(default_id)
            items.append(item)
        return items

    def _review_one(self, parsed: ParsedQuestion, known: dict[str, str], seen_here: dict[str, int]) -> dict[str, Any]:
        block = parsed.block
        errors = list(parsed.errors)
        warnings: list[str] = []
        toml = ""
        if parsed.raw and not errors:
            cls = self.registry.types[block.type_id]
            try:
                question = cls(parsed.raw, question_key("editor", parsed.raw["enunciado"]))
                warnings.extend(question.warnings)
                toml = toml_out.question(parsed.raw)
            except QuestionFormatError as exc:
                errors.append(str(exc))
            except TypeError as exc:
                errors.append(f"valor no válido: {exc}")
        prompt = block.text("enunciado")
        norm = normalize_key(prompt) if prompt else ""
        if norm and norm in known:
            errors.append(f"ya existe en {known[norm]}")
        elif norm and norm in seen_here:
            errors.append(f"repetida: es la misma que la de la línea {seen_here[norm]}")
        if norm:
            seen_here.setdefault(norm, block.line)
        return {
            "line": block.line,
            "end": block.end,
            "type": block.type_id,
            "typeName": self.formats.by_type[block.type_id].name if block.type_id in self.formats.by_type else block.type_id,
            "prompt": prompt,
            "raw": parsed.raw,
            "toml": toml,
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
        }

    def add(self, text: str, default_type: str, target: str | None = None, new: dict[str, Any] | None = None) -> dict[str, Any]:
        """Append the valid questions of ``text`` to a category (or a new one).

        The file is copied to ``data/editor_copias`` first and checked again after
        writing; if the game's loader does not see the new questions, the copy is
        restored.

        Args:
            text: Pasted text.
            default_type: Type for paragraphs without ``tipo:``.
            target: Existing category file, relative to ``preguntas/``.
            new: ``{"nombre", "icono", "color", "descripcion"}`` to create a category instead.

        Returns:
            ``added``, the ``file`` written, the review and ``remaining``: the text of
            the questions that were not added.

        Raises:
            EditorError: If there is nothing valid to add or the target is wrong.
        """
        items = self.review(text, default_type)
        good = [item for item in items if item["ok"]]
        if not good:
            raise EditorError("no hay ninguna pregunta válida que añadir")
        if new is not None:
            path, header = self._new_category(new)
            before = 0
        else:
            if not target:
                raise EditorError("elige una categoría")
            path, header = self.resolve(target), ""
            current = self._load(path)
            before = len(current.questions) + len(current.unavailable)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        chunk = f"\n# --- Añadidas con el editor el {stamp} ---\n\n" + "\n".join(i["toml"] for i in good)
        backup = self._backup(path) if path.exists() else None
        old_text = path.read_text(encoding="utf-8-sig") if path.exists() else header
        if old_text and not old_text.endswith("\n"):
            old_text += "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(old_text + chunk, encoding="utf-8")
        cat = self._load(path)
        after = len(cat.questions) + len(cat.unavailable)
        if after - before != len(good):
            if backup is not None:
                shutil.copyfile(backup, path)
            else:
                path.unlink(missing_ok=True)
            problems = "; ".join(cat.errors[:3]) or "el número de preguntas no cuadra"
            raise EditorError(f"no se añadió nada: al releer el archivo falló ({problems})")
        remaining = "\n\n".join(item["source"] for item in items if not item["ok"])
        return {
            "added": len(good),
            "file": self._relative(path),
            "total": after,
            "backup": backup.name if backup else "",
            "remaining": remaining + ("\n" if remaining else ""),
            "items": items,
        }

    def _load(self, path: Path):  # noqa: ANN202 - Category
        return load_category_file(path, self.registry, REVIEW_ENV)

    def _new_category(self, new: dict[str, Any]) -> tuple[Path, str]:
        name = str(new.get("nombre", "")).strip()
        if not name:
            raise EditorError("la categoría nueva necesita un nombre")
        path = self.paths.questions / category_filename(name)
        if path.exists():
            raise EditorError(f"ya existe {path.name}: elígela en la lista")
        meta: dict[str, Any] = {"nombre": name[:40]}
        icon = str(new.get("icono", "")).strip()
        if icon:
            meta["icono"] = icon[:4]
        color = str(new.get("color", "")).strip()
        if color:
            if not HEX_COLOR.match(color):
                raise EditorError("el color debe ser #rrggbb")
            meta["color"] = color.lower()
        desc = str(new.get("descripcion", "")).strip()
        if desc:
            meta["descripcion"] = desc[:120]
        return path, toml_out.table("[categoria]", meta)

    def _backup(self, path: Path) -> Path:
        self.paths.backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        copy = self.paths.backups / f"{path.stem}-{stamp}.toml"
        shutil.copyfile(path, copy)
        return copy
