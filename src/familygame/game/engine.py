"""Game state machine.

Pure logic: no sockets, no clock. Every method that depends on time receives
``now`` (seconds, wall clock) so the whole flow can be tested quickly.

Phases::

    lobby -> choosing -> reading -> answering -> reveal -> board -> choosing ...
                                                     \\-> finished
    tie at the end -> tiebreak (intro) -> reading -> answering -> reveal -> ...
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from random import Random
from typing import Any, Iterable

from familygame.categories import Category, CategoryLibrary
from familygame.config import TimingConfig
from familygame.game.board import DUEL, EVENT, STAR, Board
from familygame.game.picker import QuestionHistory, pick_question
from familygame.game.players import PALETTE, PALETTE_COLORS, Player, clean_name, name_key
from familygame.questions.base import AnswerError, Evaluation, QuestionType

LOBBY, CHOOSING, READING, ANSWERING = "lobby", "choosing", "reading", "answering"
REVEAL, BOARD, TIEBREAK, FINISHED = "reveal", "board", "tiebreak", "finished"
PLAYING_PHASES = (CHOOSING, READING, ANSWERING, REVEAL, BOARD, TIEBREAK)

MODES = ("points", "rounds", "categories")
RANDOM_CATEGORY = "__random__"

SPEED_BONUS = 0.5      # up to +50 % of base points for answering instantly
STEPS_CORRECT = 2
STEPS_FASTEST = 1
CLOSE_BONUS = 100      # points for closing a category
START_BONUS = 50       # points for passing the start
DUEL_STEAL = 50
EVENT_PLUS, EVENT_MINUS, EVENT_STEAL = 60, 40, 40
MAX_TIEBREAKS = 3
ANSWER_GRACE = 0.6     # seconds of network latency accepted after the deadline


class GameError(Exception):
    """An action that is not allowed; the message is shown to the player."""


@dataclass
class Settings:
    """Options the host picks in the lobby."""

    mode: str = "points"
    target_points: int = 1500
    rounds: int = 3
    categories_to_close: int = 3
    hits_to_close: int = 3
    categories_per_turn: int = 0
    disabled: set[str] = field(default_factory=set)

    def public(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "targetPoints": self.target_points,
            "rounds": self.rounds,
            "categoriesToClose": self.categories_to_close,
            "hitsToClose": self.hits_to_close,
            "categoriesPerTurn": self.categories_per_turn,
            "disabled": sorted(self.disabled),
        }


@dataclass
class Answer:
    """One player's submitted answer."""

    value: Any
    display: Any
    elapsed: float
    evaluation: Evaluation


@dataclass
class Result:
    """What one player got from one question."""

    answered: bool = False
    exempt: bool = False
    correct: bool = False
    points: int = 0
    bonus: int = 0
    steps: int = 0
    fastest: bool = False
    doubled: bool = False
    closed: str = ""
    detail: str = ""
    duel: str = ""
    elapsed: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "answered": self.answered,
            "exempt": self.exempt,
            "correct": self.correct,
            "points": self.points,
            "bonus": self.bonus,
            "steps": self.steps,
            "fastest": self.fastest,
            "doubled": self.doubled,
            "closed": self.closed,
            "detail": self.detail,
            "duel": self.duel,
            "elapsed": None if self.elapsed is None else round(self.elapsed, 2),
        }


@dataclass
class AskedQuestion:
    """A question currently being played."""

    number: int
    category: Category
    question: QuestionType
    state: dict[str, Any]
    chooser_id: str | None
    open_at: float
    deadline: float
    participants: list[str]
    tiebreak: bool = False
    answers: dict[str, Answer] = field(default_factory=dict)
    exempt: set[str] = field(default_factory=set)
    star_players: set[str] = field(default_factory=set)
    duels: list[tuple[str, str]] = field(default_factory=list)
    results: dict[str, Result] = field(default_factory=dict)


