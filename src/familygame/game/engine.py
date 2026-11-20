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
from typing import Any, Callable, Iterable

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
MECHANICS = ("ruleta", "moneda", "rival", "eleccion")  # how the category is picked, see docs/mecanicas-categoria.md
CHOICE_INTRO = 2.5     # announcement of the mechanic; actions are refused meanwhile
WHEEL_TIME = 4.5       # from the spin to the question
COIN_TIME = 4.0        # toss + zoom to the face
PICK_REVEAL = 1.5      # after a pick (rival / eleccion) the chosen category is shown
CHOICE_OFFER = 3       # categories offered by "eleccion"

SPEED_BONUS = 0.5      # up to +50 % of base points for answering instantly
STEPS_CORRECT = 2
STEPS_FASTEST = 1
CLOSE_BONUS = 100      # points for closing a category
START_BONUS = 50       # points for passing the start
DUEL_STEAL = 50
EVENT_PLUS, EVENT_MINUS, EVENT_STEAL = 60, 40, 40
# questions about a player (QuestionType.about_chooser): the subject answers, the rest guess
GUESS_POINTS = 100     # a friend who guesses the subject's answer
SUBJECT_HIT = 100      # the subject, for each friend who guessed right
SUBJECT_MISS = 50      # the subject loses this for each friend who guessed wrong
SUBJECT_TIMEOUT = 50   # the subject did not answer in time: the question is void
SUBJECT_BACK = 1       # squares back when the subject ends the question in negative
MAX_TIEBREAKS = 3
ANSWER_GRACE = 0.6     # seconds of network latency accepted after the deadline
AFK_GRACE = 4.0        # seconds a phone may be away before the match pauses by itself
HEARTBEAT_TIMEOUT = 15.0  # a phone that sent pings and went silent this long is away


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
    mechanics: list[str] = field(default_factory=lambda: list(MECHANICS))
    disabled: set[str] = field(default_factory=set)
    music: bool = True
    sfx: bool = True
    volume: int = 70
    late_join: str = "zero"  # points of someone joining a running match: zero | average | fixed
    late_points: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "targetPoints": self.target_points,
            "rounds": self.rounds,
            "categoriesToClose": self.categories_to_close,
            "hitsToClose": self.hits_to_close,
            "mechanics": list(self.mechanics),
            "disabled": sorted(self.disabled),
            "music": self.music,
            "sfx": self.sfx,
            "volume": self.volume,
            "lateJoin": self.late_join,
            "latePoints": self.late_points,
        }


@dataclass
class Away:
    """A player who left or was removed during a match; their seat and state are kept."""

    player: Player
    reason: str  # "left" (by themselves) or "kicked" (by the host)
    slot: int  # position in the join order, to come back to the same place


