"""Jugadores bot para probar partidas sin móviles.

Uso:
    .venv\\Scripts\\python tools\\bots.py [--puerto 8765] [--bots 2] [--jugadores 3]
        [--mecanicas ruleta,moneda,rival,eleccion] [--rondas N]

El primer bot que entra es el anfitrión: activa solo las mecánicas indicadas y empieza la partida
cuando hay `--jugadores` jugadores (bots + los que entren desde el navegador). Los bots giran la
ruleta, lanzan la moneda o eligen la primera categoría ofrecida, y responden con la opción 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import websockets

PENDING: set[asyncio.Task] = set()  # referencias para que no se recojan las tareas
ALL = ["ruleta", "moneda", "rival", "eleccion"]
COLORS = ["#4dabf7", "#51cf66", "#9c8cff", "#ffa94d", "#3bc9db"]


async def bot(n: int, args: argparse.Namespace) -> None:
    """Conecta un bot y juega hasta que se cierre la conexión."""
    url = f"ws://localhost:{args.puerto}/ws/phone"
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"t": "hello", "token": None}))
        await ws.send(json.dumps({"t": "join", "name": f"Bot {n + 1}", "color": COLORS[n % 5],
                                  "avatar": {"kind": "icon", "value": "gato"}}))
        me = None
        configured = started = False
        acted: set[str] = set()
        seen_match = False
        last_choice: dict | None = None
        done_rounds = 0
        answered: set[str] = set()
        async for raw in ws:
            msg = json.loads(raw)
            if msg["t"] == "joined":
                me = msg["id"]
            if msg["t"] == "error":
                print(f"[bot {n + 1}] error: {msg.get('msg')}")
            if msg["t"] != "state" or me is None:
                continue
            s, now = msg["state"], msg["now"]
            phase = s.get("phase")
            if phase == "lobby" and seen_match:
                return
            if phase != "lobby":
                seen_match = True
            choice = s.get("choice") or {}
            if phase == "choosing" and choice.get("result"):
                last_choice = choice
            elif last_choice and phase in ("reading", "answering"):
                if n == 0:
                    names = {p["id"]: p.get("name") for p in s.get("players", [])}
                    c = last_choice
                    print(f"mecánica={c['mechanic']} actor={names.get(c.get('actorId'))} "
                          f"chooser={names.get(c.get('chooserId'))} resultado={c['result']} "
                          f"outcome={c.get('outcome') or '-'} ofrecidas={len(c.get('offered') or [])}", flush=True)
                last_choice = None
                done_rounds += 1
                if n == 0 and args.rondas and done_rounds >= args.rondas:
                    await ws.send(json.dumps({"t": "lobby"}))
            host = s.get("hostId") == me
            if phase == "lobby" and host and not configured:
                configured = True
                active = set(s.get("settings", {}).get("mechanics", ALL))
                for mech in ALL:
                    if (mech in active) != (mech in args.mecanicas):
                        await ws.send(json.dumps({"t": "settings", "changes": {"toggleMechanic": mech}}))
            if phase == "lobby" and host and not started and len(s.get("players", [])) >= args.jugadores:
                started = True
                await asyncio.sleep(1)
                await ws.send(json.dumps({"t": "start"}))
            key = f"{s.get('round')}-{choice.get('introUntil')}"
            if phase == "choosing" and choice.get("actorId") == me and key not in acted:
                acted.add(key)
                wait = max(0.0, choice["introUntil"] - now) + 1.5
                task = asyncio.create_task(act(ws, choice, wait))
                PENDING.add(task)
                task.add_done_callback(PENDING.discard)
            qkey = f"{s.get('round')}-{s.get('deadline')}"
            if phase == "answering" and qkey not in answered:
                answered.add(qkey)
                await asyncio.sleep(1 + n)
                await ws.send(json.dumps({"t": "answer", "value": answer_for(s.get("question") or {})}))


def answer_for(q: dict) -> object:
    """Valor de respuesta válido según el tipo de pregunta."""
    d = q.get("data") or {}
    kind = q.get("type")
    if kind == "slider":
        return d["min"] + (d["max"] - d["min"]) / 2
    if kind == "rango":
        mid = d["min"] + (d["max"] - d["min"]) / 2
        return [d["min"], mid]
    if kind == "mapa":
        return {"lat": 40.4, "lng": -3.7}
    return 0  # test, conoces: índice de opción mostrada


async def act(ws: websockets.ClientConnection, choice: dict, wait: float = 0.0) -> None:
    """Espera `wait` segundos y gira, lanza o elige según la mecánica."""
    await asyncio.sleep(wait)
    if choice["mechanic"] in ("ruleta", "moneda"):
        await ws.send(json.dumps({"t": "spin"}))
    else:
        await ws.send(json.dumps({"t": "choose", "category": choice["offered"][0]}))


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--bots", type=int, default=2)
    p.add_argument("--jugadores", type=int, default=2)
    p.add_argument("--mecanicas", default=",".join(ALL))
    p.add_argument("--rondas", type=int, default=0)
    args = p.parse_args()
    args.mecanicas = args.mecanicas.split(",")
    tasks = []
    for n in range(args.bots):
        tasks.append(asyncio.create_task(bot(n, args)))
        await asyncio.sleep(0.5)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(main())
