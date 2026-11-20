"""Game engine: full flows with an injected clock."""

from __future__ import annotations

import json
from pathlib import Path
from random import Random

import pytest

from familygame.categories import Category, CategoryLibrary
from familygame.config import TimingConfig
from familygame.game import engine as E
from familygame.game.board import START, STAR, Board
from familygame.game.engine import Game, GameError
from familygame.game.players import PALETTE_COLORS, TV_BACKGROUND, contrast_ratio
from familygame.questions.registry import TypeRegistry

C = PALETTE_COLORS
ICON = {"kind": "icon", "value": "gato"}


def make_library(registry: TypeRegistry, cats: int = 3, per: int = 6, slider: bool = False) -> CategoryLibrary:
    test_cls = registry.get("test")
    lib = CategoryLibrary()
    for c in range(cats):
        cid = f"c{c}"
        qs = [
            test_cls(
                {"enunciado": f"{cid} pregunta {i}", "opciones": ["bien", "mal", "peor"],
                 "correcta": "bien", "barajar": False, "tiempo": 10, "lectura": 0},
                f"{cid}:{i}",
            )
            for i in range(per)
        ]
        if slider:
            qs.append(registry.get("slider")(
                {"enunciado": f"{cid} slider", "min": 0, "max": 100, "respuesta": 50,
                 "tolerancia": 0, "tiempo": 10, "lectura": 0}, f"{cid}:s"))
        lib.categories[cid] = Category(cid, f"Cat {c}", "❓", "#ffffff", "", Path(f"{cid}.toml"), qs)
    return lib


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self, dt: float = 0) -> float:
        self.t += dt
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


def new_game(registry: TypeRegistry, players: int = 2, **kw) -> tuple[Game, list[str]]:
    game = Game(make_library(registry, **kw), timing=TimingConfig(), rng=Random(1), icons={"gato"})
    ids = [game.join(f"Jugador {i}", C[i], ICON, 0).id for i in range(players)]
    return game, ids


def plain(game: Game) -> None:
    game.board = Board([START] + ["normal"] * 27)


def play(game: Game, clock: Clock, answers: dict[str, int | None], at: float = 1.0, cat: str | None = None) -> None:
    """Play one full question from CHOOSING until the next CHOOSING/FINISHED/TIEBREAK."""
    assert game.phase == E.CHOOSING, game.phase
    game.choose(game.chooser_id, cat or game.offered[0], clock())
    game.tick(clock())
    assert game.phase == E.ANSWERING
    for pid, value in answers.items():
        if value is not None:
            game.submit_answer(pid, value, clock() + at)
    game.tick(clock(at + (0 if all(v is not None for v in answers.values()) else 12)))
    assert game.phase == E.REVEAL
    game.tick(clock(game.timing.reveal))
    assert game.phase == E.BOARD
    game.tick(clock(30))


# ----- players ----------------------------------------------------------------

def test_palette_is_legible_on_tv() -> None:
    for color in PALETTE_COLORS:
        assert contrast_ratio(color, TV_BACKGROUND) >= 4.5, color


def test_join_rules(registry: TypeRegistry) -> None:
    game, ids = new_game(registry, players=1)
    with pytest.raises(GameError, match="Ya hay"):
        game.join("  jugádor   0 ", C[5], ICON, 0)
    with pytest.raises(GameError, match="color"):
        game.join("Otro", C[0], ICON, 0)
    with pytest.raises(GameError):
        game.join("Otro", "#123456", ICON, 0)
    with pytest.raises(GameError):
        game.join("", C[3], ICON, 0)
    with pytest.raises(GameError):
        game.join("Otro", C[3], {"kind": "icon", "value": "../../etc"}, 0)
    for i in range(1, 6):
        game.join(f"P{i}", C[i], ICON, 0)
    with pytest.raises(GameError, match="llena"):
        game.join("Séptimo", C[8], ICON, 0)


