"""Start the question editor: ``python src/editor.py [--puerto 8766] [--sin-navegador]``.

It is independent of the game: it can run while the game is stopped or playing.
After adding questions, press «Recargar preguntas» in the game's lobby.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from familygame.editor.app import create_editor_app  # noqa: E402


def main() -> None:
    """Parse arguments and serve the editor on this computer only."""
    parser = argparse.ArgumentParser(description="Editor de preguntas de FamilyGame")
    parser.add_argument("--puerto", type=int, default=8766, help="puerto (por defecto 8766)")
    parser.add_argument("--sin-navegador", action="store_true", help="no abrir el navegador")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = create_editor_app(ROOT)
    url = f"http://127.0.0.1:{args.puerto}/"
    print("\n  ==============================================")
    print("   FAMILY GAME · Editor de preguntas")
    print(f"   {url}")
    print("   Cierra esta ventana para pararlo.")
    print("  ==============================================\n")
    if not args.sin_navegador:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    # Only this computer: the editor writes files and has no login.
    uvicorn.run(app, host="127.0.0.1", port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