class Game:
    """One room: players, settings and the running match."""

    def __init__(
        self,
        library: CategoryLibrary,
        *,
        timing: TimingConfig | None = None,
        history: QuestionHistory | None = None,
        rng: Random | None = None,
        icons: Iterable[str] = (),
        max_players: int = 6,
    ) -> None:
        self.library = library
        self.timing = timing or TimingConfig()
        self.history = history or QuestionHistory()
        self.rng = rng or Random()
        self.icons = set(icons)
        self.max_players = max_players
        self.players: dict[str, Player] = {}
        self.order: list[str] = []
        self.settings = Settings()
        self.version = 0
        self.log: list[dict[str, Any]] = []
        self._log_id = 0
        self._last_tick: float | None = None
        self._reset_match()

    # ------------------------------------------------------------------ helpers

    def _reset_match(self) -> None:
        self.phase = LOBBY
        self.board = Board.generate(self.rng)
        self.used: set[str] = set()
        self.round_no = 1
        self.question_no = 0
        self.chosen_this_round: set[str] = set()
        self.last_chooser: str | None = None
        self.chooser_id: str | None = None
        self.offered: list[str] = []
        self.deadline: float | None = None
        self.current: AskedQuestion | None = None
        self.pending_duels: list[tuple[str, str]] = []
        self.moves: list[dict[str, Any]] = []
        self.tiebreak_players: list[str] = []
        self.tiebreak_attempt = 0
        self.winners: list[str] = []
        for player in self.players.values():
            player.reset_scores()

    def _touch(self) -> None:
        self.version += 1

    def _say(self, text: str, player: str | None = None, kind: str = "info") -> None:
        self._log_id += 1
        self.log.append({"id": self._log_id, "text": text, "player": player, "kind": kind})
        del self.log[:-20]
        self._touch()

    def _player(self, pid: str) -> Player:
        try:
            return self.players[pid]
        except KeyError as exc:
            raise GameError("No estás en la partida") from exc

    def _connected(self) -> list[Player]:
        return [self.players[pid] for pid in self.order if self.players[pid].connected]

    @property
    def host_id(self) -> str | None:
        """First connected player (by join order) controls the game."""
        connected = self._connected()
        return connected[0].id if connected else None

    def _require_host(self, pid: str) -> None:
        if pid != self.host_id:
            raise GameError("Solo el anfitrión puede hacer esto")

    def enabled_categories(self) -> list[Category]:
        """Playable categories the host has not switched off."""
        return [c for c in self.library.playable() if c.id not in self.settings.disabled]

    # ------------------------------------------------------------------ players

    def taken_colors(self, except_pid: str | None = None) -> set[str]:
        return {p.color for p in self.players.values() if p.id != except_pid}

    def _validate_profile(
        self, name: Any, color: Any, avatar: Any, except_pid: str | None = None
    ) -> tuple[str, str, dict[str, Any]]:
        clean = clean_name(name)
        if not clean:
            raise GameError("Escribe un nombre")
        key = name_key(clean)
        for other in self.players.values():
            if other.id != except_pid and name_key(other.name) == key:
                raise GameError(f"Ya hay alguien llamado «{other.name}». Elige otro nombre.")
        if color not in PALETTE_COLORS:
            raise GameError("Elige un color de la paleta")
        if color in self.taken_colors(except_pid):
            raise GameError("Ese color ya lo tiene otro jugador")
        if not isinstance(avatar, dict) or avatar.get("kind") not in ("icon", "photo"):
            raise GameError("Elige un icono o una foto")
        if avatar["kind"] == "icon":
            icon = avatar.get("value")
            if not isinstance(icon, str) or (self.icons and icon not in self.icons):
                raise GameError("Icono no válido")
            avatar = {"kind": "icon", "value": icon}
        else:
            avatar = {"kind": "photo", "url": ""}
        return clean, color, avatar

    def join(self, name: Any, color: Any, avatar: Any, now: float) -> Player:
        """Add a new player (also allowed mid-game while there is room).

        Raises:
            GameError: Full room, repeated name, taken colour or bad avatar.
        """
        if len(self.players) >= self.max_players:
            raise GameError(f"La partida está llena (máximo {self.max_players})")
        clean, color, avatar = self._validate_profile(name, color, avatar)
        pid = secrets.token_hex(4)
        while pid in self.players:
            pid = secrets.token_hex(4)
        player = Player(pid, secrets.token_urlsafe(18), clean, color, avatar)
        self.players[pid] = player
        self.order.append(pid)
        self._say(f"{clean} se ha unido", pid, "join")
        return player

    def set_photo(self, pid: str, version: int) -> None:
        """Point the avatar to the uploaded photo (stored by the server)."""
        player = self._player(pid)
        player.photo_version = version
        player.avatar = {"kind": "photo", "url": f"/avatar/{pid}?v={version}"}
        self._touch()

    def update_profile(self, pid: str, name: Any, color: Any, avatar: Any) -> Player:
        """Change name/colour/avatar; only between games."""
        if self.phase not in (LOBBY, FINISHED):
            raise GameError("El perfil solo se puede cambiar fuera de la partida")
        player = self._player(pid)
        clean, color, new_avatar = self._validate_profile(name, color, avatar, pid)
        player.name, player.color = clean, color
        if new_avatar["kind"] == "icon":
            player.avatar = new_avatar
        self._touch()
        return player

    def reconnect(self, token: str) -> Player | None:
        """Find the player owning ``token`` and mark them connected."""
        for player in self.players.values():
            if secrets.compare_digest(player.token, token):
                if not player.connected:
                    player.connected = True
                    self._say(f"{player.name} ha vuelto", player.id, "join")
                return player
        return None

    def disconnect(self, pid: str, now: float) -> None:
        """A phone closed its connection; the player stays in the game."""
        player = self.players.get(pid)
        if player is None or not player.connected:
            return
        player.connected = False
        self._say(f"{player.name} se ha desconectado", pid, "leave")
        if self.phase == CHOOSING and self.chooser_id == pid:
            self.deadline = min(self.deadline or now, now + 2)

    def remove(self, pid: str, by: str | None, now: float) -> None:
        """Kick (by the host) or leave voluntarily (``by == pid``)."""
        if by != pid:
            self._require_host(by or "")
        player = self._player(pid)
        del self.players[pid]
        self.order.remove(pid)
        self.chosen_this_round.discard(pid)
        self.pending_duels = [d for d in self.pending_duels if pid not in d]
        self.tiebreak_players = [p for p in self.tiebreak_players if p != pid]
        if self.current:
            if pid in self.current.participants:
                self.current.participants.remove(pid)
            self.current.answers.pop(pid, None)
        self.winners = [w for w in self.winners if w != pid]
        if self.last_chooser == pid:
            self.last_chooser = None
        self._say(f"{player.name} ha salido de la partida", None, "leave")
        if self.phase == CHOOSING and self.chooser_id == pid:
            self.chooser_id = None
            self.deadline = now + 1.5

    # ------------------------------------------------------------------ lobby

    def set_settings(self, pid: str, changes: dict[str, Any]) -> None:
        """Host changes lobby options. Unknown keys are ignored."""
        self._require_host(pid)
        if self.phase not in (LOBBY, FINISHED):
            raise GameError("Las opciones se cambian antes de empezar")
        s = self.settings

        def number(key: str, low: int, high: int) -> int | None:
            if key not in changes:
                return None
            value = changes[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise GameError(f"Valor no válido para {key}")
            return max(low, min(high, int(value)))

        if "mode" in changes:
            if changes["mode"] not in MODES:
                raise GameError("Modo de juego desconocido")
            s.mode = changes["mode"]
        if (v := number("targetPoints", 100, 100_000)) is not None:
            s.target_points = v
        if (v := number("rounds", 1, 30)) is not None:
            s.rounds = v
        if (v := number("categoriesToClose", 1, 50)) is not None:
            s.categories_to_close = v
        if (v := number("hitsToClose", 1, 10)) is not None:
            s.hits_to_close = v
        if (v := number("categoriesPerTurn", 0, 12)) is not None:
            s.categories_per_turn = v
        if "toggleCategory" in changes:
            cid = changes["toggleCategory"]
            if cid not in self.library.categories:
                raise GameError("Categoría desconocida")
            s.disabled.symmetric_difference_update({cid})
        if "disabled" in changes:
            ids = changes["disabled"]
            if not isinstance(ids, list):
                raise GameError("Lista de categorías no válida")
            s.disabled = {c for c in ids if c in self.library.categories}
        self._touch()

    def set_library(self, library: CategoryLibrary) -> None:
        """Swap the questions (after reloading files). Only in the lobby."""
        if self.phase not in (LOBBY, FINISHED):
            raise GameError("Las preguntas se recargan fuera de la partida")
        self.library = library
        self.settings.disabled &= set(library.categories)
        self._touch()

    def start(self, pid: str, now: float) -> None:
        """Host starts the match.

        Raises:
            GameError: Not host, no categories, or impossible target.
        """
        self._require_host(pid)
        if self.phase not in (LOBBY, FINISHED):
            raise GameError("La partida ya ha empezado")
        enabled = self.enabled_categories()
        if not enabled:
            raise GameError("No hay ninguna categoría activa con preguntas")
        if self.settings.mode == "categories" and self.settings.categories_to_close > len(enabled):
            raise GameError(
                f"Hay que cerrar {self.settings.categories_to_close} categorías pero solo "
                f"hay {len(enabled)} activas"
            )
        self._reset_match()
        self._say("¡Empieza la partida!", None, "start")
        self._begin_choosing(self._next_chooser(), now)

    def back_to_lobby(self, pid: str) -> None:
        """Host ends the match (or leaves the podium) and returns to the lobby."""
        self._require_host(pid)
        self._reset_match()
        self._say("De vuelta al lobby", None, "info")

    # ------------------------------------------------------------------ choosing

    def _next_chooser(self) -> str | None:
        """Next connected player, in join order, who has not chosen this round."""
        if not self.order:
            return None
        start = self.order.index(self.last_chooser) + 1 if self.last_chooser in self.order else 0
        for i in range(len(self.order)):
            pid = self.order[(start + i) % len(self.order)]
            if self.players[pid].connected and pid not in self.chosen_this_round:
                return pid
        return None

    def _offer_categories(self) -> list[str]:
        enabled = self.enabled_categories()
        available = [c for c in enabled if any(q.key not in self.used for q in c.questions)]
        if not available and enabled:
            self.used.clear()
            self._say("Se han agotado las preguntas: a partir de ahora se pueden repetir", None, "warn")
            available = enabled
        n = self.settings.categories_per_turn
        if n and len(available) > n:
            chosen = {c.id for c in self.rng.sample(available, n)}
            available = [c for c in available if c.id in chosen]
        return [c.id for c in available]

    def _begin_choosing(self, chooser: str | None, now: float) -> None:
        self.offered = self._offer_categories()
        if not self.offered:
            self._finish(self._ranking_ids()[:1], now)
            return
        self.phase = CHOOSING
        self.chooser_id = chooser
        self.current = None
        self.moves = []
        delay = self.timing.choose if chooser else 1.5
        self.deadline = now + delay
        self._touch()

    def choose(self, pid: str, category_id: str, now: float) -> None:
        """The current chooser picks a category (or RANDOM_CATEGORY)."""
        if self.phase != CHOOSING:
            raise GameError("Ahora no toca elegir categoría")
        if pid != self.chooser_id:
            raise GameError("No es tu turno de elegir")
        if category_id != RANDOM_CATEGORY and category_id not in self.offered:
            raise GameError("Esa categoría no está disponible")
        self._ask(category_id, now)

    def _ask(self, category_id: str, now: float) -> None:
        if category_id == RANDOM_CATEGORY:
            # uniform per category: one with 200 questions is not favoured over one with 10
            category_id = self.rng.choice(self.offered)
        category = self.library.categories[category_id]
        question = pick_question(category, self.used, self.history, self.rng)
        if question is None:  # defensive: category exhausted between offer and pick
            self.used -= {q.key for q in category.questions}
            question = pick_question(category, self.used, self.history, self.rng)
            assert question is not None
        participants = [p.id for p in self._connected()]
        self._start_question(category, question, participants, now, tiebreak=False)
        if self.chooser_id:
            self.chosen_this_round.add(self.chooser_id)
            self.last_chooser = self.chooser_id
            chooser = self.players.get(self.chooser_id)
            self._say(
                f"{chooser.name if chooser else 'Alguien'} elige {category.icon} {category.name}",
                self.chooser_id,
                "choose",
            )
        else:
            self._say(f"Categoría al azar: {category.icon} {category.name}", None, "choose")

    def _start_question(
        self,
        category: Category,
        question: QuestionType,
        participants: list[str],
        now: float,
        tiebreak: bool,
    ) -> None:
        self.used.add(question.key)
        self.history.mark(question.key, now)
        self.question_no += 0 if tiebreak else 1
        open_at = now + question.read_time
        asked = AskedQuestion(
            number=self.question_no,
            category=category,
            question=question,
            state=question.prepare(self.rng),
            chooser_id=None if tiebreak else self.chooser_id,
            open_at=open_at,
            deadline=open_at + question.time_limit,
            participants=participants,
            tiebreak=tiebreak,
        )
        if not tiebreak:
            asked.star_players = {
                pid for pid in participants
                if self.board.spaces[self.players[pid].position] == STAR
            }
            asked.duels = [d for d in self.pending_duels if d[0] in participants and d[1] in participants]
            self.pending_duels = []
        self.current = asked
        self.phase = READING
        self.deadline = open_at
        self._touch()

    # ------------------------------------------------------------------ answering

    def submit_answer(self, pid: str, raw: Any, now: float) -> None:
        """Store a player's answer (one per question, cannot be changed)."""
        cur = self.current
        if self.phase != ANSWERING or cur is None:
            raise GameError("Ahora no se puede responder")
        if pid not in cur.participants:
            raise GameError("No participas en esta pregunta")
        if pid in cur.answers or pid in cur.exempt:
            raise GameError("Ya has respondido")
        if now > cur.deadline + ANSWER_GRACE:
            raise GameError("¡Se acabó el tiempo!")
        try:
            value = cur.question.normalize_answer(raw, cur.state)
        except AnswerError as exc:
            raise GameError(str(exc)) from exc
        elapsed = max(0.0, min(now - cur.open_at, float(cur.question.time_limit)))
        cur.answers[pid] = Answer(
            value,
            cur.question.answer_for_display(value, cur.state),
            elapsed,
            cur.question.evaluate(value, cur.state),
        )
        self._touch()

    def report_unavailable(self, pid: str, now: float) -> None:
        """A phone could not show this question (e.g. map failed to load).

        The player is exempt: no points, no penalty, and the question does not
        count against them.
        """
        cur = self.current
        if self.phase not in (READING, ANSWERING) or cur is None or pid not in cur.participants:
            return
        if pid not in cur.answers and pid not in cur.exempt:
            cur.exempt.add(pid)
            self._say(f"{self.players[pid].name} no puede ver esta pregunta: no le cuenta", pid, "warn")

    def _everyone_answered(self) -> bool:
        cur = self.current
        assert cur is not None
        waiting = [
            pid for pid in cur.participants
            if pid not in cur.answers and pid not in cur.exempt
            and pid in self.players and self.players[pid].connected
        ]
        return not waiting

    # ------------------------------------------------------------------ scoring

    def _reveal(self, now: float) -> None:
        cur = self.current
        assert cur is not None
        q = cur.question
        correct_times = [a.elapsed for a in cur.answers.values() if a.evaluation.correct]
        fastest = min(correct_times) if correct_times else None
        for pid in cur.participants:
            player = self.players.get(pid)
            if player is None:
                continue
            res = Result()
            cur.results[pid] = res
            if pid in cur.exempt:
                res.exempt = True
                continue
            answer = cur.answers.get(pid)
            if not cur.tiebreak:
                player.asked_count += 1
            if answer is not None:
                res.answered = True
                res.correct = answer.evaluation.correct
                res.detail = answer.evaluation.detail
                res.elapsed = answer.elapsed
            if cur.tiebreak:
                continue
            if res.correct:
                speed = max(0.0, 1 - answer.elapsed / q.time_limit)
                res.points = q.base_points + round(q.base_points * SPEED_BONUS * speed)
                if player.double_next:
                    res.points *= 2
                    res.doubled = True
                res.fastest = answer.elapsed == fastest
                res.steps = STEPS_CORRECT + (STEPS_FASTEST if res.fastest else 0)
                player.correct_count += 1
                cat = cur.category.id
                player.progress[cat] = player.progress.get(cat, 0) + 1
                on_star = pid in cur.star_players
                if cat not in player.closed and (
                    on_star or player.progress[cat] >= self.settings.hits_to_close
                ):
                    player.closed.append(cat)
                    res.closed = cur.category.name
                    res.bonus += CLOSE_BONUS
                    how = "desde la estrella ★" if on_star else f"con {player.progress[cat]} aciertos"
                    self._say(
                        f"{player.name} cierra {cur.category.icon} {cur.category.name} {how}", pid, "close"
                    )
            player.double_next = False
            player.points += res.points + res.bonus
        if not cur.tiebreak:
            self._resolve_duels(cur)
        self.phase = REVEAL
        self.deadline = now + self.timing.reveal
        self._touch()

    def _duel_key(self, cur: AskedQuestion, pid: str) -> tuple[bool, float, float]:
        answer = cur.answers.get(pid)
        if answer is None:
            return (False, -1.0, 0.0)
        return (answer.evaluation.correct, answer.evaluation.closeness, -answer.elapsed)

    def _resolve_duels(self, cur: AskedQuestion) -> None:
        for a, b in cur.duels:
            pa, pb = self.players.get(a), self.players.get(b)
            if pa is None or pb is None or a in cur.exempt or b in cur.exempt:
                continue
            ka, kb = self._duel_key(cur, a), self._duel_key(cur, b)
            if ka == kb or not (ka[0] or kb[0]):
                text = f"⚔ Duelo {pa.name} – {pb.name}: nadie gana"
            else:
                winner, loser = (pa, pb) if ka > kb else (pb, pa)
                stolen = min(DUEL_STEAL, loser.points)
                winner.points += stolen
                loser.points -= stolen
                cur.results[winner.id].bonus += stolen
                cur.results[loser.id].bonus -= stolen
                text = f"⚔ {winner.name} gana el duelo y roba {stolen} puntos a {loser.name}"
            cur.results[a].duel = cur.results[b].duel = text
            self._say(text, None, "duel")

    # ------------------------------------------------------------------ board

    def _move(self, player: Player, steps: int) -> tuple[list[int], bool]:
        path = self.board.path(player.position, steps)
        passed = self.board.passes_start(player.position, steps)
        if path:
            player.position = path[-1]
        if passed:
            player.points += START_BONUS
        return path, passed

    def _apply_board(self, now: float) -> None:
        cur = self.current
        assert cur is not None
        self.moves = []
        movers = sorted(
            (pid for pid, r in cur.results.items() if r.steps > 0 and pid in self.players),
            key=lambda pid: (-cur.results[pid].steps, cur.results[pid].elapsed or 0),
        )
        for pid in movers:
            player = self.players[pid]
            start = player.position
            path, passed = self._move(player, cur.results[pid].steps)
            texts = [f"Pasa por la salida: +{START_BONUS}"] if passed else []
            extra = self._space_effect(player)
            move = {"player": pid, "from": start, "path": path, "space": self.board.spaces[player.position]}
            self.moves.append(move)
            texts.extend(t for t in [extra.get("text")] if t)
            move["texts"] = texts
            if extra.get("then"):
                self.moves.extend(extra["then"])
        events = sum(len(m.get("texts", [])) for m in self.moves)
        self.phase = BOARD
        base = self.timing.board if self.moves else 1.5
        self.deadline = now + base + self.timing.board_per_event * events
        self._touch()

    def _space_effect(self, player: Player) -> dict[str, Any]:
        """Apply the space the player landed on; returns text and follow-up moves."""
        space = self.board.spaces[player.position]
        if space == STAR:
            return {"text": "★ Si aciertas la próxima pregunta, cierras su categoría"}
        if space == DUEL:
            rivals = [p for p in self._connected() if p.id != player.id]
            if not rivals:
                return {}
            rival = min(rivals, key=lambda p: (abs(p.points - player.points), -p.points))
            self.pending_duels.append((player.id, rival.id))
            text = f"⚔ Reta a {rival.name}: en la próxima, quien lo haga mejor roba {DUEL_STEAL} puntos"
            self._say(f"⚔ {player.name} reta a {rival.name} a un duelo", player.id, "duel")
            return {"text": text}
        if space != EVENT:
            return {}
        kind = self.rng.choice(("double", "plus", "minus", "forward", "back", "steal", "swap"))
        result: dict[str, Any] = {}
        if kind == "double":
            player.double_next = True
            result["text"] = "🎲 ¡Puntos dobles en la próxima pregunta!"
        elif kind == "plus":
            player.points += EVENT_PLUS
            result["text"] = f"🎲 ¡Regalo! +{EVENT_PLUS} puntos"
        elif kind == "minus":
            lost = min(EVENT_MINUS, player.points)
            player.points -= lost
            result["text"] = f"🎲 Mala suerte: −{lost} puntos"
        elif kind in ("forward", "back"):
            steps = 3 if kind == "forward" else -2
            start = player.position
            path, passed = self._move(player, steps)
            word = "Avanza 3 casillas" if steps > 0 else "Retrocede 2 casillas"
            result["text"] = f"🎲 {word}" + (f" (+{START_BONUS} por la salida)" if passed else "")
            result["then"] = [{"player": player.id, "from": start, "path": path,
                               "space": self.board.spaces[player.position], "texts": []}]
        elif kind == "steal":
            others = [p for p in self.players.values() if p.id != player.id]
            leader = max(others, key=lambda p: p.points, default=None)
            if leader is None or leader.points <= player.points:
                player.points += EVENT_STEAL
                result["text"] = f"🎲 Vas en cabeza: +{EVENT_STEAL} puntos"
            else:
                stolen = min(EVENT_STEAL, leader.points)
                leader.points -= stolen
                player.points += stolen
                result["text"] = f"🎲 Roba {stolen} puntos a {leader.name}, que va líder"
        else:  # swap
            others = [p for p in self._connected() if p.id != player.id]
            if not others:
                player.points += EVENT_PLUS
                result["text"] = f"🎲 ¡Regalo! +{EVENT_PLUS} puntos"
            else:
                other = self.rng.choice(others)
                a, b = player.position, other.position
                player.position, other.position = b, a
                result["text"] = f"🎲 Cambia el sitio con {other.name}"
                result["then"] = [
                    {"player": player.id, "from": a, "path": [b], "space": self.board.spaces[b], "texts": [], "jump": True},
                    {"player": other.id, "from": b, "path": [a], "space": self.board.spaces[a], "texts": [], "jump": True},
                ]
        self._say(f"{player.name}: {result['text'].split(' ', 1)[1]}", player.id, "event")
        return result

    def _after_board(self, now: float) -> None:
        if self._check_end(end_of_round=False, now=now):
            return
        chooser = self._next_chooser()
        if chooser is None:
            if self.settings.mode == "rounds" and self.round_no >= self.settings.rounds:
                if self._check_end(end_of_round=True, now=now):
                    return
            self.round_no += 1
            self.chosen_this_round.clear()
            chooser = self._next_chooser()
            if self._connected():
                self._say(f"Empieza la ronda {self.round_no}", None, "round")
        self._begin_choosing(chooser, now)

    # ------------------------------------------------------------------ victory

    def _rank_key(self, player: Player) -> tuple[int, ...]:
        if self.settings.mode == "categories":
            return (len(player.closed), player.points)
        return (player.points,)

    def _ranking_ids(self) -> list[str]:
        return sorted(self.order, key=lambda pid: self._rank_key(self.players[pid]), reverse=True)

    def _check_end(self, end_of_round: bool, now: float) -> bool:
        """Finish or start a tie-break if someone met the victory condition."""
        everyone = [self.players[pid] for pid in self.order]
        if not everyone:
            return False
        s = self.settings
        if s.mode == "points":
            reached = [p for p in everyone if p.points >= s.target_points]
        elif s.mode == "categories":
            reached = [p for p in everyone if len(p.closed) >= s.categories_to_close]
        else:
            reached = everyone if end_of_round else []
        if not reached:
            return False
        best = max(self._rank_key(p) for p in reached)
        top = [p.id for p in reached if self._rank_key(p) == best]
        if len(top) == 1:
            self._finish(top, now)
        else:
            self._start_tiebreak(top, now)
        return True

    def _start_tiebreak(self, pids: list[str], now: float) -> None:
        self.tiebreak_players = list(pids)
        self.tiebreak_attempt += 1
        self.phase = TIEBREAK
        self.current = None
        self.moves = []
        self.deadline = now + self.timing.tiebreak_intro
        names = ", ".join(self.players[p].name for p in pids)
        self._say(f"¡Empate entre {names}! Pregunta de desempate", None, "tiebreak")

    def _ask_tiebreak(self, now: float) -> None:
        pool = [(c, q) for c in self.enabled_categories() for q in c.questions]
        fresh = [(c, q) for c, q in pool if q.key not in self.used] or pool
        players = [p for p in self.tiebreak_players if p in self.players]
        if not fresh or len(players) < 2:
            self._finish(players, now)
            return
        best = max(q.tiebreak_priority for _, q in fresh)
        category, question = self.rng.choice([(c, q) for c, q in fresh if q.tiebreak_priority == best])
        self._start_question(category, question, players, now, tiebreak=True)

    def _resolve_tiebreak(self, now: float) -> None:
        cur = self.current
        assert cur is not None
        players = [p for p in cur.participants if p in self.players]
        keys = {pid: self._duel_key(cur, pid) for pid in players}
        best = max(keys.values(), default=(False, -1.0, 0.0))
        contenders = [pid for pid, k in keys.items() if k == best]
        if (best[0] or best[1] > 0) and len(contenders) == 1:
            self._finish(contenders, now)
        elif self.tiebreak_attempt >= MAX_TIEBREAKS:
            self._finish(contenders if best[0] or best[1] > 0 else players, now)
        else:
            self._start_tiebreak(contenders if len(contenders) > 1 else players, now)

    def _finish(self, winners: list[str], now: float) -> None:
        self.phase = FINISHED
        self.winners = list(winners)
        self.deadline = None
        names = " y ".join(self.players[w].name for w in winners if w in self.players)
        self._say(f"🏆 ¡{'Ganan' if len(winners) > 1 else 'Gana'} {names}!" if names else "Fin de la partida", None, "win")

    # ------------------------------------------------------------------ clock

    def tick(self, now: float) -> None:
        """Advance timers. Call often (the server does it 5 times a second)."""
        last = self._last_tick if self._last_tick is not None else now
        self._last_tick = now
        if self.phase in PLAYING_PHASES and not self._connected():
            # nobody is connected: freeze the clock instead of playing alone
            delta = now - last
            if self.deadline is not None:
                self.deadline += delta
            if self.current is not None:
                self.current.open_at += delta
                self.current.deadline += delta
            return
        for _ in range(6):  # several transitions may be due after a long pause
            if not self._step(now):
                break

    def _step(self, now: float) -> bool:
        cur = self.current
        if self.phase == CHOOSING and self.deadline is not None and now >= self.deadline:
            self._ask(RANDOM_CATEGORY, now)
            if self.chooser_id:
                self.log[-1]["text"] += " (al azar: se acabó el tiempo)"
            return True
        if self.phase == READING and cur and now >= cur.open_at:
            self.phase = ANSWERING
            self.deadline = cur.deadline
            self._touch()
            return True
        if self.phase == ANSWERING and cur and (now >= cur.deadline + ANSWER_GRACE or self._everyone_answered()):
            self._reveal(now)
            return True
        if self.phase == REVEAL and self.deadline is not None and now >= self.deadline:
            if cur and cur.tiebreak:
                self._resolve_tiebreak(now)
            else:
                self._apply_board(now)
            return True
        if self.phase == BOARD and self.deadline is not None and now >= self.deadline:
            self._after_board(now)
            return True
        if self.phase == TIEBREAK and self.deadline is not None and now >= self.deadline:
            self._ask_tiebreak(now)
            return True
        return False

    def skip_wait(self, pid: str, now: float) -> None:
        """Host shortens the reveal / board / tie-break intro pause."""
        self._require_host(pid)
        if self.phase in (REVEAL, BOARD, TIEBREAK):
            self.deadline = now
            self.tick(now)

    # ------------------------------------------------------------------ views

    def _category_list(self) -> list[dict[str, Any]]:
        items = []
        for cat in self.library.categories.values():
            info = cat.summary()
            info["enabled"] = cat.playable and cat.id not in self.settings.disabled
            items.append(info)
        return items

    def _players_public(self) -> list[dict[str, Any]]:
        cur = self.current
        host = self.host_id
        out = []
        for pid in self.order:
            info = self.players[pid].public()
            info["host"] = pid == host
            info["onStar"] = self.phase != LOBBY and self.board.spaces[self.players[pid].position] == STAR
            info["answered"] = bool(cur and pid in cur.answers)
            info["exempt"] = bool(cur and pid in cur.exempt)
            info["participant"] = bool(cur and pid in cur.participants)
            out.append(info)
        return out

    def _question_public(self, for_phone: bool) -> dict[str, Any] | None:
        cur = self.current
        if cur is None or self.phase not in (READING, ANSWERING, REVEAL, BOARD):
            return None
        info = cur.question.to_public(cur.state)
        if self.phase == READING:
            info = {k: info[k] for k in ("key", "type", "prompt", "time", "read", "image", "points")}
        info.update(
            {
                "number": cur.number,
                "openAt": cur.open_at,
                "deadline": cur.deadline,
                "tiebreak": cur.tiebreak,
                "category": {k: cur.category.summary()[k] for k in ("id", "name", "icon", "color")},
                "chooser": cur.chooser_id,
                "starPlayers": sorted(cur.star_players),
                "duels": [list(d) for d in cur.duels],
            }
        )
        return info

    def _reveal_public(self) -> dict[str, Any] | None:
        cur = self.current
        if cur is None or self.phase not in (REVEAL, BOARD):
            return None
        reveal = cur.question.to_reveal(cur.state)
        reveal["answers"] = {pid: a.display for pid, a in cur.answers.items()}
        reveal["results"] = {pid: r.public() for pid, r in cur.results.items()}
        return reveal

    def _round_info(self) -> dict[str, Any]:
        return {
            "round": self.round_no,
            "rounds": self.settings.rounds if self.settings.mode == "rounds" else None,
            "question": self.question_no,
            "chosenThisRound": sorted(self.chosen_this_round),
        }

    def _common_view(self) -> dict[str, Any]:
        cur = self.current
        in_tiebreak = self.phase == TIEBREAK or bool(
            cur and cur.tiebreak and self.phase in (READING, ANSWERING, REVEAL)
        )
        return {
            "phase": self.phase,
            "version": self.version,
            "deadline": self.deadline,
            "players": self._players_public(),
            "hostId": self.host_id,
            "settings": self.settings.public(),
            "round": self._round_info(),
            "chooserId": self.chooser_id if self.phase == CHOOSING else None,
            "question": self._question_public(for_phone=False),
            "reveal": self._reveal_public(),
            "winners": self.winners,
            "ranking": self._ranking_ids(),
            "tiebreakPlayers": self.tiebreak_players if in_tiebreak else [],
            "maxPlayers": self.max_players,
            "chooseTime": self.timing.choose,
        }

    def tv_view(self) -> dict[str, Any]:
        """Everything the shared TV screen needs."""
        view = self._common_view()
        view.update(
            {
                "board": self.board.spaces,
                "categories": self._category_list(),
                "offered": self.offered if self.phase == CHOOSING else [],
                "moves": self.moves if self.phase == BOARD else [],
                "log": self.log[-12:],
            }
        )
        return view

    def phone_view(self, pid: str) -> dict[str, Any]:
        """What one phone needs (other players' answers are never included early)."""
        view = self._common_view()
        player = self.players.get(pid)
        cur = self.current
        me = player.public() if player else None
        if me:
            me["host"] = pid == self.host_id
        my_answer = None
        if cur and pid in cur.answers:
            my_answer = {"display": cur.answers[pid].display}
        is_chooser = self.phase == CHOOSING and self.chooser_id == pid
        categories = self._category_list()
        if not (me and me["host"]) and self.phase not in (LOBBY, FINISHED):
            categories = []
        view.update(
            {
                "me": me,
                "myAnswer": my_answer,
                "exempt": bool(cur and pid in cur.exempt),
                "participant": bool(cur and pid in cur.participants),
                "offered": self.offered if is_chooser else [],
                "categories": categories if self.phase in (LOBBY, FINISHED) or is_chooser else [],
                "myMoves": [m for m in self.moves if m["player"] == pid] if self.phase == BOARD else [],
                "palette": [{"color": c, "name": n} for c, n in PALETTE],
                "takenColors": sorted(self.taken_colors(pid)),
                "boardSize": len(self.board),
                "mySpace": self.board.spaces[player.position] if player else None,
            }
        )
        return view
