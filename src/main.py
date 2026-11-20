"""Start the FamilyGame server: ``python src/main.py [--puerto 8765]``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from familygame.config import load_config  # noqa: E402
from familygame.server import Paths, create_app  # noqa: E402


def main() -> None:
    """Parse arguments, build the app and serve it."""
    parser = argparse.ArgumentParser(description="Trivial familiar en la tele")
    parser.add_argument("--puerto", type=int, help="puerto (por defecto el de config.toml)")
    parser.add_argument("--sin-internet", action="store_true", help="no comprobar la conexión")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_config(ROOT / "config.toml")
    if args.puerto:
        config.port = args.puerto
    app = create_app(config, Paths.from_root(ROOT), check_internet=False if args.sin_internet else None)
    server = app.state.server

    lib = server.game.library
    print("\n  ==============================================")
    print("   FAMILY GAME")
    print(f"   Tele:    http://localhost:{config.port}/tv")
    print(f"   Moviles: {server.join_url}")
    print("  ==============================================")
    for cat in lib.categories.values():
        state = f"{len(cat.questions)} preguntas" if cat.playable else "NO JUGABLE"
        print(f"   {cat.icon} {cat.name}: {state}" + (f" ({len(cat.errors)} errores)" if cat.errors else ""))
    for err in server.registry.errors:
        print(f"   ! {err}")
    print()
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning", ws_max_size=1_000_000)


if __name__ == "__main__":
    main()
