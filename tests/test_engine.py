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
    game.settings.mechanics = ["eleccion"]  # deterministic: the flow tests pick from the offered list
    return game, ids


def act(game: Game, clock: Clock, cat: str | None = None) -> None:
    """Drive whatever mechanic is active: wait out the intro, act, wait out the animation."""
    ch = game.choice
    assert ch is not None
    clock(max(0.0, ch["introUntil"] - clock()) + 0.01)
    if ch["mechanic"] in ("ruleta", "moneda"):
        game.spin(ch["actorId"], clock())
    else:
        game.choose(ch["actorId"], cat if cat in ch["offered"] else ch["offered"][0], clock())
    game.tick(clock(ch["revealUntil"] - clock() + 0.01))


def plain(game: Game) -> None:
    game.board = Board([START] + ["normal"] * 27)


def play(game: Game, clock: Clock, answers: dict[str, int | None], at: float = 1.0, cat: str | None = None) -> None:
    """Play one full question from CHOOSING until the next CHOOSING/FINISHED/TIEBREAK."""
    assert game.phase == E.CHOOSING, game.phase
    act(game, clock, cat)
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
    act(game, clock)
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
        act(game, clock)
        asked.append(game.current.question.key)
        game.tick(clock())
        game.submit_answer(a, 1, clock(1))
        game.tick(clock())
        game.tick(clock(10))
        game.tick(clock(30))
    assert asked[0] != asked[1]
    assert any("agotado" in entry["text"] for entry in game.log)


def test_eleccion_offers_three(registry: TypeRegistry, clock: Clock) -> None:
    game, (a,) = new_game(registry, players=1, cats=5)
    game.start(a, clock())
    assert game.choice["mechanic"] == "eleccion" and len(game.offered) == 3
    assert len(set(game.offered)) == 3 and set(game.phone_view(a)["offered"]) == set(game.offered)


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
    game.afk_ignored.add(a)  # the match would pause by itself after a few seconds away
    game.tick(clock(E.CHOICE_INTRO + 0.1))  # the engine picks as soon as the announcement is over
    game.tick(clock(E.PICK_REVEAL + 0.1))
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
    act(game, clock)
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


def test_sound_settings_change_during_the_game(registry: TypeRegistry, clock: Clock) -> None:
    game, (host, other) = new_game(registry)
    game.start(host, clock())
    game.set_settings(host, {"music": False, "volume": 250})
    assert game.settings.music is False and game.settings.volume == 100
    with pytest.raises(GameError):
        game.set_settings(host, {"rounds": 5})  # game options stay locked mid-game
    with pytest.raises(GameError):
        game.set_settings(other, {"music": True})  # only the host
    with pytest.raises(GameError):
        game.set_settings(host, {"sfx": "si"})
    assert game.settings.public()["music"] is False
    game.set_settings(host, {"track": "algo.mp3"})  # also allowed while playing
    assert game.settings.public()["track"] == "algo.mp3"
    game.set_settings(host, {"music": True})  # a paused TV does not play, so it never reports an end
    play = game.settings.track_play
    assert not game.next_track("otra.mp3", play, "x.mp3")  # not the song that is playing
    assert not game.next_track("algo.mp3", play - 1, "x.mp3")  # an older start of it
    assert game.next_track("algo.mp3", play, "x.mp3")
    assert game.settings.track == "x.mp3" and game.settings.track_play == play + 1
    game.set_settings(host, {"musicVolume": 300})
    assert game.settings.music_volume == 100
    game.set_settings(host, {"musicVolume": 35})
    assert game.settings.public()["musicVolume"] == 35
    with pytest.raises(GameError):
        game.set_settings(host, {"musicVolume": "alto"})
    with pytest.raises(GameError):
        game.set_settings(other, {"musicVolume": 10})
    assert not game.next_track("algo.mp3", play, "y.mp3")  # a second TV reporting the same end
    with pytest.raises(GameError):
        game.set_settings(host, {"track": 5})