def test_host_is_first_connected_and_reconnect(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    assert game.host_id == a
    with pytest.raises(GameError):
        game.start(b, clock())
    token = game.players[a].token
    game.disconnect(a, clock())
    assert game.host_id == b
    assert game.reconnect(token).id == a
    assert game.host_id == a
    assert game.reconnect("nope") is None


# ----- flow -------------------------------------------------------------------

def test_points_and_steps(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    plain(game)
    assert game.chooser_id == a
    play(game, clock, {a: 0, b: 1})
    pa, pb = game.players[a], game.players[b]
    assert pa.points == 100 + round(50 * 0.9)  # base + speed bonus (answered at 1 s of 10)
    assert pb.points == 0
    assert pa.position == 3 and pb.position == 0  # 2 steps + 1 for fastest
    assert game.chooser_id == b  # rotation


def test_phone_view_never_leaks_answers(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    game.choose(a, game.offered[0], clock())
    game.tick(clock())
    game.submit_answer(a, 0, clock(1))
    view = json.dumps(game.phone_view(b))
    assert '"reveal": null' in view and "correct_index" not in view
    assert game.phone_view(b)["myAnswer"] is None
    assert game.phone_view(a)["myAnswer"] == {"display": 0}
    with pytest.raises(GameError, match="Ya has"):
        game.submit_answer(a, 1, clock())


def test_no_repeats_then_recycle(registry: TypeRegistry, clock: Clock) -> None:
    game, (a,) = new_game(registry, players=1, cats=1, per=2)
    game.settings.target_points = 100_000
    game.start(a, clock())
    asked = []
    for _ in range(3):
        game.choose(a, "c0", clock())
        asked.append(game.current.question.key)
        game.tick(clock())
        game.submit_answer(a, 1, clock(1))
        game.tick(clock())
        game.tick(clock(10))
        game.tick(clock(30))
    assert asked[0] != asked[1]
    assert any("agotado" in entry["text"] for entry in game.log)


def test_categories_per_turn(registry: TypeRegistry, clock: Clock) -> None:
    game, (a,) = new_game(registry, players=1, cats=5)
    game.settings.categories_per_turn = 2
    game.start(a, clock())
    assert len(game.offered) == 2


def test_rounds_mode_ends_and_ties_go_to_tiebreak(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.set_settings(a, {"mode": "rounds", "rounds": 1})
    game.start(a, clock())
    plain(game)
    play(game, clock, {a: 0, b: 0}, at=2)  # both correct at the same time
    assert game.phase == E.CHOOSING and game.round_no == 1
    play(game, clock, {a: 0, b: 0}, at=2)
    assert game.phase == E.TIEBREAK
    assert sorted(game.tiebreak_players) == sorted([a, b])
    game.tick(clock(10))
    assert game.phase in (E.READING, E.ANSWERING) and game.current.tiebreak
    game.tick(clock())
    game.submit_answer(a, 1, clock(1))
    game.submit_answer(b, 0, clock(0.5))
    game.tick(clock())
    game.tick(clock(10))
    assert game.phase == E.FINISHED and game.winners == [b]


def test_tiebreak_prefers_slider(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry, slider=True)
    game.start(a, clock())
    game._start_tiebreak([a, b], clock())
    game.tick(clock(10))
    assert game.current.question.type_id == "slider"
    game.tick(clock())
    game.submit_answer(a, 40, clock(1))
    game.submit_answer(b, 45, clock(1))  # nobody exact, b closer -> b wins
    game.tick(clock())
    game.tick(clock(10))
    assert game.winners == [b]


def test_tiebreak_gives_up_after_max_attempts(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    game._start_tiebreak([a, b], clock())
    for _ in range(E.MAX_TIEBREAKS):
        game.tick(clock(10))
        game.tick(clock())
        game.tick(clock(20))  # nobody answers
        game.tick(clock(10))
    assert game.phase == E.FINISHED and sorted(game.winners) == sorted([a, b])


def test_points_target_wins(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.set_settings(a, {"targetPoints": 100})
    game.start(a, clock())
    play(game, clock, {a: 0, b: 1})
    assert game.phase == E.FINISHED and game.winners == [a]


def test_categories_mode_by_hits(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.set_settings(a, {"mode": "categories", "categoriesToClose": 1, "hitsToClose": 2})
    game.board = Board([START] + ["normal"] * 27)  # no stars or events
    game.start(a, clock())
    game.board = Board([START] + ["normal"] * 27)
    play(game, clock, {a: 0, b: 1}, cat="c0")
    assert game.players[a].closed == []
    play(game, clock, {a: 0, b: 1}, cat="c0")
    assert game.players[a].closed == ["c0"]
    assert game.phase == E.FINISHED and game.winners == [a]


def test_categories_mode_rejects_impossible_target(registry: TypeRegistry, clock: Clock) -> None:
    game, (a,) = new_game(registry, players=1, cats=2)
    game.set_settings(a, {"mode": "categories", "categoriesToClose": 3})
    with pytest.raises(GameError, match="solo"):
        game.start(a, clock())


def test_star_space_closes_category(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    game.board = Board([START, STAR] + ["normal"] * 26)
    game.players[a].position = 1
    play(game, clock, {a: 0, b: 0}, cat="c1")
    assert game.players[a].closed == ["c1"] and game.players[b].closed == []


def test_duel_steals_points(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    game.board = Board([START] + ["normal"] * 27)
    game.players[b].points = 500
    game.pending_duels = [(a, b)]
    play(game, clock, {a: 0, b: 1})
    assert game.players[b].points == 500 - E.DUEL_STEAL


def test_chooser_disconnect_picks_random(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    game.disconnect(a, clock())
    game.tick(clock(2.1))
    assert game.phase in (E.READING, E.ANSWERING)
    assert game.current.participants == [b]


def test_clock_freezes_when_nobody_connected(registry: TypeRegistry, clock: Clock) -> None:
    game, (a,) = new_game(registry, players=1)
    game.start(a, clock())
    game.disconnect(a, clock())
    game.tick(clock())
    game.tick(clock(600))
    assert game.phase == E.CHOOSING


def test_unavailable_player_is_exempt(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    game.choose(a, game.offered[0], clock())
    game.tick(clock())
    game.report_unavailable(b, clock())
    game.submit_answer(a, 0, clock(1))
    game.tick(clock())
    assert game.phase == E.REVEAL  # did not wait for b
    assert game.current.results[b].exempt
    assert game.players[b].asked_count == 0


def test_kick_mid_game_and_late_join(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = new_game(registry, players=3)
    game.start(a, clock())
    game.remove(b, a, clock())
    assert b not in game.players
    late = game.join("Tarde", C[7], ICON, clock())
    assert late.points == 0 and late.id in game.order
    with pytest.raises(GameError):
        game.update_profile(late.id, "Otro", C[7], ICON)


# ----- board ------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_board_generation(seed: int) -> None:
    board = Board.generate(Random(seed))
    assert len(board) == 28 and board.spaces[0] == START
    stars = [i for i, s in enumerate(board.spaces) if s == STAR]
    assert len(stars) == 4 and 1 not in stars and 27 not in stars
    assert all(b - a > 1 for a, b in zip(stars, stars[1:]))


def test_board_path_wraps() -> None:
    board = Board([START] + ["normal"] * 9)
    assert board.path(8, 3) == [9, 0, 1]
    assert board.passes_start(8, 3) and not board.passes_start(2, 3)
    assert board.path(1, -2) == [0, 9]
