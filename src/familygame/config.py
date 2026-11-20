"""Settings read from ``config.toml`` (all optional, sensible defaults)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class TimingConfig:
    """Seconds each automatic phase lasts."""

    choose: float = 20.0
    reveal: float = 7.0
    board: float = 4.0
    board_per_event: float = 1.8
    tiebreak_intro: float = 4.0


@dataclass
class AppConfig:
    """Whole application configuration."""

    host: str = "0.0.0.0"
    port: int = 8765
    google_maps_api_key: str = ""
    check_internet: bool = True
    max_players: int = 6
    remember_questions: bool = True
    timing: TimingConfig = field(default_factory=TimingConfig)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def load_config(path: Path) -> AppConfig:
    """Read ``path`` if it exists; unknown or wrong values fall back to defaults.

    Args:
        path: Location of config.toml.

    Returns:
        The configuration.
    """
    cfg = AppConfig()
    if not path.is_file():
        return cfg
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.error("config.toml no válido (%s); uso valores por defecto", exc)
        return cfg
    # config.local.toml (git-ignored) overrides config.toml: put secrets such as the Maps key there
    local = path.with_name("config.local.toml")
    if local.is_file():
        try:
            override = tomllib.loads(local.read_text(encoding="utf-8-sig"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            log.error("config.local.toml no válido (%s); lo ignoro", exc)
            override = {}
        for name, section in override.items():
            if isinstance(section, dict) and isinstance(data.get(name), dict):
                data[name] = {**data[name], **section}
            else:
                data[name] = section
    server = _section(data, "servidor")
    maps = _section(data, "mapas")
    game = _section(data, "partida")
    timing = _section(data, "tiempos")

    def pick(section: dict[str, Any], key: str, default: Any, kind: type) -> Any:
        value = section.get(key, default)
        if kind is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
            log.warning("config.toml: «%s» no válido, uso %r", key, default)
            return default
        return value

    cfg.host = pick(server, "host", cfg.host, str)
    cfg.port = pick(server, "puerto", cfg.port, int)
    cfg.google_maps_api_key = pick(maps, "google_maps_api_key", "", str).strip()
    cfg.check_internet = pick(maps, "comprobar_internet", True, bool)
    cfg.max_players = max(1, min(6, pick(game, "max_jugadores", 6, int)))
    cfg.remember_questions = pick(game, "evitar_repetidas_entre_partidas", True, bool)
    t = cfg.timing
    t.choose = pick(timing, "elegir_categoria", t.choose, float)
    t.reveal = pick(timing, "revelar", t.reveal, float)
    t.board = pick(timing, "tablero", t.board, float)
    return cfg