def test_save_and_resume_keeps_the_match(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.settings.rounds = 5
    game.start(a, clock())
    plain(game)
    play(game, clock, {a: 0, b: 1})  # a correct, b wrong
    points, position = game.players[a].points, game.players[a].position
    assert points > 0 and position > 0
    act(game, clock)  # a question is open when saving
    game.tick(clock())
    assert game.phase == E.ANSWERING
    chooser = game.chooser_id

    snapshot = game.save_and_exit(a, clock())
    assert game.phase == E.LOBBY and game.saved is snapshot
    assert game.players[a].points == 0  # the lobby is clean
    assert game.saved_summary()["players"] == ["Jugador 0", "Jugador 1"]

    game.resume(a, clock())
    assert game.phase == E.CHOOSING and game.saved is None
    assert game.chooser_id == chooser  # the dropped question is picked again by the same player
    assert (game.players[a].points, game.players[a].position) == (points, position)
    assert game.settings.rounds == 5 and game.board.spaces == snapshot["board"]
    json.dumps(snapshot)  # must be storable


def test_resume_restores_absent_players_and_adds_new_ones(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    play(game, clock, {a: 0, b: 0})
    snapshot = game.save_and_exit(a, clock())
    token_b = game.players[b].token

    fresh, (a2,) = new_game(registry, players=1)  # a server restart: only the host is back
    fresh.saved = json.loads(json.dumps(snapshot))
    fresh.players[a2].id  # new id: not the saved one
    fresh.join("Nuevo", C[5], ICON, clock())
    fresh.resume(a2, clock())
    assert b in fresh.players and not fresh.players[b].connected
    assert fresh.reconnect(token_b).id == b  # the old phone gets its player back
    assert any(p.name == "Nuevo" and p.points == 0 for p in fresh.players.values())


def test_cannot_save_without_a_match(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    with pytest.raises(GameError):
        game.save_and_exit(a, clock())
    with pytest.raises(GameError):
        game.resume(a, clock())
    game.start(a, clock())
    with pytest.raises(GameError):
        game.save_and_exit(b, clock())  # only the host


# ----- leaving, coming back, pause, late join --------------------------------------

def started(registry: TypeRegistry, clock: Clock, players: int = 3):
    game, ids = new_game(registry, players=players)
    plain(game)
    game.start(ids[0], clock())
    return game, ids


def test_leaving_keeps_the_state_out_of_the_ranking(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = started(registry, clock)
    game.players[b].points, game.players[b].position = 300, 5
    game.remove(b, b, clock())
    assert b not in game.players and b not in game.ranking_ids()
    assert game.away[b].reason == "left"
    assert [x["id"] for x in game.tv_view()["away"]] == [b]
    back = game.reclaim(b)
    assert (back.points, back.position) == (300, 5) and b in game.ranking_ids()
    assert not game.away


def test_kicked_players_are_not_recognised_but_the_host_can_readmit(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = started(registry, clock)
    game.players[b].points = 120
    game.remove(b, a, clock())  # the host kicks b
    assert game.away[b].reason == "kicked"
    with pytest.raises(GameError):
        game.reclaim(b)
    with pytest.raises(GameError):
        game.readmit(c, b)  # only the host
    game.readmit(a, b)
    assert game.players[b].points == 120 and not game.players[b].connected  # its phone reconnects by token


def test_reserved_seats_count_and_the_host_can_free_them(registry: TypeRegistry, clock: Clock) -> None:
    game, ids = started(registry, clock, players=6)
    game.remove(ids[5], ids[5], clock())
    with pytest.raises(GameError, match="reservadas"):
        game.join("Otro", "#e599f7", ICON, clock())
    game.forget_away(ids[0], ids[5])
    game.join("Otro", "#e599f7", ICON, clock())


def test_late_join_points_follow_the_host_rule(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = started(registry, clock, players=2)
    game.players[a].points, game.players[b].points = 100, 300
    assert game.join("Cero", C[4], ICON, clock()).points == 0
    game.set_settings(a, {"lateJoin": "average"})
    assert game.join("Media", C[5], ICON, clock()).points == round((100 + 300 + 0) / 3)
    game.set_settings(a, {"lateJoin": "fixed", "latePoints": 250})
    game.remove(game.order[-1], game.order[-1], clock())
    assert game.join("Fijo", C[6], ICON, clock()).points == 250
    with pytest.raises(GameError):
        game.set_settings(a, {"lateJoin": "otra"})


def test_pause_freezes_the_clock_for_everyone(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = started(registry, clock, players=2)
    act(game, clock)
    game.tick(clock())
    assert game.phase == E.ANSWERING
    deadline = game.current.deadline
    game.pause(b, clock())  # not the host: anyone can
    assert game.paused and game.paused_by == b
    paused_at = clock()
    game.tick(clock(50))  # far beyond the deadline
    assert game.phase == E.ANSWERING
    with pytest.raises(GameError, match="pausa"):
        game.submit_answer(a, 0, clock())
    resumed_at = clock()
    game.unpause(a, resumed_at)
    assert not game.paused and game.current.deadline == pytest.approx(deadline + (resumed_at - paused_at))
    game.submit_answer(a, 0, clock(1))


def test_host_change_is_announced(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = started(registry, clock)
    game.disconnect(a, clock())
    assert game.host_id == b
    assert any("anfitrión" in e["text"] and e["kind"] == "host" for e in game.log)
    game.set_host(b, c)
    assert game.host_id == c


def test_autosave_checkpoint_and_away_survive_a_roundtrip(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = started(registry, clock)
    assert game.checkpoint == "save"
    game.remove(c, c, clock())
    snap = json.loads(json.dumps(game.snapshot(clock(), game.chooser_id)))
    other, (x, y) = new_game(registry, players=2)
    other.load_saved(snap)
    assert c in other.away and other.away_reason(snap["players"][-1]["token"]) == "left"
    other.resume(other.host_id or x, clock())
    assert c in other.away and c not in other.players
    other.reclaim(c)
    assert c in other.players


def test_afk_phone_pauses_the_match_and_only_the_host_resumes(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = started(registry, clock)  # a is the host
    act(game, clock)
    game.tick(clock())
    game.presence(c, clock(), True)  # c sends heartbeats from now on
    game.presence(c, clock(1), False)  # ...and locks the phone
    game.tick(clock(2))
    assert not game.paused  # grace period
    game.tick(clock(3))
    assert game.paused and game.paused_reason == "afk" and c in game.tv_view()["afk"]
    with pytest.raises(GameError):
        game.unpause(b, clock())  # not the host
    game.unpause(a, clock())
    assert not game.paused
    game.tick(clock(30))
    assert not game.paused  # the host chose to go on without c


def test_returning_phone_and_dropped_connection(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = started(registry, clock)
    game.presence(b, clock(), False)
    game.presence(b, clock(1), True)  # back before the grace period ends
    game.tick(clock(10))
    assert not game.paused
    game.disconnect(c, clock())  # closed the tab
    game.tick(clock(5))
    assert game.paused and game.paused_reason == "afk"
    token = game.players[c].token
    game.reconnect(token)
    assert c not in game.tv_view()["afk"] and game.paused  # still paused until the host resumes
    game.unpause(a, clock())
    assert not game.paused


def test_silent_heartbeat_counts_as_away_but_phones_without_one_do_not(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = started(registry, clock, players=2)
    game.tick(clock(60))  # nobody ever sent a ping: bots and old clients are never flagged
    assert not game.paused
    game.presence(b, clock(), None)
    game.tick(clock(E.HEARTBEAT_TIMEOUT + E.AFK_GRACE + 1))
    assert game.paused and game.paused_reason == "afk"


def test_manual_pause_can_be_resumed_by_who_paused_it(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = started(registry, clock)
    game.pause(b, clock())
    with pytest.raises(GameError):
        game.unpause(c, clock())
    game.unpause(b, clock())
    assert not game.paused


# ----- category mechanics (docs/mecanicas-categoria.md) -----------------------

def begin(registry: TypeRegistry, clock: Clock, mechanic: str, players: int = 2, **kw) -> tuple[Game, list[str]]:
    game, ids = new_game(registry, players=players, **kw)
    game.settings.mechanics = [mechanic]
    game.start(ids[0], clock())
    plain(game)
    assert game.choice["mechanic"] == mechanic
    return game, ids


def test_ruleta(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = begin(registry, clock, "ruleta")
    ch = game.choice
    assert ch["actorId"] == a and ch["chooserId"] == a and sorted(ch["offered"]) == ["c0", "c1", "c2"]
    with pytest.raises(GameError, match="Espera"):
        game.spin(a, clock())  # still in the intro
    clock(E.CHOICE_INTRO + 0.1)
    with pytest.raises(GameError, match="turno"):
        game.spin(b, clock())
    with pytest.raises(GameError, match="mecánica"):
        game.choose(a, "c0", clock())
    game.spin(a, clock())
    ch = game.choice
    assert ch["result"] in ch["offered"] and ch["revealUntil"] == pytest.approx(ch["spinAt"] + E.WHEEL_TIME)
    assert game.deadline == ch["revealUntil"] and game.phase == E.CHOOSING
    assert game.phone_view(b)["choice"]["result"] == ch["result"] == game.tv_view()["choice"]["result"]
    with pytest.raises(GameError, match="Ya se ha"):
        game.spin(a, clock())
    assert game.log[-1]["text"].startswith("Ruleta: sale")
    game.tick(clock(E.WHEEL_TIME - 1))
    assert game.phase == E.CHOOSING
    game.tick(clock(1.1))
    assert game.phase in (E.READING, E.ANSWERING) and game.current.category.id == ch["result"]
    assert game.last_chooser == a and a in game.chosen_this_round


def test_moneda_uses_best_and_worst_from_stats(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = begin(registry, clock, "moneda")
    p = game.players[a]
    p.asked, p.right = {"c0": 4, "c1": 4, "c2": 4}, {"c0": 4, "c1": 0, "c2": 2}
    game._begin_choosing(a, clock())
    ch = game.choice
    assert ch["offered"] == ["c0", "c1"]  # best 5/6, worst 1/6
    assert ch["stats"] == {"cara": 1.0, "cruz": 0.0}
    clock(E.CHOICE_INTRO + 0.1)
    game.spin(a, clock())
    assert ch["outcome"] in ("cara", "cruz")
    assert ch["result"] == ("c0" if ch["outcome"] == "cara" else "c1")
    assert ch["revealUntil"] == pytest.approx(ch["spinAt"] + E.COIN_TIME)
    assert game.log[-1]["text"].startswith(f"Cara o cruz ({ch['outcome']}): ")
    game.tick(clock(E.COIN_TIME + 0.1))
    assert game.current.category.id == ch["result"]


def test_moneda_without_data_gives_two_distinct_categories(registry: TypeRegistry, clock: Clock) -> None:
    for seed in range(10):
        game, (a, b) = new_game(registry, cats=4)
        game.rng = Random(seed)
        game.settings.mechanics = ["moneda"]
        game.start(a, clock())
        cara, cruz = game.choice["offered"]
        assert cara != cruz and game.choice["stats"] == {"cara": None, "cruz": None}


def test_stats_count_asked_and_right_per_category(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.start(a, clock())
    plain(game)
    play(game, clock, {a: 0, b: 1}, cat="c1")
    pa, pb = game.players[a], game.players[b]
    assert pa.asked == {"c1": 1} and pb.asked == {"c1": 1}
    assert pa.right == {"c1": 1} and pb.right == {}
    snap = json.loads(json.dumps(game.snapshot(clock(), game.chooser_id)))
    other, (x, y) = new_game(registry)
    other.load_saved(snap)
    other.resume(x, clock())
    assert other.players[a].asked == {"c1": 1} and other.players[a].right == {"c1": 1}


def test_rival_chooses_for_the_chooser(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = begin(registry, clock, "rival", players=3)
    ch = game.choice
    assert ch["chooserId"] == a and ch["actorId"] in (b, c) and len(ch["offered"]) == 3
    rival = ch["actorId"]
    assert game.phone_view(rival)["offered"] == ch["offered"] and game.phone_view(a)["offered"] == []
    with pytest.raises(GameError, match="Espera"):
        game.choose(rival, "c1", clock())
    clock(E.CHOICE_INTRO + 0.1)
    with pytest.raises(GameError, match="turno"):
        game.choose(a, "c1", clock())  # the chooser does not pick
    with pytest.raises(GameError, match="disponible"):
        game.choose(rival, "__random__", clock())
    game.choose(rival, "c1", clock())
    assert ch["result"] == "c1" and ch["revealUntil"] == pytest.approx(ch["spinAt"] + E.PICK_REVEAL)
    assert game.log[-1]["text"] == f"{game.players[rival].name} elige por {game.players[a].name}: ❓ Cat 1"
    game.tick(clock(E.PICK_REVEAL + 0.1))
    assert game.current.category.id == "c1"
    assert game.last_chooser == a and a in game.chosen_this_round and rival not in game.chosen_this_round


def test_eleccion_rules(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = begin(registry, clock, "eleccion", cats=5)
    other = next(c for c in ("c0", "c1", "c2", "c3", "c4") if c not in game.offered)
    clock(E.CHOICE_INTRO + 0.1)
    with pytest.raises(GameError, match="disponible"):
        game.choose(a, other, clock())
    with pytest.raises(GameError, match="turno"):
        game.choose(b, game.offered[0], clock())
    with pytest.raises(GameError, match="mecánica"):
        game.spin(a, clock())
    game.choose(a, game.offered[0], clock())
    assert game.log[-1]["text"] == f"Jugador 0 elige ❓ Cat {game.choice['result'][1]}"
    with pytest.raises(GameError, match="Ya se ha"):
        game.choose(a, game.offered[0], clock())


def test_rival_needs_another_connected_player(registry: TypeRegistry, clock: Clock) -> None:
    for seed in range(15):
        game, (a, b) = new_game(registry)
        game.rng = Random(seed)
        game.settings.mechanics = list(E.MECHANICS)
        game.disconnect(b, clock())
        game.start(a, clock())
        assert game.choice["mechanic"] != "rival"
        game, (a,) = new_game(registry, players=1)
        game.rng = Random(seed)
        game.settings.mechanics = ["rival", "eleccion"]
        game.start(a, clock())
        assert game.choice["mechanic"] == "eleccion"


def test_single_category_always_uses_eleccion(registry: TypeRegistry, clock: Clock) -> None:
    for seed in range(15):
        game, (a, b) = new_game(registry, cats=1)
        game.rng = Random(seed)
        game.settings.mechanics = list(E.MECHANICS)
        game.start(a, clock())
        assert game.choice["mechanic"] in ("eleccion", "rival") and game.choice["offered"] == ["c0"]
    game, (a, b) = new_game(registry, cats=1)
    game.settings.mechanics = ["ruleta", "moneda"]
    game.start(a, clock())
    assert game.choice["mechanic"] == "eleccion"


@pytest.mark.parametrize("mechanic", E.MECHANICS)
def test_timeout_acts_for_the_actor(registry: TypeRegistry, clock: Clock, mechanic: str) -> None:
    game, ids = begin(registry, clock, mechanic, players=3)
    ch = game.choice
    game.tick(clock(E.CHOICE_INTRO + game.timing.choose - 1))
    assert ch["result"] is None  # still waiting for the actor
    game.tick(clock(1.1))
    assert ch["result"] in ch["offered"] and game.phase == E.CHOOSING
    assert game.log[-1]["text"].endswith("(al azar: se acabó el tiempo)")
    game.tick(clock(E.COIN_TIME + E.WHEEL_TIME))
    assert game.phase in (E.READING, E.ANSWERING) and game.current.category.id == ch["result"]


@pytest.mark.parametrize("mechanic", ["ruleta", "rival"])
def test_actor_disconnect_acts_after_a_moment(registry: TypeRegistry, clock: Clock, mechanic: str) -> None:
    game, ids = begin(registry, clock, mechanic, players=3)
    ch = game.choice
    game.afk_ignored.update(ids)
    clock(E.CHOICE_INTRO + 0.1)
    game.disconnect(ch["actorId"], clock())
    assert game.deadline == pytest.approx(clock() + 1.5)
    game.tick(clock(1.4))
    assert ch["result"] is None
    game.tick(clock(0.2))
    assert ch["result"] is not None


def test_pause_freezes_the_choice(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = begin(registry, clock, "ruleta")
    game.pause(b, clock())
    game.tick(clock())
    game.tick(clock(200))
    assert game.choice["result"] is None
    game.unpause(a, clock())
    game.tick(clock(E.CHOICE_INTRO + game.timing.choose + 1))
    assert game.choice["result"] is not None


def test_toggle_mechanic(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = new_game(registry)
    game.settings.mechanics = list(E.MECHANICS)
    assert game.tv_view()["settings"]["mechanics"] == list(E.MECHANICS)
    game.set_settings(a, {"toggleMechanic": "moneda"})
    assert game.settings.mechanics == ["ruleta", "rival", "eleccion"]
    game.set_settings(a, {"toggleMechanic": "moneda"})
    assert game.settings.mechanics == list(E.MECHANICS)
    for m in ("ruleta", "moneda", "rival"):
        game.set_settings(a, {"toggleMechanic": m})
    with pytest.raises(GameError, match="al menos una"):
        game.set_settings(a, {"toggleMechanic": "eleccion"})
    with pytest.raises(GameError):
        game.set_settings(a, {"toggleMechanic": "nada"})
    game.start(a, clock())
    with pytest.raises(GameError, match="antes de empezar"):
        game.set_settings(a, {"toggleMechanic": "ruleta"})


def test_old_save_with_categories_per_turn_loads(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b) = started(registry, clock, players=2)
    snap = json.loads(json.dumps(game.snapshot(clock(), game.chooser_id)))
    snap["settings"].pop("mechanics")
    snap["settings"]["categoriesPerTurn"] = 2
    for p in snap["players"]:
        p.pop("catAsked"), p.pop("catRight")
    other, (x, y) = new_game(registry)
    other.load_saved(snap)
    other.resume(x, clock())
    assert other.phase == E.CHOOSING and other.settings.mechanics == list(E.MECHANICS)
    assert other.players[x].asked == {}
    other.back_to_lobby(x)
    other.set_settings(x, {"categoriesPerTurn": 3})  # unknown keys are ignored
    assert "categoriesPerTurn" not in other.settings.public()


def test_every_phone_gets_the_categories_while_choosing(registry: TypeRegistry, clock: Clock) -> None:
    game, (a, b, c) = begin(registry, clock, "rival", players=3)
    for pid in (a, b, c):
        assert len(game.phone_view(pid)["categories"]) == 3
    assert set(game.tv_view()["choice"]) == {
        "mechanic", "chooserId", "actorId", "offered", "introUntil", "spinAt", "revealUntil",
        "result", "outcome", "stats",
    }
