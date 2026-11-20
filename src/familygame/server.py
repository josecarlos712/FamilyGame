"""Web server: TV page, phone page, WebSockets and question-type assets."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import io
import json
import logging
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import segno
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from familygame.categories import load_library
from familygame.config import AppConfig
from familygame.game.engine import Game, GameError
from familygame.game.picker import QuestionHistory
from familygame.questions.base import Environment
from familygame.questions.registry import load_question_types

log = logging.getLogger(__name__)

ASSET_TYPES = {
    ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".json": "application/json", ".woff2": "font/woff2",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
}
MEDIA_TYPES = {k: v for k, v in ASSET_TYPES.items() if v.startswith(("image/", "audio/"))}
PHOTO_RE = re.compile(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=\s]+)$")
PHOTO_MAGIC = {"jpeg": b"\xff\xd8", "png": b"\x89PNG", "webp": b"RIFF"}
MAX_PHOTO_BYTES = 400_000
MAX_MESSAGE = 700_000
TICK_SECONDS = 0.2


@dataclass
class Paths:
    """Folders the server reads from."""

    root: Path
    questions: Path
    question_types: Path
    web: Path
    data: Path

    @classmethod
    def from_root(cls, root: Path) -> Paths:
        return cls(root, root / "preguntas", root / "question_types", root / "web", root / "data")


def lan_ip() -> str:
    """Best guess of this PC's address on the local network."""
    with contextlib.suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent for UDP connect
            return s.getsockname()[0]
    return "127.0.0.1"


def internet_available(timeout: float = 2.0) -> bool:
    """Can we open a TCP connection to Google Maps?"""
    try:
        with socket.create_connection(("maps.googleapis.com", 443), timeout=timeout):
            return True
    except OSError:
        return False


def decode_photo(data: Any) -> tuple[bytes, str]:
    """Validate a ``data:image/...;base64,`` URL sent by a phone.

    Raises:
        GameError: If it is not a small JPEG/PNG/WebP image.
    """
    if not isinstance(data, str):
        raise GameError("Foto no válida")
    match = PHOTO_RE.match(data)
    if not match:
        raise GameError("La foto debe ser JPG, PNG o WebP")
    kind, payload = match.groups()
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise GameError("Foto dañada") from exc
    if len(raw) > MAX_PHOTO_BYTES:
        raise GameError("La foto es demasiado grande")
    if not raw.startswith(PHOTO_MAGIC[kind]):
        raise GameError("El archivo no es una imagen válida")
    return raw, f"image/{kind}"


def safe_child(base: Path, relative: str) -> Path | None:
    """Resolve ``relative`` inside ``base``; None if it escapes or does not exist."""
    try:
        base_resolved = base.resolve()
        target = (base_resolved / relative).resolve()
    except (OSError, ValueError):
        return None
    if base_resolved != target and base_resolved not in target.parents:
        return None
    return target if target.is_file() else None


