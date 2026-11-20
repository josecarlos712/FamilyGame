"""Dynamic discovery of question types from ``question_types/<name>/type.py``."""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from familygame.questions.base import QuestionType

log = logging.getLogger(__name__)


def normalize_key(text: str) -> str:
    """Lowercase, strip accents and surrounding spaces (``"Rángo "`` -> ``"rango"``)."""
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass
class TypeRegistry:
    """All question types that loaded correctly, plus loading errors."""

    types: dict[str, type[QuestionType]] = field(default_factory=dict)
    lookup: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def register(self, cls: type[QuestionType], assets_dir: Path | None = None) -> None:
        """Add a type class under its ``type_id`` and aliases."""
        if not cls.type_id:
            raise ValueError(f"{cls.__name__} no define type_id")
        if cls.type_id in self.types:
            raise ValueError(f"tipo «{cls.type_id}» duplicado")
        if assets_dir is not None:
            cls.assets_dir = assets_dir
        self.types[cls.type_id] = cls
        for name in (cls.type_id, *cls.aliases):
            self.lookup[normalize_key(name)] = cls.type_id

    def get(self, name: str) -> type[QuestionType] | None:
        """Find a type by its id or alias, ignoring case and accents."""
        type_id = self.lookup.get(normalize_key(name))
        return self.types.get(type_id) if type_id else None


def load_question_types(root: Path) -> TypeRegistry:
    """Import every ``<root>/<folder>/type.py`` and register its QuestionType.

    Folders starting with ``_`` or ``.`` (like the template) are skipped.
    A broken plugin never stops the game: its error is recorded instead.

    Args:
        root: The ``question_types`` folder.

    Returns:
        The registry with loaded types and human-readable errors.
    """
    registry = TypeRegistry()
    if not root.is_dir():
        registry.errors.append(f"No existe la carpeta de tipos: {root}")
        return registry
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder.name.startswith(("_", ".")):
            continue
        module_file = folder / "type.py"
        if not module_file.is_file():
            registry.errors.append(f"Tipo «{folder.name}»: falta type.py")
            continue
        module_name = f"familygame_qtype_{folder.name}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_file)
            if spec is None or spec.loader is None:
                raise ImportError("no se pudo preparar el módulo")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            classes = [
                obj
                for _, obj in inspect.getmembers(module, inspect.isclass)
                if issubclass(obj, QuestionType)
                and obj is not QuestionType
                and not inspect.isabstract(obj)
                and obj.__module__ == module_name
            ]
            if not classes:
                raise ImportError("no define ninguna clase que herede de QuestionType")
            for cls in classes:
                registry.register(cls, folder)
        except Exception as exc:  # noqa: BLE001 - plugin code is arbitrary; report and continue
            log.exception("Error cargando el tipo %s", folder.name)
            registry.errors.append(f"Tipo «{folder.name}» no cargado: {exc}")
    return registry