LATE_JOIN_MODES = ("zero", "average", "fixed")


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
    subject_id: str | None = None  # question about this player (about_chooser types)
    stage: str = ""  # about_chooser: "subject" (they pick) then "guess" (the others)
    void: str = ""  # why the question was cancelled ("" = it was not)


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
        self.away: dict[str, Away] = {}  # players who left mid-match; they can come back
        self.host_override: str | None = None  # host handed the control to someone
        self._host_seen: str | None = None
        self.checkpoint: str | None = None  # "save" | "clear": the server (un)writes the autosave
        self.settings = Settings()
        self.saved: dict[str, Any] | None = None  # stored match (see save_and_exit)
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
        self.choice: dict[str, Any] | None = None
        self.deadline: float | None = None
        self.current: AskedQuestion | None = None
        self.pending_duels: list[tuple[str, str]] = []
        self.moves: list[dict[str, Any]] = []
        self.tiebreak_players: list[str] = []
        self.tiebreak_attempt = 0
        self.winners: list[str] = []
        self.paused = False
        self.paused_by: str | None = None
        self.pause_started: float | None = None
        self.paused_reason: str | None = None  # "manual" or "afk"
        self.seen: dict[str, float] = {}  # last ping of the phones that send them
        self.afk_since: dict[str, tuple[float, str]] = {}  # pid -> (since, "hidden"|"dropped"|"silent")
        self.afk_ignored: set[str] = set()  # the host resumed anyway: do not pause again for them
        self.away = {}  # a new match: the seats reserved in the old one are free again
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
        """The player the host handed control to, else the first connected one (join order)."""
        override = self.players.get(self.host_override) if self.host_override else None
        if override and override.connected:
            return override.id
        connected = self._connected()
        return connected[0].id if connected else None

    def _announce_host(self) -> None:
        """Say it out loud when the control passes to someone else."""
        host = self.host_id
        if host is None or host == self._host_seen:
            return
        if self._host_seen is not None and self.phase != LOBBY:
            self._say(f"👑 {self.players[host].name} es ahora el anfitrión", host, "host")
        self._host_seen = host

    def set_host(self, pid: str, target: str) -> None:
        """The host passes the control to another connected player."""
        self._require_host(pid)
        new = self._player(target)
        if not new.connected:
            raise GameError("Esa persona no está conectada")
        self.host_override = target
        self._announce_host()
        self._touch()

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
        if len(self.players) + len(self.away) >= self.max_players:
            raise GameError("Todas las plazas están ocupadas o reservadas por quien se fue; "
                            "el anfitrión puede liberar una")
        clean, color, avatar = self._validate_profile(name, color, avatar)
        pid = secrets.token_hex(4)
        while pid in self.players or pid in self.away:
            pid = secrets.token_hex(4)
        player = Player(pid, secrets.token_urlsafe(18), clean, color, avatar)
        if self.phase not in (LOBBY, FINISHED):
            player.points = self._late_points()
        self.players[pid] = player
        self.order.append(pid)
        self._say(f"{clean} se ha unido" + (f" con {player.points} puntos" if player.points else ""), pid, "join")
        self._announce_host()
        return player

    def _late_points(self, exclude: Iterable[str] = ()) -> int:
        """Points for someone joining a running match, as the host chose."""
        s = self.settings
        if s.late_join == "fixed":
            return s.late_points
        if s.late_join == "average":
            others = [p.points for p in self.players.values() if p.id not in set(exclude)]
            return round(sum(others) / len(others)) if others else 0
        return 0

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
                    self._back(player.id)
                    self._say(f"{player.name} ha vuelto", player.id, "join")
                    self._announce_host()
                return player
        return None

    def away_reason(self, token: str) -> str | None:
        """Why the phone owning ``token`` is out of the match ("left"/"kicked"), if it is."""
        for away in self.away.values():
            if secrets.compare_digest(away.player.token, token):
                return away.reason
        return None

    def disconnect(self, pid: str, now: float) -> None:
        """A phone closed its connection; the player stays in the game."""
        player = self.players.get(pid)
        if player is None or not player.connected:
            return
        player.connected = False
        if self.phase not in (LOBBY, FINISHED):
            self.afk_since[pid] = (now, "dropped")
        self._say(f"{player.name} se ha desconectado", pid, "leave")
        if self.phase == CHOOSING and self.chooser_id == pid:
            self._actor_gone(pid, now)
        elif self.phase == CHOOSING and self.choice and self.choice["actorId"] == pid:
            self._actor_gone(pid, now)
        self._announce_host()

    def remove(self, pid: str, by: str | None, now: float) -> None:
        """Kick (by the host) or leave voluntarily (``by == pid``).

        During a match the player is not forgotten: their seat and state are kept in
        ``self.away`` so they can come back (see :meth:`reclaim` and :meth:`readmit`).
        """
        if by != pid:
            self._require_host(by or "")
        player = self._player(pid)
        in_match = self.phase not in (LOBBY, FINISHED)
        if in_match:
            self.away[pid] = Away(player, "left" if by == pid else "kicked", self.order.index(pid))
        if self.host_override == pid:
            self.host_override = None
        for table in (self.seen, self.afk_since):
            table.pop(pid, None)
        self.afk_ignored.discard(pid)
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
        self._say(f"{player.name} " + ("ha salido de la partida" if by == pid else "ha sido sacado de la partida"),
                  None, "leave")
        if self.phase == CHOOSING and self.chooser_id == pid:
            self.chooser_id = None
            self._actor_gone(pid, now, removed=True)
        elif self.phase == CHOOSING and self.choice and self.choice["actorId"] == pid:
            self._actor_gone(pid, now, removed=True)
        self._announce_host()

    def _restore_away(self, pid: str, connected: bool) -> Player:
        """Put a player who was away back in their old place, fixing name/colour clashes."""
        away = self.away.pop(pid)
        player = away.player
        while any(name_key(o.name) == name_key(player.name) for o in self.players.values()):
            player.name += "*"
        if player.color in self.taken_colors(None):
            player.color = next((c for c in PALETTE_COLORS if c not in self.taken_colors(None)), player.color)
        player.connected = connected
        self.players[pid] = player
        self.order.insert(min(away.slot, len(self.order)), pid)
        return player

    def reclaim(self, pid: str) -> Player:
        """Someone who left comes back (recognised by their phone) and gets their state back."""
        away = self.away.get(pid)
        if away is None or away.reason != "left":
            raise GameError("Esa plaza ya no está disponible")
        player = self._restore_away(pid, True)
        self._say(f"{player.name} ha vuelto a la partida", pid, "join")
        self._announce_host()
        return player

    def readmit(self, by: str, pid: str) -> None:
        """The host brings back someone who left or was removed (their phone reconnects by itself)."""
        self._require_host(by)
        if pid not in self.away:
            raise GameError("Esa persona ya no está en la lista de ausentes")
        player = self._restore_away(pid, False)
        self._say(f"{player.name} vuelve a la partida", pid, "join")
        self._touch()

    def forget_away(self, by: str, pid: str) -> None:
        """The host frees the seat reserved for someone who left."""
        self._require_host(by)
        if self.away.pop(pid, None) is None:
            raise GameError("Esa persona ya no está en la lista de ausentes")
        self._touch()

    def assign_away(self, by: str, new_pid: str, away_pid: str) -> None:
        """The host says a player who just joined is really someone who left (new phone, new name)."""
        self._require_host(by)
        new = self._player(new_pid)
        away = self.away.get(away_pid)
        if away is None:
            raise GameError("Esa persona ya no está en la lista de ausentes")
        old = away.player
        for attr in ("points", "position", "closed", "progress", "double_next", "correct_count", "asked_count"):
            setattr(new, attr, getattr(old, attr))
        new.asked, new.right = dict(old.asked), dict(old.right)
        del self.away[away_pid]
        self._say(f"{new.name} retoma la partida de {old.name}", new_pid, "join")
        self._touch()

    # ------------------------------------------------------------------ lobby

    def set_settings(self, pid: str, changes: dict[str, Any]) -> None:
        """Host changes lobby options. Unknown keys are ignored."""
        self._require_host(pid)
        s = self.settings
        # sound can be changed at any moment, the rest only between games
        for key in ("music", "sfx"):
            if key in changes:
                if not isinstance(changes[key], bool):
                    raise GameError(f"Valor no válido para {key}")
                setattr(s, key, changes[key])
        if "volume" in changes:
            vol = changes["volume"]
            if isinstance(vol, bool) or not isinstance(vol, (int, float)):
                raise GameError("Valor no válido para volume")
            s.volume = max(0, min(100, int(vol)))
        if "lateJoin" in changes:
            if changes["lateJoin"] not in LATE_JOIN_MODES:
                raise GameError("Valor no válido para lateJoin")
            s.late_join = changes["lateJoin"]
        if "latePoints" in changes:
            value = changes["latePoints"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise GameError("Valor no válido para latePoints")
            s.late_points = max(0, min(100_000, int(value)))
        if self.phase not in (LOBBY, FINISHED):
            if set(changes) - {"music", "sfx", "volume", "lateJoin", "latePoints"}:
                raise GameError("Las opciones se cambian antes de empezar")
            self._touch()
            return

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
        if "toggleMechanic" in changes:
            mid = changes["toggleMechanic"]
            if mid not in MECHANICS:
                raise GameError("Mecánica desconocida")
            if mid in s.mechanics:
                if len(s.mechanics) == 1:
                    raise GameError("Debe quedar al menos una mecánica activa")
                s.mechanics.remove(mid)
            else:
                s.mechanics = [m for m in MECHANICS if m in s.mechanics or m == mid]
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
        self.checkpoint = "clear"
        self._say("De vuelta al lobby", None, "info")

    # ------------------------------------------------------------------ save / resume

    def save_and_exit(self, pid: str, now: float) -> dict[str, Any]:
        """Host stores the match in ``self.saved`` and returns everyone to the lobby.

        The match is saved at a question boundary: a question still being played is
        dropped (its chooser picks again when the match is resumed); a pending reveal
        or board movement is finished first.

        Args:
            pid: Player asking (must be the host).
            now: Current time.

        Returns:
            The snapshot (JSON-serialisable); the server writes it to disk.

        Raises:
            GameError: Not host, no match running, or a tie-break in progress.
        """
        self._require_host(pid)
        if self.phase in (LOBBY, FINISHED):
            raise GameError("No hay ninguna partida en curso que guardar")
        for _ in range(4):  # let the reveal and the board movement finish
            if self.phase in (REVEAL, BOARD):
                self.deadline = now
                self.tick(now)
        cur = self.current
        if self.phase in (TIEBREAK,) or (cur and cur.tiebreak) or self.phase == FINISHED:
            raise GameError("No se puede guardar durante un desempate; termina antes la pregunta")
        chooser = self.chooser_id
        duels = list(self.pending_duels)
        if self.phase in (READING, ANSWERING) and cur:
            chooser = cur.chooser_id
            if chooser:
                self.chosen_this_round.discard(chooser)
            duels += cur.duels
        snapshot = self.snapshot(now, chooser, duels)
        self.saved = snapshot
        self._reset_match()
        self._say("Partida guardada. Se puede continuar desde el menú", None, "info")
        self.checkpoint = "clear"  # the manual save replaces the autosave
        return snapshot

    def snapshot(self, now: float, chooser: str | None, duels: list[Any] | None = None) -> dict[str, Any]:
        """The match as plain data (what is written to disk), taken at a question boundary."""
        s = self.settings
        duels = list(self.pending_duels) if duels is None else duels
        return {
            "version": 1,
            "savedAt": now,
            "settings": {
                "mode": s.mode, "targetPoints": s.target_points, "rounds": s.rounds,
                "categoriesToClose": s.categories_to_close, "hitsToClose": s.hits_to_close,
                "mechanics": list(s.mechanics), "disabled": sorted(s.disabled),
                "lateJoin": s.late_join, "latePoints": s.late_points,
            },
            "board": list(self.board.spaces),
            "used": sorted(self.used),
            "roundNo": self.round_no,
            "questionNo": self.question_no,
            "chosen": sorted(self.chosen_this_round),
            "lastChooser": self.last_chooser,
            "chooser": chooser,
            "pendingDuels": [list(d) for d in duels],
            "order": list(self.order),
            "players": [
                {
                    "id": p.id, "token": p.token, "name": p.name, "color": p.color, "avatar": p.avatar,
                    "photoVersion": p.photo_version, "points": p.points, "position": p.position,
                    "closed": list(p.closed), "progress": dict(p.progress), "doubleNext": p.double_next,
                    "correct": p.correct_count, "asked": p.asked_count,
                    "catAsked": dict(p.asked), "catRight": dict(p.right),
                }
                for p in (self.players[i] for i in self.order)
            ]
            + [
                {
                    "id": a.player.id, "token": a.player.token, "name": a.player.name, "color": a.player.color,
                    "avatar": a.player.avatar, "photoVersion": a.player.photo_version,
                    "points": a.player.points, "position": a.player.position,
                    "closed": list(a.player.closed), "progress": dict(a.player.progress),
                    "doubleNext": a.player.double_next, "correct": a.player.correct_count,
                    "asked": a.player.asked_count, "catAsked": dict(a.player.asked),
                    "catRight": dict(a.player.right), "away": a.reason, "slot": a.slot,
                }
                for a in self.away.values()
            ],
        }

    def saved_summary(self) -> dict[str, Any] | None:
        """What the menu shows about the stored match."""
        data = self.saved
        if not data:
            return None
        return {
            "players": [p["name"] for p in data["players"] if not p.get("away")],
            "auto": bool(data.get("auto")),
            "round": data["roundNo"],
            "questions": data["questionNo"],
            "mode": data["settings"]["mode"],
            "savedAt": data["savedAt"],
        }

    def load_saved(self, data: dict[str, Any]) -> None:
        """Adopt a match stored on disk (server start-up).

        Its players are added as disconnected so their phones, which keep the token,
        get their identity back by themselves; the host can then resume.
        """
        self.saved = data
        for saved in data["players"][: self.max_players]:
            if saved["id"] in self.players:
                continue
            player = Player(saved["id"], saved["token"], saved["name"], saved["color"], saved["avatar"], connected=False)
            player.photo_version = saved.get("photoVersion", 0)
            if saved.get("away"):  # kept apart: a kicked phone still has to be recognised
                self.away[player.id] = Away(player, saved["away"], saved.get("slot", 0))
                continue
            self.players[player.id] = player
            self.order.append(player.id)
        self._touch()

    def discard_saved(self, pid: str) -> None:
        """Host forgets the stored match (and the players that only exist because of it)."""
        self._require_host(pid)
        data, self.saved = self.saved, None
        for saved in (data or {}).get("players", []):
            player = self.players.get(saved["id"])
            if player and not player.connected and self.phase in (LOBBY, FINISHED):
                del self.players[saved["id"]]
                self.order.remove(saved["id"])
        self._touch()

    def resume(self, pid: str, now: float) -> None:
        """Host continues the stored match with whoever is here.

        Players of the save that are not connected stay in the match as disconnected
        (their phones rejoin by themselves); players who joined since start from 0.

        Raises:
            GameError: Not host, a match is running, or nothing is saved.
        """
        self._require_host(pid)
        if self.phase not in (LOBBY, FINISHED):
            raise GameError("Ya hay una partida en marcha")
        data = self.saved
        if not data:
            raise GameError("No hay ninguna partida guardada")
        s = self.settings
        cfg = data["settings"]
        s.mode, s.target_points, s.rounds = cfg["mode"], cfg["targetPoints"], cfg["rounds"]
        s.categories_to_close, s.hits_to_close = cfg["categoriesToClose"], cfg["hitsToClose"]
        s.mechanics = [m for m in MECHANICS if m in cfg.get("mechanics", MECHANICS)] or list(MECHANICS)
        s.disabled = {c for c in cfg["disabled"] if c in self.library.categories}
        s.late_join, s.late_points = cfg.get("lateJoin", s.late_join), cfg.get("latePoints", s.late_points)
        self._reset_match()
        self.board = Board(list(data["board"]))
        self.used = set(data["used"])
        self.round_no, self.question_no = data["roundNo"], data["questionNo"]
        self.chosen_this_round = set(data["chosen"])
        self.last_chooser = data["lastChooser"]
        self.pending_duels = [(a, b) for a, b in data["pendingDuels"]]
        for saved in data["players"]:
            player = self.players.get(saved["id"])
            if saved.get("away"):  # they were out of the match when it was saved
                if player is not None:  # a ghost created at load time or a present phone
                    del self.players[saved["id"]]
                    if saved["id"] in self.order:
                        self.order.remove(saved["id"])
                ghost = Player(saved["id"], saved["token"], saved["name"], saved["color"], saved["avatar"], connected=False)
                ghost.photo_version = saved.get("photoVersion", 0)
                for attr, key in (("points", "points"), ("position", "position"), ("correct_count", "correct"),
                                  ("asked_count", "asked"), ("double_next", "doubleNext")):
                    setattr(ghost, attr, saved[key])
                ghost.closed, ghost.progress = list(saved["closed"]), dict(saved["progress"])
                ghost.asked, ghost.right = dict(saved.get("catAsked", {})), dict(saved.get("catRight", {}))
                self.away[ghost.id] = Away(ghost, saved["away"], saved.get("slot", 0))
                continue
            if player is None:
                if len(self.players) >= self.max_players:
                    continue
                name = saved["name"]
                while any(name_key(o.name) == name_key(name) for o in self.players.values()):
                    name += "*"
                color = saved["color"]
                if color in self.taken_colors(None):
                    color = next((c for c in PALETTE_COLORS if c not in self.taken_colors(None)), color)
                player = Player(saved["id"], saved["token"], name, color, saved["avatar"], connected=False)
                player.photo_version = saved.get("photoVersion", 0)
                self.players[player.id] = player
            player.points, player.position = saved["points"], saved["position"]
            player.closed, player.progress = list(saved["closed"]), dict(saved["progress"])
            player.double_next = saved["doubleNext"]
            player.correct_count, player.asked_count = saved["correct"], saved["asked"]
            player.asked, player.right = dict(saved.get("catAsked", {})), dict(saved.get("catRight", {}))
        self.order = [i for i in data["order"] if i in self.players] + [
            i for i in self.players if i not in data["order"]
        ]
        self.chosen_this_round &= set(self.players)
        self.pending_duels = [(a, b) for a, b in self.pending_duels if a in self.players and b in self.players]
        saved_ids = {p["id"] for p in data["players"]}
        newcomers = [pid for pid in self.players if pid not in saved_ids]
        late = self._late_points(exclude=newcomers)  # people who joined since: the host's late-join rule
        for pid in newcomers:
            self.players[pid].points = late
        self.saved = None
        self._say("Se reanuda la partida guardada", None, "start")
        chooser = data["chooser"]
        if chooser not in self.players or not self.players[chooser].connected:
            chooser = self._next_chooser()
        self._begin_choosing(chooser, now)

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

    def _allowed(self, chooser: str | None) -> Callable[[QuestionType], bool]:
        """Filter of askable questions: those about a player need one who chose, and someone to guess."""
        can_be_subject = bool(
            chooser and chooser in self.players and self.players[chooser].connected
            and len(self._connected()) >= 2
        )
        return lambda q: can_be_subject or not q.about_chooser

    def _offer_categories(self, chooser: str | None) -> list[str]:
        allowed = self._allowed(chooser)
        enabled = [c for c in self.enabled_categories() if any(allowed(q) for q in c.questions)]
        available = [c for c in enabled if any(q.key not in self.used and allowed(q) for q in c.questions)]
        if not available and enabled:
            self.used.clear()
            self._say("Se han agotado las preguntas: a partir de ahora se pueden repetir", None, "warn")
            available = enabled
        return [c.id for c in available]

    def _hit_rate(self, pid: str, cat: str) -> float:
        """Laplace-smoothed hit rate of a player in a category, this match."""
        player = self.players[pid]
        return (player.right.get(cat, 0) + 1) / (player.asked.get(cat, 0) + 2)

    def _best_worst(self, pid: str, cats: list[str]) -> tuple[str, str]:
        """Best and worst category of a player (ties at random, always two distinct ones)."""
        order = cats[:]
        self.rng.shuffle(order)  # random tie-break: the sort below is stable
        order.sort(key=lambda c: self._hit_rate(pid, c))
        return order[-1], order[0]

    def _begin_choosing(self, chooser: str | None, now: float) -> None:
        available = self._offer_categories(chooser)
        if not available:
            self._finish(self._ranking_ids()[:1], now)
            return
        others = [p.id for p in self._connected() if p.id != chooser]
        enabled = [m for m in MECHANICS if m in self.settings.mechanics]
        usable = [
            m for m in enabled
            if (m != "rival" or others) and (m not in ("ruleta", "moneda") or len(available) >= 2)
            and (m == "eleccion" or chooser)
        ]
        mechanic = self.rng.choice(usable) if usable else "eleccion"
        actor = chooser
        stats = None
        if mechanic == "eleccion":
            offered = self.rng.sample(available, min(CHOICE_OFFER, len(available)))
        elif mechanic == "moneda":
            assert chooser
            offered = list(self._best_worst(chooser, available))
            player = self.players[chooser]
            stats = {
                face: (player.right.get(cat, 0) / player.asked[cat] if player.asked.get(cat) else None)
                for face, cat in zip(("cara", "cruz"), offered)
            }
        else:
            offered = list(available)
            if mechanic == "rival":
                actor = self.rng.choice(others)
        self.phase = CHOOSING
        self.checkpoint = "save"  # a clean boundary: the server autosaves here
        self.chooser_id = chooser
        self.offered = offered
        self.current = None
        self.moves = []
        intro = now + CHOICE_INTRO
        self.choice = {
            "mechanic": mechanic, "chooserId": chooser, "actorId": actor, "offered": offered,
            "introUntil": intro, "spinAt": None, "revealUntil": None, "result": None,
            "outcome": None, "stats": stats,
        }
        self.deadline = intro + self._act_delay(actor)
        self._touch()

    def _act_delay(self, actor: str | None) -> float:
        player = self.players.get(actor) if actor else None
        return self.timing.choose if player and player.connected else 1.5

    def _actor_gone(self, pid: str, now: float, removed: bool = False) -> None:
        """The chooser or the actor left or dropped during choosing: the engine acts soon."""
        ch = self.choice
        if removed and ch:
            if ch["chooserId"] == pid:
                ch["chooserId"] = None
            if ch["actorId"] == pid:
                ch["actorId"] = None
        if ch and ch["result"] is None and ch["actorId"] in (pid, None):
            self.deadline = min(self.deadline or now, max(now + 1.5, ch["introUntil"]))

    def _check_choice(self, pid: str, mechanics: tuple[str, ...], now: float) -> dict[str, Any]:
        """Validate that ``pid`` may act now in the current choice.

        Returns:
            The current choice.

        Raises:
            GameError: Paused, wrong phase, wrong actor or mechanic, intro, or already done.
        """
        if self.paused:
            raise GameError("La partida está en pausa")
        ch = self.choice
        if self.phase != CHOOSING or ch is None:
            raise GameError("Ahora no toca elegir categoría")
        if pid != ch["actorId"]:
            raise GameError("No es tu turno de elegir")
        if ch["mechanic"] not in mechanics:
            raise GameError("Esa acción no corresponde a esta mecánica")
        if now < ch["introUntil"]:
            raise GameError("Espera un momento")
        if ch["result"] is not None:
            raise GameError("Ya se ha elegido")
        return ch

    def spin(self, pid: str, now: float) -> None:
        """The actor spins the wheel or tosses the coin (ruleta / moneda)."""
        self._check_choice(pid, ("ruleta", "moneda"), now)
        self._do_spin(now)

    def choose(self, pid: str, category_id: str, now: float) -> None:
        """The actor picks a category (rival / eleccion)."""
        ch = self._check_choice(pid, ("rival", "eleccion"), now)
        if category_id not in ch["offered"]:
            raise GameError("Esa categoría no está disponible")
        self._do_pick(category_id, now)

    def _name_of(self, pid: str | None) -> str:
        player = self.players.get(pid) if pid else None
        return player.name if player else "Alguien"

    def _cat_text(self, cid: str) -> str:
        cat = self.library.categories[cid]
        return f"{cat.icon} {cat.name}"

    def _do_spin(self, now: float) -> None:
        ch = self.choice
        assert ch is not None
        ch["spinAt"] = now
        if ch["mechanic"] == "ruleta":
            ch["result"] = self.rng.choice(ch["offered"])
            ch["revealUntil"] = now + WHEEL_TIME
            self._say(f"Ruleta: sale {self._cat_text(ch['result'])}", ch["chooserId"], "choose")
        else:
            ch["outcome"] = self.rng.choice(("cara", "cruz"))
            ch["result"] = ch["offered"][0 if ch["outcome"] == "cara" else 1]
            ch["revealUntil"] = now + COIN_TIME
            self._say(f"Cara o cruz ({ch['outcome']}): {self._cat_text(ch['result'])}", ch["chooserId"], "choose")
        self.deadline = ch["revealUntil"]
        self._touch()

    def _do_pick(self, category_id: str, now: float) -> None:
        ch = self.choice
        assert ch is not None
        ch["spinAt"], ch["result"], ch["revealUntil"] = now, category_id, now + PICK_REVEAL
        self.deadline = ch["revealUntil"]
        text = self._cat_text(category_id)
        if ch["mechanic"] == "rival":
            self._say(f"{self._name_of(ch['actorId'])} elige por {self._name_of(ch['chooserId'])}: {text}",
                      ch["actorId"], "choose")
        elif ch["chooserId"]:
            self._say(f"{self._name_of(ch['chooserId'])} elige {text}", ch["chooserId"], "choose")
        else:
            self._say(f"Categoría al azar: {text}", None, "choose")
        self._touch()

    def _auto_choice(self, now: float) -> None:
        """Nobody acted in time: the engine spins, tosses or picks at random."""
        ch = self.choice
        assert ch is not None
        if ch["mechanic"] in ("ruleta", "moneda"):
            self._do_spin(now)
        else:
            self._do_pick(self.rng.choice(ch["offered"]), now)
        if ch["chooserId"] or ch["mechanic"] == "rival":
            self.log[-1]["text"] += " (al azar: se acabó el tiempo)"

    def _ask(self, category_id: str, now: float) -> None:
        category = self.library.categories[category_id]
        allowed = self._allowed(self.chooser_id)
        question = pick_question(category, self.used, self.history, self.rng, allowed)
        if question is None:  # defensive: category exhausted between offer and pick
            self.used -= {q.key for q in category.questions}
            question = pick_question(category, self.used, self.history, self.rng, allowed)
        if question is None:  # only questions about the chooser, who has just gone
            others = [c for c in self.enabled_categories() if any(allowed(q) for q in c.questions)]
            if not others:
                self._finish(self._ranking_ids()[:1], now)
                return
            category = self.rng.choice(others)
            self.used -= {q.key for q in category.questions}
            question = pick_question(category, self.used, self.history, self.rng, allowed)
            assert question is not None
        participants = [p.id for p in self._connected()]
        self._start_question(category, question, participants, now, tiebreak=False)
        if self.chooser_id:
            self.chosen_this_round.add(self.chooser_id)
            self.last_chooser = self.chooser_id

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
        subject = None
        if question.about_chooser and not tiebreak and self.chooser_id in participants:
            subject = self.chooser_id
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
            subject_id=subject,
            stage="subject" if subject else "",
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
        if self.paused:
            raise GameError("La partida está en pausa")
        if self.phase != ANSWERING or cur is None:
            raise GameError("Ahora no se puede responder")
        if pid not in cur.participants:
            raise GameError("No participas en esta pregunta")
        if pid in cur.answers or pid in cur.exempt:
            raise GameError("Ya has respondido")
        choosing_self = cur.stage == "subject"
        if choosing_self and pid != cur.subject_id:
            subject = self.players.get(cur.subject_id or "")
            raise GameError(f"Espera: primero elige {subject.name if subject else 'el otro jugador'}")
        if now > cur.deadline + ANSWER_GRACE:
            raise GameError("¡Se acabó el tiempo!")
        try:
            value = cur.question.normalize_answer(raw, cur.state)
        except AnswerError as exc:
            raise GameError(str(exc)) from exc
        if choosing_self:
            cur.question.set_reference(value, cur.state)
        elapsed = max(0.0, min(now - cur.open_at, float(cur.question.time_limit)))
        cur.answers[pid] = Answer(
            value,
            cur.question.answer_for_display(value, cur.state),
            elapsed,
            cur.question.evaluate(value, cur.state),
        )
        if choosing_self:
            self._begin_guessing(now)
        self._touch()

    def _begin_guessing(self, now: float) -> None:
        """The subject has answered: the clock starts again for the others to guess."""
        cur = self.current
        assert cur is not None
        cur.stage = "guess"
        cur.open_at = now
        cur.deadline = now + cur.question.time_limit
        self.deadline = cur.deadline
        subject = self.players[cur.subject_id or ""]
        self._say(f"{subject.name} ya ha elegido: ¿lo conocéis?", subject.id, "info")

    def _void(self, now: float, penalty: bool) -> None:
        """The subject did not answer (time ran out, left or cannot see it): nobody scores."""
        cur = self.current
        assert cur is not None
        subject = self.players.get(cur.subject_id or "")
        cur.void = "timeout" if penalty else "gone"
        cur.stage = ""
        for pid in cur.participants:
            if pid in self.players:
                cur.results[pid] = Result(exempt=True)
        if subject and penalty:
            lost = max(0, min(SUBJECT_TIMEOUT, subject.points))
            subject.points -= lost
            cur.results[subject.id] = Result(points=-lost, detail="No elegiste a tiempo")
            self._say(f"{subject.name} no eligió a tiempo: pregunta anulada (−{lost})", subject.id, "warn")
        else:
            name = subject.name if subject else "el jugador"
            self._say(f"Pregunta anulada: {name} no puede responder", cur.subject_id, "warn")
        self.phase = REVEAL
        self.deadline = now + self.timing.reveal
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
        subject = cur.subject_id
        correct_times = [a.elapsed for pid, a in cur.answers.items() if a.evaluation.correct and pid != subject]
        fastest = min(correct_times) if correct_times else None
        hits = misses = 0
        for pid in cur.participants:
            player = self.players.get(pid)
            if player is None or pid == subject:
                continue
            res = Result()
            cur.results[pid] = res
            if pid in cur.exempt:
                res.exempt = True
                continue
            answer = cur.answers.get(pid)
            if not cur.tiebreak:
                player.asked_count += 1
                player.asked[cur.category.id] = player.asked.get(cur.category.id, 0) + 1
            if answer is not None:
                res.answered = True
                res.correct = answer.evaluation.correct
                res.detail = answer.evaluation.detail
                res.elapsed = answer.elapsed
            if cur.tiebreak:
                continue
            if res.correct:
                assert answer is not None
                if subject:
                    hits += 1
                    res.points = GUESS_POINTS
                else:
                    speed = max(0.0, 1 - answer.elapsed / q.time_limit)
                    res.points = q.base_points + round(q.base_points * SPEED_BONUS * speed)
                self._credit_hit(cur, player, res, fastest=answer.elapsed == fastest)
            elif res.answered:
                misses += 1
            player.double_next = False
            player.points += res.points + res.bonus
        if subject:
            self._score_subject(cur, hits, misses)
        if not cur.tiebreak:
            self._resolve_duels(cur)
        self.phase = REVEAL
        self.deadline = now + self.timing.reveal
        self._touch()

    def _credit_hit(self, cur: AskedQuestion, player: Player, res: Result, fastest: bool) -> None:
        """A good answer: double points, board steps and category progress (``res.points`` already set)."""
        if player.double_next:
            res.points *= 2
            res.doubled = True
        res.fastest = fastest
        res.steps = STEPS_CORRECT + (STEPS_FASTEST if fastest else 0)
        player.correct_count += 1
        cat = cur.category.id
        player.right[cat] = player.right.get(cat, 0) + 1
        player.progress[cat] = player.progress.get(cat, 0) + 1
        on_star = player.id in cur.star_players
        if cat not in player.closed and (on_star or player.progress[cat] >= self.settings.hits_to_close):
            player.closed.append(cat)
            res.closed = cur.category.name
            res.bonus += CLOSE_BONUS
            how = "desde la estrella ★" if on_star else f"con {player.progress[cat]} aciertos"
            self._say(f"{player.name} cierra {cur.category.icon} {cur.category.name} {how}", player.id, "close")

    def _score_subject(self, cur: AskedQuestion, hits: int, misses: int) -> None:
        """The subject wins for each friend who knew them and loses for each who did not.

        It counts as a hit (board steps, category progress, x2) when at least half of
        those who answered guessed right. Points never drop below zero.
        """
        player = self.players.get(cur.subject_id or "")
        if player is None:
            return
        answer = cur.answers.get(player.id)
        res = Result(answered=True, elapsed=answer.elapsed if answer else None)
        cur.results[player.id] = res
        player.asked_count += 1
        voters = hits + misses
        res.detail = f"Te han acertado {hits} de {voters}" if voters else "Nadie ha respondido"
        points = hits * SUBJECT_HIT - misses * SUBJECT_MISS
        res.points = points  # may be negative, also the player's total
        if points < 0:
            res.steps = -SUBJECT_BACK
        res.correct = hits > 0 and 2 * hits >= voters
        if res.correct:
            self._credit_hit(cur, player, res, fastest=False)
        player.double_next = False
        player.points += res.points + res.bonus

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
                stolen = max(0, min(DUEL_STEAL, loser.points))  # totals can be negative
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
            (pid for pid, r in cur.results.items() if r.steps != 0 and pid in self.players),
            key=lambda pid: (-cur.results[pid].steps, cur.results[pid].elapsed or 0),
        )
        for pid in movers:
            player = self.players[pid]
            start = player.position
            steps = cur.results[pid].steps
            path, passed = self._move(player, steps)
            texts = [f"Pasa por la salida: +{START_BONUS}"] if passed else []
            # moving back is a penalty: the square it lands on does nothing
            extra = self._space_effect(player) if steps > 0 else {"text": f"Retrocede {-steps} por no ser conocido"}
            move = {"player": pid, "from": start, "path": path, "space": self.board.spaces[player.position],
                    "back": steps < 0}
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
            lost = max(0, min(EVENT_MINUS, player.points))
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
                stolen = max(0, min(EVENT_STEAL, leader.points))
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

    def ranking_ids(self) -> list[str]:
        return self._ranking_ids()

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
        pool = [(c, q) for c in self.enabled_categories() for q in c.questions if not q.about_chooser]
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
        self.checkpoint = "clear"  # nothing left to recover
        self.winners = list(winners)
        self.deadline = None
        names = " y ".join(self.players[w].name for w in winners if w in self.players)
        self._say(f"🏆 ¡{'Ganan' if len(winners) > 1 else 'Gana'} {names}!" if names else "Fin de la partida", None, "win")

    # ------------------------------------------------------------------ clock

    def tick(self, now: float) -> None:
        """Advance timers. Call often (the server does it 5 times a second)."""
        last = self._last_tick if self._last_tick is not None else now
        self._last_tick = now
        if self.phase in PLAYING_PHASES and not self.paused:
            self._check_afk(now)
        if self.phase in PLAYING_PHASES and (self.paused or not self._connected()):
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
            if self.choice and self.choice["result"] is None:
                self._auto_choice(now)
            elif self.choice:
                self._ask(self.choice["result"], now)
            else:
                self._ask(self.rng.choice(self.offered), now)
            return True
        if self.phase == READING and cur and now >= cur.open_at:
            self.phase = ANSWERING
            self.deadline = cur.deadline
            self._touch()
            return True
        if self.phase == ANSWERING and cur and cur.stage == "subject":
            if cur.subject_id not in self.players or cur.subject_id in cur.exempt:
                self._void(now, penalty=False)
                return True
            if now >= cur.deadline + ANSWER_GRACE:
                self._void(now, penalty=True)
                return True
            return False
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
        if self.phase in (REVEAL, BOARD, TIEBREAK) and not self.paused:
            self.deadline = now
            self.tick(now)

    def pause(self, pid: str, now: float) -> None:
        """Any player freezes the match (a phone died, someone has to leave for a minute...)."""
        self._player(pid)
        if self.phase in (LOBBY, FINISHED):
            raise GameError("No hay partida en curso")
        if self.paused:
            return
        self._freeze(pid, "manual", now)
        self._say(f"⏸ {self.players[pid].name} ha pausado la partida", pid, "pause")

    def _freeze(self, by: str | None, reason: str, now: float) -> None:
        self.paused, self.paused_by, self.paused_reason, self.pause_started = True, by, reason, now
        self._last_tick = now

    def unpause(self, pid: str, now: float) -> None:
        """Resume a paused match; the clocks continue where they stopped.

        An automatic pause (someone went away) is only lifted by the host; a manual one by the
        host or by whoever paused it.

        Raises:
            GameError: Not allowed to resume this pause.
        """
        player = self._player(pid)
        if not self.paused:
            return
        if pid != self.host_id and (self.paused_reason == "afk" or pid != self.paused_by):
            raise GameError("Solo el anfitrión puede reanudar la partida")
        self.tick(now)  # the last bit of the freeze
        self.paused, self.paused_by, self.paused_reason, self.pause_started = False, None, None, None
        self._last_tick = now
        self.afk_ignored |= set(self.afk_since)  # the host chose to go on without them
        self._say(f"▶ {player.name} reanuda la partida", pid, "pause")

    # ------------------------------------------------------------------ presence

    def presence(self, pid: str, now: float, visible: bool | None = None) -> None:
        """A phone's heartbeat; ``visible`` is False while its page is hidden (locked, minimised)."""
        if pid not in self.players:
            return
        self.seen[pid] = now
        entry = self.afk_since.get(pid)
        if visible is False:
            if entry is None or entry[1] != "hidden":
                self.afk_since[pid] = (now, "hidden")
                self._touch()
        elif entry is not None and (visible is True or entry[1] == "silent"):
            if entry[1] != "hidden" or visible is True:
                self._back(pid)

    def _back(self, pid: str) -> None:
        if self.afk_since.pop(pid, None) is not None:
            self._touch()
        self.afk_ignored.discard(pid)

    def _check_afk(self, now: float) -> None:
        """Pause by itself when a connected phone has been away for too long."""
        for pid, last in self.seen.items():
            if pid in self.players and self.players[pid].connected and pid not in self.afk_since \
                    and now - last > HEARTBEAT_TIMEOUT:
                self.afk_since[pid] = (last + HEARTBEAT_TIMEOUT, "silent")  # frozen phone, dead wifi...
        due = [
            pid for pid, (since, _) in self.afk_since.items()
            if pid in self.players and pid not in self.afk_ignored and now - since >= AFK_GRACE
        ]
        if due:
            names = ", ".join(self.players[pid].name for pid in due)
            self._freeze(None, "afk", now)
            self._say(f"⏸ Pausa automática: {names} no responde. El anfitrión puede reanudar", None, "pause")

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
                "subject": cur.subject_id,
                "stage": cur.stage,
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
        reveal["subject"] = cur.subject_id
        reveal["void"] = cur.void
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
            "choice": dict(self.choice) if self.phase == CHOOSING and self.choice else None,
            "question": self._question_public(for_phone=False),
            "reveal": self._reveal_public(),
            "winners": self.winners,
            "ranking": self._ranking_ids(),
            "tiebreakPlayers": self.tiebreak_players if in_tiebreak else [],
            "maxPlayers": self.max_players,
            "chooseTime": self.timing.choose,
            "saved": self.saved_summary() if self.phase in (LOBBY, FINISHED) else None,
            "paused": self.paused,
            "pausedBy": self.paused_by,
            "pausedReason": self.paused_reason,
            "afk": sorted(p for p in self.afk_since if p in self.players),
            "pausedAt": self.pause_started,
            "away": [
                {"id": a.player.id, "name": a.player.name, "color": a.player.color, "avatar": a.player.avatar,
                 "points": a.player.points, "reason": a.reason}
                for a in self.away.values()
            ],
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
        actor = self.phase == CHOOSING and bool(self.choice) and self.choice["actorId"] == pid
        view.update(
            {
                "me": me,
                "myAnswer": my_answer,
                "exempt": bool(cur and pid in cur.exempt),
                "participant": bool(cur and pid in cur.participants),
                "offered": self.offered if actor else [],
                "categories": self._category_list() if self.phase in (LOBBY, FINISHED, CHOOSING) else [],
                "myMoves": [m for m in self.moves if m["player"] == pid] if self.phase == BOARD else [],
                "palette": [{"color": c, "name": n} for c, n in PALETTE],
                "takenColors": sorted(self.taken_colors(pid)),
                "boardSize": len(self.board),
                "mySpace": self.board.spaces[player.position] if player else None,
            }
        )
        return view
