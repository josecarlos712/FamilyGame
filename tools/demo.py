"""Serve a frozen demo scene, used to take the README screenshots.

Usage::

    .venv\\Scripts\\python tools\\demo.py <escena> [puerto]

Scenes: lobby, choosing, question, reveal, board, finished, mapa, mapa-reveal
(the two map scenes need the Google Maps key in config.local.toml).
The server clock is frozen, so the scene never advances. Phones can join the
scene as a player by putting its token in localStorage (key ``fg.token``); the
tokens are written to ``data/demo_tokens.json``.
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

import familygame.server as server_module  # noqa: E402
from familygame.config import load_config  # noqa: E402
from familygame.game.board import Board  # noqa: E402
from familygame.server import Paths, create_app  # noqa: E402

T0 = time.time()
server_module.time = types.SimpleNamespace(time=lambda: T0)  # freeze the game clock

PLAYERS = [
    ("Ana", "#4dabf7", "unicornio"),
    ("Luis", "#ff6b6b", "zorro"),
    ("Marta", "#51cf66", "buho"),
    ("Abuela Carmen", "#ffd43b", "gato"),
]


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lobby"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
    paths = Paths.from_root(ROOT)
    config = load_config(ROOT / "config.toml")  # includes the Maps key from config.local.toml
    config.port, config.remember_questions = port, False
    app = create_app(config, paths, check_internet=False)
    app.state.server.join_url = "http://192.168.1.20:8000/"
    game = app.state.server.game
    game.rng = Random(4)
    game.settings.disabled = set() if scene.startswith("mapa") else {"mapas"}
    ids = [game.join(n, c, {"kind": "icon", "value": i}, T0).id for n, c, i in PLAYERS]
    ana, luis, marta, carmen = ids
    tokens = {game.players[pid].name: game.players[pid].token for pid in ids}

    if scene != "lobby":
        game.start(ana, T0)
        game.board = Board.generate(Random(3))
        game.round_no = 2
        for pid, pos, pts in zip(ids, (6, 3, 10, 1), (640, 455, 820, 300)):
            game.players[pid].position = pos
            game.players[pid].points = pts
        game.players[marta].closed = ["ciencia"]
        game.players[marta].progress = {"ciencia": 3}
        game.players[luis].double_next = True
        game.chosen_this_round = set()
        game.deadline = T0 + 20

    if scene in ("mapa", "mapa-reveal"):
        cat = game.library.categories["mapas"]
        question = next(q for q in cat.questions if "Eiffel" in q.prompt)
        game.chooser_id = ana
        game._start_question(cat, question, list(ids), T0 - question.read_time - 12, tiebreak=False)
        game.tick(T0)
        pins = {
            luis: {"lat": 51.51, "lng": -0.13},
            marta: {"lat": 48.86, "lng": 2.34},
            carmen: {"lat": 40.42, "lng": -3.70},
        }
        if scene == "mapa-reveal":
            pins[ana] = {"lat": 48.87, "lng": 2.31}
        for k, (pid, pin) in enumerate(pins.items()):
            game.submit_answer(pid, pin, T0 - 8 + k * 1.7)
        if scene == "mapa-reveal":
            game._reveal(T0)

    if scene in ("question", "reveal", "board"):
        cat = game.library.categories["geografia"]
        question = next(q for q in cat.questions if "río más largo" in q.prompt)
        game.chooser_id = ana
        game._start_question(cat, question, list(ids), T0 - question.read_time - 6, tiebreak=False)
        game.tick(T0)
        options = question.public_data(game.current.state)["options"]
        picks = {luis: "Ebro", marta: "Tajo"}
        if scene != "question":
            picks.update({ana: "Tajo", carmen: "Duero"})
        for k, (pid, text) in enumerate(picks.items()):
            game.submit_answer(pid, options.index(text), T0 - 5 + k * 1.3)
        if scene != "question":
            game._reveal(T0)
        if scene == "board":
            game._apply_board(T0)

    if scene == "finished":
        for pid, pts, ok in zip(ids, (1620, 1380, 990, 720), (9, 8, 6, 5)):
            game.players[pid].points = pts
            game.players[pid].correct_count = ok
            game.players[pid].asked_count = 12
        game._finish([ana], T0)

    (paths.data).mkdir(exist_ok=True)
    (paths.data / "demo_tokens.json").write_text(json.dumps(tokens, ensure_ascii=False), encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
