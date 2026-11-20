"""Server: routes, asset safety and the WebSocket protocol."""

from __future__ import annotations

import base64
import contextlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from familygame.config import AppConfig
from familygame.server import Paths, create_app, decode_photo
from familygame.game.engine import GameError

JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 100).decode()


@pytest.fixture
def client(root: Path, tmp_path: Path) -> TestClient:
    paths = Paths.from_root(root)
    paths.data = tmp_path  # keep the question history out of the repo
    config = AppConfig()
    config.timing.choose = 0.1  # the engine acts for the chooser right after the intro
    app = create_app(config, paths, check_internet=False)
    with TestClient(app) as c:
        yield c


def recv_until(ws, kind: str, limit: int = 20) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["t"] == kind:
            return msg
    raise AssertionError(f"no llegó {kind}")


def test_pages_and_assets(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/tv").status_code == 200
    assert client.get("/qr.svg").headers["content-type"].startswith("image/svg")
    assert client.get("/qtypes/test/tv.js").status_code == 200
    assert client.get("/qtypes/test/type.py").status_code == 404  # python source not served
    assert client.get("/qtypes/test/..%2F..%2Fconfig.toml").status_code == 404
    assert client.get("/media/../config.toml").status_code == 404
    assert client.get("/static/icons/gato.svg").status_code == 200
    info = client.get("/api/info").json()
    assert "test" in info["types"] and "gato" in info["icons"]


def test_photo_validation() -> None:
    raw, mime = decode_photo(JPEG)
    assert mime == "image/jpeg" and raw.startswith(b"\xff\xd8")
    with pytest.raises(GameError):
        decode_photo("data:image/jpeg;base64," + base64.b64encode(b"<svg>").decode())
    with pytest.raises(GameError):
        decode_photo("data:text/html;base64,AAAA")


def test_join_start_and_answer_over_websockets(client: TestClient) -> None:
    with client.websocket_connect("/ws/tv") as tv, client.websocket_connect("/ws/phone") as phone:
        assert recv_until(tv, "welcome")["joinUrl"].startswith("http://")
        phone.send_json({"t": "hello", "token": None})
        assert recv_until(phone, "welcome")["id"] is None
        phone.send_json({"t": "join", "name": "Ana", "color": "#ff6b6b",
                         "avatar": {"kind": "photo", "data": JPEG}})
        joined = recv_until(phone, "joined")
        state = recv_until(phone, "state")["state"]
        assert state["me"]["name"] == "Ana" and state["me"]["host"]
        assert client.get(state["me"]["avatar"]["url"]).content.startswith(b"\xff\xd8")

        phone.send_json({"t": "join", "name": "Otra", "color": "#ffa94d", "avatar": {"kind": "icon", "value": "gato"}})
        assert "Ya estás" in recv_until(phone, "error")["msg"]

        for mech in ("ruleta", "moneda", "rival"):
            phone.send_json({"t": "settings", "changes": {"toggleMechanic": mech}})
        phone.send_json({"t": "start"})
        for _ in range(20):
            state = recv_until(phone, "state")["state"]
            if state["phase"] == "choosing":
                break
        assert state["offered"] and state["choice"]["mechanic"] == "eleccion"
        phone.send_json({"t": "choose", "category": state["offered"][0]})
        assert "Espera" in recv_until(phone, "error")["msg"]  # still in the announcement
        for _ in range(100):  # the engine picks for Ana once the announcement and the wait are over
            state = recv_until(phone, "state")["state"]
            if state["phase"] in ("reading", "answering"):
                break
        assert state["phase"] in ("reading", "answering")
        for _ in range(20):
            tv_state = recv_until(tv, "state")["state"]
            if tv_state["phase"] in ("reading", "answering"):
                break
        assert tv_state["players"][0]["name"] == "Ana"

    # reconnect with the token
    with client.websocket_connect("/ws/phone") as phone:
        phone.send_json({"t": "hello", "token": joined["token"]})
        assert recv_until(phone, "welcome")["id"] == joined["id"]


def test_garbage_messages_do_not_crash(client: TestClient) -> None:
    with client.websocket_connect("/ws/phone") as phone:
        phone.send_text("no es json")
        assert recv_until(phone, "error")
        phone.send_json({"t": "start"})
        assert "Primero" in recv_until(phone, "error")["msg"]
        phone.send_json(["lista"])
        assert recv_until(phone, "error")


def test_config_local_overrides_config(tmp_path):
    """config.local.toml (git-ignored) overrides config.toml, e.g. for the Maps key."""
    from familygame.config import load_config

    (tmp_path / "config.toml").write_text('[mapas]\ngoogle_maps_api_key = ""\n[servidor]\npuerto = 8765\n', encoding="utf-8")
    (tmp_path / "config.local.toml").write_text('[mapas]\ngoogle_maps_api_key = "abc"\n', encoding="utf-8")
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.google_maps_api_key == "abc"
    assert cfg.port == 8765


def test_saved_match_survives_a_restart(root: Path, tmp_path: Path) -> None:
    paths = Paths.from_root(root)
    paths.data = tmp_path
    config = AppConfig()
    config.timing.choose = 0.1  # the engine acts for the chooser right after the intro
    app = create_app(config, paths, check_internet=False)
    with TestClient(app) as c, c.websocket_connect("/ws/phone") as phone:
        phone.send_json({"t": "hello", "token": None})
        recv_until(phone, "welcome")
        phone.send_json({"t": "join", "name": "Ana", "color": "#ff6b6b", "avatar": {"kind": "photo", "data": JPEG}})
        token = recv_until(phone, "joined")["token"]
        for mech in ("ruleta", "moneda", "rival"):
            phone.send_json({"t": "settings", "changes": {"toggleMechanic": mech}})
        phone.send_json({"t": "start"})
        recv_until(phone, "state")
        phone.send_json({"t": "save"})
        for _ in range(20):
            state = recv_until(phone, "state")["state"]
            if state["phase"] == "lobby" and state["saved"]:
                break
        assert state["saved"]["players"] == ["Ana"]
    assert (tmp_path / "partida_guardada.json").is_file()

    app2 = create_app(AppConfig(), paths, check_internet=False)  # "restart"
    with TestClient(app2) as c2, c2.websocket_connect("/ws/phone") as phone:
        phone.send_json({"t": "hello", "token": token})
        assert recv_until(phone, "welcome")["id"] is not None  # the phone gets Ana back
        phone.send_json({"t": "resume"})
        for _ in range(20):
            state = recv_until(phone, "state")["state"]
            if state["phase"] == "choosing":
                break
        assert state["phase"] == "choosing" and state["saved"] is None
        assert c2.get(state["me"]["avatar"]["url"]).content.startswith(b"\xff\xd8")  # photo restored
    assert not (tmp_path / "partida_guardada.json").exists()


def _join(c: TestClient, stack, name: str, color: str):
    phone = stack.enter_context(c.websocket_connect("/ws/phone"))
    phone.send_json({"t": "hello", "token": None})
    welcome = recv_until(phone, "welcome")
    phone.send_json({"t": "join", "name": name, "color": color, "avatar": {"kind": "icon", "value": "gato"}})
    joined = recv_until(phone, "joined")
    return phone, welcome, joined


def _state(phone, until=lambda s: True) -> dict:
    for _ in range(40):
        state = recv_until(phone, "state")["state"]
        if until(state):
            return state
    raise AssertionError("state not reached")


def test_leave_come_back_by_address_kick_pause_and_autosave(root: Path, tmp_path: Path) -> None:
    paths = Paths.from_root(root)
    paths.data = tmp_path
    config = AppConfig()
    config.timing.choose = 0.1  # the engine acts for the chooser right after the intro
    app = create_app(config, paths, check_internet=False)
    with TestClient(app) as c, contextlib.ExitStack() as stack:
        ana, _, ana_j = _join(c, stack, "Ana", "#ff6b6b")
        luis, _, luis_j = _join(c, stack, "Luis", "#4dabf7")
        ana.send_json({"t": "start"})
        _state(ana, lambda s: s["phase"] == "choosing")
        assert (tmp_path / "autoguardado.json").is_file()  # autosave at the question boundary

        luis.send_json({"t": "leave"})  # Luis leaves mid-match
        state = _state(ana, lambda s: s["away"])
        assert [p["name"] for p in state["players"]] == ["Ana"] and state["away"][0]["reason"] == "left"
        luis.close()

        again = stack.enter_context(c.websocket_connect("/ws/phone"))  # same address, new phone session, no token
        again.send_json({"t": "hello", "token": None})
        welcome = recv_until(again, "welcome")
        assert [x["name"] for x in welcome["claimable"]] == ["Luis"]  # recognised by address
        again.send_json({"t": "claim", "player": welcome["claimable"][0]["id"]})
        assert recv_until(again, "joined")["id"] == luis_j["id"]
        assert not _state(ana, lambda s: not s["away"])["away"]

        ana.send_json({"t": "pause"})  # anyone pauses; only the host resumes an automatic pause
        assert _state(ana, lambda s: s["paused"])["pausedReason"] == "manual"
        again.send_json({"t": "unpause"})
        assert "anfitrión" in recv_until(again, "error")["msg"]
        ana.send_json({"t": "unpause"})
        assert not _state(ana, lambda s: not s["paused"])["paused"]

        ana.send_json({"t": "kick", "player": luis_j["id"]})  # the host kicks Luis: no automatic recognition
        _state(ana, lambda s: s["away"] and s["away"][0]["reason"] == "kicked")
        fresh = stack.enter_context(c.websocket_connect("/ws/phone"))
        fresh.send_json({"t": "hello", "token": None})
        assert recv_until(fresh, "welcome")["claimable"] == []
        stale = stack.enter_context(c.websocket_connect("/ws/phone"))
        stale.send_json({"t": "hello", "token": luis_j["token"]})
        assert recv_until(stale, "welcome")["kicked"] is True  # his phone is told, and keeps the token
        ana.send_json({"t": "readmit", "player": luis_j["id"]})
        stale.send_json({"t": "hello", "token": luis_j["token"]})
        assert recv_until(stale, "welcome")["id"] == luis_j["id"]  # the host brought him back


def test_same_player_in_two_tabs_gets_a_notice(client: TestClient) -> None:
    with client.websocket_connect("/ws/phone") as first:
        first.send_json({"t": "hello", "token": None})
        recv_until(first, "welcome")
        first.send_json({"t": "join", "name": "Ana", "color": "#ff6b6b", "avatar": {"kind": "icon", "value": "gato"}})
        token = recv_until(first, "joined")["token"]
        with client.websocket_connect("/ws/phone") as second:
            second.send_json({"t": "hello", "token": token})
            assert recv_until(second, "welcome")["id"] is not None
            recv_until(first, "replaced")  # the older tab is told to step aside
