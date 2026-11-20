"""Turn the editor's plain-text format into raw ``[[pregunta]]`` tables.

The text is a list of paragraphs (separated by blank lines or ``---``), one per
question::

    ¿En qué año llegó Colón a América?
    - 1453
    + 1492
    - 1512
    tiempo: 10
    explicacion: Llegó a Guanahaní el 12 de octubre.

* The first line without a key is the prompt (it may continue on following lines).
* ``clave: valor`` lines are fields; a line without a key continues the previous field.
* ``- texto`` is an option and ``+ texto`` the correct one (types that use options).
* ``# ...`` lines are comments.
* ``tipo: slider`` inside a paragraph changes the type of that question; a paragraph
  with only ``tipo: ...`` changes it for the following ones.

What each type accepts lives in ``question_types/<tipo>/editor.py`` (see
:class:`TypeFormat`); types without one get a generic format.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from familygame.editor.values import Block, FormatoError, Option, boolean, number
from familygame.questions.registry import TypeRegistry, normalize_key

log = logging.getLogger(__name__)

COMMON_KEYS = ("tipo", "enunciado", "tiempo", "lectura", "dificultad", "puntos", "explicacion", "imagen", "id")
COMMON_ALIASES = {"pregunta": "enunciado", "dato": "explicacion", "dato curioso": "explicacion"}
SECONDS = {"": 1, "s": 1, "seg": 1, "segundos": 1}

_KEY_LINE = re.compile(r"^([A-Za-zÁÉÍÓÚÜÑáéíóúüñ_ ]{1,24}?)\s*:\s*(.*)$")
_OPTION_LINE = re.compile(r"^([-+*•])\s+(.*)$")
_SEPARATOR = re.compile(r"^(?:-{3,}|={3,})$")


@dataclass
class TypeFormat:
    """How one question type is written in the editor.

    Attributes:
        type_id: Value of ``tipo``.
        name: Name shown in the editor.
        keys: Extra keys the type accepts (``None``: any key, generic format).
        aliases: Alternative names for keys (``{"punto": "respuesta"}``).
        options: Whether ``-``/``+`` option lines are allowed.
        help: Format guide shown in the editor (plain text).
        example: A ready-to-paste example.
        to_raw: Fills the type-specific fields of the raw table from a block.
        custom: True when the type ships its own ``editor.py``.
    """

    type_id: str
    name: str
    keys: tuple[str, ...] | None
    aliases: dict[str, str]
    options: bool
    help: str
    example: str
    to_raw: Callable[[Block, dict[str, Any]], None]
    custom: bool = False

    def canonical(self, written: str) -> str | None:
        """The key a written name stands for, or ``None`` if not accepted here."""
        name = normalize_key(written).replace("_", " ").strip()
        name = re.sub(r"\s+", " ", name)
        for table in (self.aliases, COMMON_ALIASES):
            for alias, target in table.items():
                if normalize_key(alias) == name:
                    return target
        name = name.replace(" ", "_")
        if name in COMMON_KEYS:
            return name
        if self.keys is None:
            return name if re.fullmatch(r"[a-z][a-z0-9_]*", name) else None
        return name if name in self.keys else None


@dataclass
class Formats:
    """Text formats of every loaded type, plus problems loading the hooks."""

    by_type: dict[str, TypeFormat] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _auto_value(text: str, key: str) -> Any:
    """Generic typing for keys of types without ``editor.py``."""
    try:
        return number(text, key)
    except FormatoError:
        pass
    try:
        return boolean(text, key)
    except FormatoError:
        return text


def _generic_to_raw(block: Block, raw: dict[str, Any]) -> None:
    """Options become ``opciones`` (+ ``correcta``); other keys are typed automatically."""
    if block.options:
        raw["opciones"] = [o.text for o in block.options]
        marked = [o.text for o in block.options if o.correct]
        if len(marked) == 1 and not block.has("correcta"):
            raw["correcta"] = marked[0]
    for key in block.values:
        if key not in COMMON_KEYS:
            raw[key] = _auto_value(block.text(key), key)


def _generic(type_id: str, name: str) -> TypeFormat:
    return TypeFormat(
        type_id=type_id,
        name=name,
        keys=None,
        aliases={},
        options=True,
        help=(
            "Este tipo no tiene formato propio para el editor: cada «clave: valor» se copia tal "
            "cual al archivo (números y sí/no se reconocen solos) y las líneas «- opción» van a "
            "«opciones»."
        ),
        example="Enunciado de la pregunta\nclave: valor",
        to_raw=_generic_to_raw,
    )


def _import_hook(path: Path, folder: str) -> ModuleType:
    module_name = f"familygame_qeditor_{folder}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("no se pudo preparar el módulo")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_formats(registry: TypeRegistry) -> Formats:
    """Build the text format of every registered type.

    Reads ``editor.py`` next to each type's ``type.py`` when it exists. A broken
    hook falls back to the generic format and is reported, like broken types.
    """
    formats = Formats()
    for type_id, cls in registry.types.items():
        name = cls.display_name or type_id
        hook_file = cls.assets_dir / "editor.py" if cls.assets_dir else None
        if hook_file is None or not hook_file.is_file():
            formats.by_type[type_id] = _generic(type_id, name)
            continue
        try:
            module = _import_hook(hook_file, cls.assets_dir.name)  # type: ignore[union-attr]
            to_raw = getattr(module, "to_raw")
            if not callable(to_raw):
                raise TypeError("to_raw debe ser una función")
            formats.by_type[type_id] = TypeFormat(
                type_id=type_id,
                name=getattr(module, "NAME", name),
                keys=tuple(getattr(module, "KEYS", ())),
                aliases=dict(getattr(module, "ALIASES", {})),
                options=bool(getattr(module, "OPTIONS", False)),
                help=str(getattr(module, "HELP", "")).strip(),
                example=str(getattr(module, "EXAMPLE", "")).strip(),
                to_raw=to_raw,
                custom=True,
            )
        except Exception as exc:  # noqa: BLE001 - hook code is arbitrary; report and continue
            log.exception("Error cargando el formato del editor de %s", type_id)
            formats.errors.append(f"Formato del editor de «{type_id}» no cargado: {exc}")
            formats.by_type[type_id] = _generic(type_id, name)
    return formats


def split_paragraphs(text: str) -> list[tuple[int, list[str]]]:
    """Split the text into ``(first line number, lines)`` paragraphs."""
    paragraphs: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 0
    for number_, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or _SEPARATOR.match(stripped):
            if current:
                paragraphs.append((start, current))
                current = []
            continue
        if not current:
            start = number_
        current.append(line.rstrip())
    if current:
        paragraphs.append((start, current))
    return [
        (start, lines) for start, lines in paragraphs
        if any(not line.strip().startswith("#") for line in lines)
    ]


def _find_type(lines: list[str], registry: TypeRegistry) -> tuple[str | None, str | None]:
    """``(type_id, error)`` from a ``tipo:`` line, or ``(None, None)`` if there is none."""
    for line in lines:
        match = _KEY_LINE.match(line.strip())
        if match and normalize_key(match.group(1)) == "tipo":
            written = match.group(2).strip().strip("\"'")
            cls = registry.get(written)
            if cls is None:
                known = ", ".join(registry.types)
                return None, f"tipo «{written}» desconocido (hay: {known})"
            return cls.type_id, None
    return None, None


def parse_block(start: int, lines: list[str], type_id: str, fmt: TypeFormat) -> Block:
    """Split one paragraph into prompt, fields and options (no type conversion yet)."""
    block = Block(line=start, end=start + len(lines) - 1, source=lines, type_id=type_id)
    current: str | None = None
    for offset, line in enumerate(lines):
        number_ = start + offset
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        option = _OPTION_LINE.match(stripped)
        if option:
            if not fmt.options:
                block.errors.append(f"línea {number_}: «{fmt.name}» no usa opciones con - o +")
            else:
                block.options.append(Option(option.group(2).strip(), option.group(1) in "+*", number_))
            current = None
            continue
        keyed = _KEY_LINE.match(stripped)
        key = fmt.canonical(keyed.group(1)) if keyed else None
        if key is not None and fmt.keys is None and "enunciado" not in block.values and key not in COMMON_KEYS:
            key = None  # generic format: the first unknown «x: y» line is the prompt
        if keyed and key is not None:
            if key in block.values:
                block.errors.append(f"línea {number_}: «{key}» está repetido")
            block.values[key] = [keyed.group(2)]
            current = key
            continue
        if "enunciado" not in block.values:
            block.values["enunciado"] = [stripped]
            current = "enunciado"
        elif keyed:
            block.errors.append(f"línea {number_}: no conozco la clave «{keyed.group(1).strip()}»")
        elif current is not None:
            block.values[current].append(stripped)
        else:
            block.errors.append(f"línea {number_}: línea suelta tras las opciones: «{stripped}»")
    return block


def _common_fields(block: Block) -> dict[str, Any]:
    """The optional fields every type shares, typed."""
    out: dict[str, Any] = {}
    for key in ("tiempo", "lectura"):
        if block.has(key):
            out[key] = number(block.text(key), key, SECONDS)
    for key in ("dificultad", "puntos"):
        if block.has(key):
            out[key] = number(block.text(key), key)
    for key in ("explicacion", "imagen", "id"):
        if block.has(key):
            out[key] = block.text(key)
    return out


def to_raw(block: Block, fmt: TypeFormat) -> dict[str, Any]:
    """Build the ``[[pregunta]]`` table of a parsed block.

    Raises:
        FormatoError: If a field cannot be converted.
    """
    raw: dict[str, Any] = {}
    if block.type_id != "test":
        raw["tipo"] = block.type_id
    prompt = block.text("enunciado")
    if not prompt:
        raise FormatoError("falta el enunciado (la primera línea del bloque)")
    raw["enunciado"] = prompt
    fmt.to_raw(block, raw)
    raw.update(_common_fields(block))
    return raw


@dataclass
class ParsedQuestion:
    """One question of the pasted text, before validation by its type.

    Attributes:
        block: The paragraph split into fields.
        raw: The table to write (empty if it could not be built).
        errors: Problems turning the text into a table.
    """

    block: Block
    raw: dict[str, Any]
    errors: list[str]
    inline_type: bool = False

    def standalone_source(self, default_type: str) -> str:
        """The block's text, with a ``tipo:`` line if it relied on an earlier header."""
        text = "\n".join(self.block.source)
        if not self.inline_type and self.block.type_id != default_type:
            return f"tipo: {self.block.type_id}\n{text}"
        return text


def parse_text(text: str, default_type: str, registry: TypeRegistry, formats: Formats) -> list[ParsedQuestion]:
    """Parse the whole pasted text.

    Args:
        text: What the user pasted.
        default_type: Type for paragraphs without ``tipo:``.
        registry: Loaded question types.
        formats: Their editor formats.

    Returns:
        One entry per question paragraph, in order.
    """
    cls = registry.get(default_type)
    current_type = cls.type_id if cls else "test"
    result: list[ParsedQuestion] = []
    for start, lines in split_paragraphs(text):
        found, error = _find_type(lines, registry)
        content = [line for line in lines if not line.strip().startswith("#")]
        if found and len(content) == 1:
            current_type = found
            continue
        type_id = found or current_type
        fmt = formats.by_type.get(type_id) or _generic(type_id, type_id)
        block = parse_block(start, lines, type_id, fmt)
        errors = list(block.errors)
        if error:
            errors.insert(0, error)
        raw: dict[str, Any] = {}
        if not errors:
            try:
                raw = to_raw(block, fmt)
            except FormatoError as exc:
                errors.append(str(exc))
        result.append(ParsedQuestion(block, raw, errors, inline_type=found is not None or error is not None))
    return result