class GameServer:
    """Owns the game and every connected screen."""

    def __init__(self, config: AppConfig, paths: Paths, check_internet: bool | None = None) -> None:
        self.config = config
        self.paths = paths
        check = config.check_internet if check_internet is None else check_internet
        self.env = Environment(
            internet=internet_available() if check else True,
            google_maps_api_key=config.google_maps_api_key,
        )
        self.registry = load_question_types(paths.question_types)
        library = load_library(paths.questions, self.registry, self.env)
        self.icons = sorted(p.stem for p in (paths.web / "icons").glob("*.svg"))
        history = QuestionHistory(paths.data / "historial.json" if config.remember_questions else None)
        self.game = Game(
            library,
            timing=config.timing,
            history=history,
            icons=self.icons,
            max_players=config.max_players,
        )
        self.lock = asyncio.Lock()
        self.tvs: set[WebSocket] = set()
        self.phones: dict[WebSocket, str | None] = {}
        self.photos: dict[str, tuple[bytes, str]] = {}
        self._photo_counter = 0
        self._sent_version = -1
        self.join_url = f"http://{lan_ip()}:{config.port}/"
        self.save_file = paths.data / "partida_guardada.json"
        self.autosave_file = paths.data / "autoguardado.json"
        self._saved_path: Path | None = None  # file the match shown in the menu came from
        self.last_ip: dict[str, str] = {}  # player id -> address of their phone (kept in memory only)
        self._load_saved_match()

    # ------------------------------------------------------------- saved match

    def _load_saved_match(self) -> None:
        """Pick up a match stored in an earlier run: the newest of the manual save and the autosave."""
        best: tuple[float, Path, dict[str, Any]] | None = None
        for path in (self.save_file, self.autosave_file):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if best is None or data["savedAt"] > best[0]:
                    best = (data["savedAt"], path, data)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("%s no se puede leer (%s); lo ignoro", path.name, exc)
        if best is None:
            return
        _, path, data = best
        try:
            photos = data.pop("photos", {})
            self.game.load_saved(data)
            self._saved_path = path
            for pid, (b64, mime) in photos.items():
                self.photos[pid] = (base64.b64decode(b64), mime)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("%s no es una partida válida (%s); la ignoro", path.name, exc)
            self.game.saved = None

    def _write_match(self, snapshot: dict[str, Any], path: Path) -> None:
        """Store a match (with the players' photos) so it survives a restart."""
        photos = {
            p["id"]: [base64.b64encode(self.photos[p["id"]][0]).decode("ascii"), self.photos[p["id"]][1]]
            for p in snapshot["players"]
            if p["id"] in self.photos
        }
        self.paths.data.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**snapshot, "photos": photos}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _write_saved_match(self, snapshot: dict[str, Any]) -> None:
        self._write_match(snapshot, self.save_file)
        self._saved_path = self.save_file

    def _forget_saved_match(self) -> None:
        """Delete the file the menu's saved match came from."""
        if self._saved_path is not None:
            with contextlib.suppress(OSError):
                self._saved_path.unlink()
            self._saved_path = None

    def _process_checkpoint(self, now: float) -> None:
        """Autosave at every question boundary; drop the autosave when the match is over."""
        game = self.game
        action, game.checkpoint = game.checkpoint, None
        try:
            if action == "save" and game.phase == "choosing":
                snapshot = game.snapshot(now, game.chooser_id)
                snapshot["auto"] = True
                self._write_match(snapshot, self.autosave_file)
            elif action == "clear":
                with contextlib.suppress(OSError):
                    self.autosave_file.unlink()
        except OSError as exc:
            log.warning("No se pudo escribir el autoguardado: %s", exc)

    # ----------------------------------------------------------------- info

    def static_info(self) -> dict[str, Any]:
        """Data that does not change during a session."""
        types = {}
        for type_id, cls in self.registry.types.items():
            folder = cls.assets_dir
            types[type_id] = {
                "name": cls.display_name,
                "css": bool(folder and (folder / "style.css").is_file()),
            }
        return {
            "types": types,
            "typeErrors": self.registry.errors,
            "icons": self.icons,
            "mapsKey": self.env.google_maps_api_key,
            "internet": self.env.internet,
            "joinUrl": self.join_url,
        }

    def reload_questions(self, pid: str) -> None:
        """Host re-reads the question files (edited while the server runs)."""
        if pid != self.game.host_id:
            raise GameError("Solo el anfitrión puede recargar")
        env = Environment(
            internet=internet_available() if self.config.check_internet else True,
            google_maps_api_key=self.config.google_maps_api_key,
        )
        self.env = env
        self.game.set_library(load_library(self.paths.questions, self.registry, env))

    # ----------------------------------------------------------------- sending

    async def _send(self, ws: WebSocket, message: dict[str, Any]) -> bool:
        try:
            await ws.send_text(json.dumps(message, ensure_ascii=False))
            return True
        except (WebSocketDisconnect, RuntimeError, OSError):
            return False

    async def broadcast(self, force: bool = False) -> None:
        """Send fresh state to every screen if the game changed."""
        if not force and self.game.version == self._sent_version:
            return
        self._sent_version = self.game.version
        now = time.time()
        tv_state = {"t": "state", "now": now, "state": self.game.tv_view()}
        dead: list[WebSocket] = []
        for ws in list(self.tvs):
            if not await self._send(ws, tv_state):
                dead.append(ws)
        for ws, pid in list(self.phones.items()):
            view = self.game.phone_view(pid or "")
            if not await self._send(ws, {"t": "state", "now": now, "state": view}):
                dead.append(ws)
        for ws in dead:
            self.tvs.discard(ws)
            pid = self.phones.pop(ws, None)
            if pid and pid not in self.phones.values():
                self.game.disconnect(pid, now)

    async def ticker(self) -> None:
        """Background loop advancing timers."""
        while True:
            await asyncio.sleep(TICK_SECONDS)
            async with self.lock:
                try:
                    self.game.tick(time.time())
                    self._process_checkpoint(time.time())
                    await self.broadcast()
                except Exception:  # noqa: BLE001 - keep the game loop alive whatever happens
                    log.exception("Error en el bucle del juego")

    # ----------------------------------------------------------------- phones

    def _bind(self, ws: WebSocket, pid: str) -> list[WebSocket]:
        """Attach ``ws`` to ``pid``; returns older sockets of the same player."""
        old = [w for w, p in self.phones.items() if p == pid and w is not ws]
        for w in old:
            self.phones[w] = None
        self.phones[ws] = pid
        self.last_ip[pid] = ws.client.host if ws.client else ""
        return old

    def _claimable(self, ws: WebSocket) -> list[dict[str, Any]]:
        """Players who left the match from this same address: the phone may take one back."""
        ip = ws.client.host if ws.client else ""
        return [
            {"id": a.player.id, "name": a.player.name, "color": a.player.color,
             "avatar": a.player.avatar, "points": a.player.points}
            for a in self.game.away.values()
            if a.reason == "left" and ip and self.last_ip.get(a.player.id) == ip
        ]

    def _store_photo(self, pid: str, avatar: Any) -> None:
        if isinstance(avatar, dict) and avatar.get("kind") == "photo":
            raw, mime = decode_photo(avatar.get("data"))
            self._photo_counter += 1
            self.photos[pid] = (raw, mime)
            self.game.set_photo(pid, self._photo_counter)

    async def handle_phone(self, ws: WebSocket, msg: dict[str, Any]) -> None:
        """Apply one message from a phone (called with the lock held)."""
        kind = msg.get("t")
        pid = self.phones.get(ws)
        now = time.time()
        game = self.game
        if kind == "hello":
            token = msg.get("token")
            player = game.reconnect(token) if isinstance(token, str) and token else None
            if player:
                for old in self._bind(ws, player.id):
                    await self._send(old, {"t": "replaced"})
            kicked = not player and isinstance(token, str) and game.away_reason(token) == "kicked"
            await self._send(ws, {
                "t": "welcome", "id": player.id if player else None,
                "token": player.token if player else None,
                "claimable": [] if player or kicked else self._claimable(ws),
                "kicked": kicked, **self.static_info(),
            })
            return
        if kind == "claim":  # a phone takes back the seat of someone who left from the same address
            if pid:
                raise GameError("Ya estás dentro")
            target = str(msg.get("player"))
            if target not in {c["id"] for c in self._claimable(ws)}:
                raise GameError("No se puede recuperar esa plaza desde este móvil")
            player = game.reclaim(target)
            self._bind(ws, player.id)
            await self._send(ws, {"t": "joined", "id": player.id, "token": player.token})
            return
        if kind == "join":
            if pid:
                raise GameError("Ya estás dentro")
            avatar = msg.get("avatar")
            if isinstance(avatar, dict) and avatar.get("kind") == "photo":
                decode_photo(avatar.get("data"))  # validate before creating the player
            player = game.join(msg.get("name"), msg.get("color"), avatar, now)
            self._store_photo(player.id, avatar)
            self._bind(ws, player.id)
            await self._send(ws, {"t": "joined", "id": player.id, "token": player.token})
            return
        if not pid or pid not in game.players:
            raise GameError("Primero tienes que entrar en la partida")
        if kind == "profile":
            avatar = msg.get("avatar")
            game.update_profile(pid, msg.get("name"), msg.get("color"), avatar)
            self._store_photo(pid, avatar)
        elif kind == "settings":
            changes = msg.get("changes")
            game.set_settings(pid, changes if isinstance(changes, dict) else {})
        elif kind == "start":
            game.start(pid, now)
        elif kind == "choose":
            game.choose(pid, str(msg.get("category")), now)
        elif kind == "spin":
            game.spin(pid, now)
        elif kind == "answer":
            game.submit_answer(pid, msg.get("value"), now)
        elif kind == "unavailable":
            game.report_unavailable(pid, now)
        elif kind == "next":
            game.skip_wait(pid, now)
        elif kind == "lobby":
            game.back_to_lobby(pid)
        elif kind == "save":
            self._write_saved_match(game.save_and_exit(pid, now))
        elif kind == "resume":
            game.resume(pid, now)
            self._forget_saved_match()
        elif kind == "discard":
            game.discard_saved(pid)
            self._forget_saved_match()
        elif kind == "reload":
            self.reload_questions(pid)
        elif kind == "ping":  # heartbeat; "visible" is False while the page is hidden
            visible = msg.get("visible")
            game.presence(pid, now, visible if isinstance(visible, bool) else None)
        elif kind == "pause":
            game.pause(pid, now)
        elif kind == "unpause":
            game.unpause(pid, now)
        elif kind == "host":
            game.set_host(pid, str(msg.get("player")))
        elif kind == "readmit":
            game.readmit(pid, str(msg.get("player")))
        elif kind == "forget":
            target = str(msg.get("player"))
            game.forget_away(pid, target)
            self.photos.pop(target, None)
        elif kind == "assign":  # the host says a newcomer is really someone who left
            target = str(msg.get("player"))
            game.assign_away(pid, str(msg.get("new")), target)
            self.photos.pop(target, None)
        elif kind in ("kick", "leave"):
            target = pid if kind == "leave" else str(msg.get("player"))
            game.remove(target, pid, now)
            if target not in game.away:  # their seat is reserved: keep the photo for when they return
                self.photos.pop(target, None)
            for w, p in list(self.phones.items()):
                if p == target:
                    self.phones[w] = None
                    await self._send(w, {"t": "kicked" if kind == "kick" else "left"})
        else:
            raise GameError("Mensaje desconocido")

    async def phone_socket(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.phones[ws] = None
        try:
            while True:
                text = await ws.receive_text()
                msg: Any = None
                async with self.lock:
                    try:
                        if len(text) > MAX_MESSAGE:
                            raise GameError("Mensaje demasiado grande")
                        msg = json.loads(text)
                        if not isinstance(msg, dict):
                            raise GameError("Mensaje no válido")
                        await self.handle_phone(ws, msg)
                    except (GameError, ValueError) as exc:
                        await self._send(ws, {"t": "error", "msg": str(exc)})
                    self.game.tick(time.time())
                    self._process_checkpoint(time.time())
                    await self.broadcast(force=msg.get("t") == "hello" if isinstance(msg, dict) else False)
        except WebSocketDisconnect:
            pass
        finally:
            async with self.lock:
                pid = self.phones.pop(ws, None)
                if pid and pid not in self.phones.values():
                    self.game.disconnect(pid, time.time())
                await self.broadcast()

    async def tv_socket(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.tvs.add(ws)
            await self._send(ws, {"t": "welcome", **self.static_info()})
            await self.broadcast(force=True)
        try:
            while True:
                await ws.receive_text()  # the TV only listens
        except WebSocketDisconnect:
            pass
        finally:
            async with self.lock:
                self.tvs.discard(ws)


def create_app(config: AppConfig, paths: Paths, check_internet: bool | None = None) -> Starlette:
    """Build the Starlette application."""
    server = GameServer(config, paths, check_internet)

    async def phone_page(request: Request) -> Response:
        return FileResponse(paths.web / "phone.html", headers={"Cache-Control": "no-cache"})

    async def tv_page(request: Request) -> Response:
        return FileResponse(paths.web / "tv.html", headers={"Cache-Control": "no-cache"})

    async def qtype_asset(request: Request) -> Response:
        cls = server.registry.types.get(request.path_params["qtype"])
        rel = request.path_params["file"]
        suffix = Path(rel).suffix.lower()
        if cls is None or cls.assets_dir is None or suffix not in ASSET_TYPES:
            return Response(status_code=404)
        target = safe_child(cls.assets_dir, rel)
        if target is None:
            return Response(status_code=404)
        return FileResponse(target, media_type=ASSET_TYPES[suffix], headers={"Cache-Control": "no-cache"})

    async def media(request: Request) -> Response:
        rel = request.path_params["file"]
        suffix = Path(rel).suffix.lower()
        target = safe_child(paths.questions, rel) if suffix in MEDIA_TYPES else None
        if target is None:
            return Response(status_code=404)
        return FileResponse(target, media_type=MEDIA_TYPES[suffix])

    async def avatar(request: Request) -> Response:
        photo = server.photos.get(request.path_params["pid"])
        if photo is None:
            return Response(status_code=404)
        return Response(photo[0], media_type=photo[1], headers={"Cache-Control": "max-age=86400"})

    async def qr(request: Request) -> Response:
        buffer = io.BytesIO()
        segno.make(server.join_url, error="m").save(
            buffer, kind="svg", scale=10, border=2, dark="#14151c", light="#ffffff"
        )
        return Response(buffer.getvalue(), media_type="image/svg+xml")

    async def info(request: Request) -> Response:
        return JSONResponse(server.static_info())

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(server.ticker())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = Starlette(
        routes=[
            Route("/", phone_page),
            Route("/movil", phone_page),
            Route("/tv", tv_page),
            Route("/qr.svg", qr),
            Route("/api/info", info),
            Route("/avatar/{pid}", avatar),
            Route("/qtypes/{qtype}/{file:path}", qtype_asset),
            Route("/media/{file:path}", media),
            WebSocketRoute("/ws/phone", server.phone_socket),
            WebSocketRoute("/ws/tv", server.tv_socket),
            Mount("/static", StaticFiles(directory=paths.web), name="static"),
        ],
        lifespan=lifespan,
    )
    app.state.server = server
    return app
