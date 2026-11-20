"""«¿Lo conoces?»: questions about the player who chose (QuestionType.about_chooser)."""

from __future__ import annotations

from pathlib import Path
from random import Random

import pytest

from familygame.categories import Category, CategoryLibrary
from familygame.config import TimingConfig
from familygame.game import engine as E
from familygame.game.board import START, Board
from familygame.game.engine import Game, GameError
from familygame.game.players import PALETTE_COLORS
from familygame.questions.base import QuestionFormatError
from familygame.questions.registry import TypeRegistry

ICON = {"kind": "icon", "value": "gato"}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self, dt: float = 0) -> float:
        self.t += dt
        return self.t


def library(registry: TypeRegistry) -> CategoryLibrary:
    know = registry.get("conoces")
    test = registry.get("test")
    lib = CategoryLibrary()
    lib.categories["k"] = Category("k", "Conocer", "🎯", "#ffffff", "", Path("k.toml"), [
        know({"tipo": "conoces", "enunciado": f"¿Qué prefiere? {i}", "opciones": ["Playa", "Montaña", "Ciudad"],
              "barajar": False, "tiempo": 10, "lectura": 0}, f"k:{i}")
        for i in range(4)
    ])
    lib.categories["t"] = Category("t", "Test", "❓", "#000000", "", Path("t.toml"), [
        test({"enunciado": f"Normal {i}", "opciones": ["bien", "mal"], "correcta": "bien",
              "barajar": False, "tiempo": 10, "lectura": 0}, f"t:{i}")
        for i in range(4)
    ])
    return lib


def started(registry: TypeRegistry, clock: Clock, players: int = 3) -> tuple[Game, list[str]]:
    game = Game(library(registry), timing=TimingConfig(), rng=Random(1), icons={"gato"})
    ids = [game.join(f"Jugador {i}", PALETTE_COLORS[i], ICON, 0).id for i in range(players)]
    game.board = Board([START] + ["normal"] * 27)
    game.start(ids[0], clock())
    return game, ids


def ask_about_chooser(game: Game, clock: Clock) -> str:
    subject = game.chooser_id
    assert subject
    game.choose(subject, "k", clock())
    game.tick(clock())
    assert game.phase == E.ANSWERING and game.current and game.current.stage == "subject"
    return subject


@pytest.fixture
def clock() -> Clock:
    return Clock()


def test_format_needs_options(registry: TypeRegistry) -> None:
    know = registry.get("conoces")
    with pytest.raises(QuestionFormatError):
        know({"enunciado": "x", "opciones": ["solo una"]}, "k:x")
    q = know({"enunciado": "x", "opciones": ["A", "B"], "correcta": "A"}, "k:y")
    assert any("correcta" in w for w in q.warnings)  # there is no right answer in the file


def test_friends_wait_for_the_subject_then_score(registry: TypeRegistry, clock: Clock) -> None:
    game, ids = started(registry, clock)
    subject = ask_about_chooser(game, clock)
    friend_ok, friend_bad = [p for p in ids if p != subject]
    with pytest.raises(GameError, match="primero elige"):
        game.submit_answer(friend_ok, 0, clock())
    assert game.tv_view()["question"]["stage"] == "subject"
    game.submit_answer(subject, 1, clock(1))  # «Montaña»
    assert game.current.stage == "guess"
    assert game.tv_view()["question"]["stage"] == "guess"
    game.submit_answer(friend_ok, 1, clock(1))
    game.submit_answer(friend_bad, 2, clock(1))
    game.tick(clock())
    assert game.phase == E.REVEAL
    res = game.current.results
    assert res[friend_ok].correct and res[friend_ok].points == E.GUESS_POINTS
    assert not res[friend_bad].correct and res[friend_bad].points == 0
    assert res[subject].points == E.SUBJECT_HIT - E.SUBJECT_MISS
    assert res[subject].correct and res[subject].steps == E.STEPS_CORRECT  # half guessed right
    assert game.players[subject].points == E.SUBJECT_HIT - E.SUBJECT_MISS
    reveal = game.tv_view()["reveal"]
    assert reveal["solution"]["index"] == 1 and reveal["subject"] == subject and not reveal["void"]


def test_subject_loses_but_not_below_zero(registry: TypeRegistry, clock: Clock) -> None:
    game, ids = started(registry, clock)
    subject = ask_about_chooser(game, clock)
    game.players[subject].points = 30
    game.submit_answer(subject, 0, clock(1))
    for pid in ids:
        if pid != subject:
            game.submit_answer(pid, 2, clock(1))
    game.tick(clock())
    res = game.current.results[subject]
    assert res.points == -30 and not res.correct and res.steps == 0
    assert game.players[subject].points == 0


def test_friend_without_answer_does_not_count(registry: TypeRegistry, clock: Clock) -> None:
    game, ids = started(registry, clock)
    subject = ask_about_chooser(game, clock)
    friend, silent = [p for p in ids if p != subject]
    game.submit_answer(subject, 0, clock(1))
    game.submit_answer(friend, 0, clock(1))
    game.tick(clock(20))
    assert game.phase == E.REVEAL
    assert game.current.results[subject].points == E.SUBJECT_HIT
    assert not game.current.results[silent].answered


def test_subject_out_of_time_voids_with_penalty(registry: TypeRegistry, clock: Clock) -> None:
    game, ids = started(registry, clock)
    subject = ask_about_chooser(game, clock)
    game.players[subject].points = 200
    game.tick(clock(10 + E.ANSWER_GRACE + 0.1))
    assert game.phase == E.REVEAL and game.current.void == "timeout"
    assert game.players[subject].points == 200 - E.SUBJECT_TIMEOUT
    for pid in ids:
        if pid != subject:
            assert game.current.results[pid].exempt
    assert game.tv_view()["reveal"]["solution"]["index"] is None
    game.tick(clock(game.timing.reveal))
    assert game.phase == E.BOARD


def test_subject_leaving_voids_without_penalty(registry: TypeRegistry, clock: Clock) -> None:
    game, ids = started(registry, clock)
    subject = ask_about_chooser(game, clock)
    game.remove(subject, subject, clock())
    game.tick(clock())
    assert game.phase == E.REVEAL and game.current.void == "gone"


def test_not_offered_without_friends(registry: TypeRegistry, clock: Clock) -> None:
    game, _ = started(registry, clock, players=1)
    assert game.offered == ["t"]


def test_never_used_for_tiebreaks(registry: TypeRegistry, clock: Clock) -> None:
    game, ids = started(registry, clock)
    game._start_tiebreak(ids[:2], clock())
    game.tick(clock(game.timing.tiebreak_intro))
    assert game.current and not game.current.question.about_chooser
