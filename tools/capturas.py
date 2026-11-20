"""Regenerate the README screenshots (docs/img) with headless Edge driven over DevTools.

Usage::

    .venv\\Scripts\\python tools\\capturas.py

For every demo scene (see ``tools/demo.py``) it captures the TV at 1920x1080 and,
for some scenes, Ana's phone at 390x844 (x2).
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
GAME_PORT = 8001
DEBUG_PORT = 9333
SCENES = ["lobby", "choosing", "question", "reveal", "board", "finished"]  # map scenes: see note below
PHONE_SCENES = {"lobby": "Ana", "choosing": "Ana", "question": "Ana", "reveal": "Marta",
                "mapa": "Ana", "mapa-reveal": "Ana"}
MAP_SCENES = {"mapa", "mapa-reveal"}  # Google Maps tiles take longer to load


class Tab:
    """Minimal Chrome DevTools Protocol client for one page."""

    def __init__(self, ws_url: str) -> None:
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024).__enter__()
        self.next_id = 0

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        """Send a command and wait for its result, skipping events.

        Args:
            method: CDP method name.
            **params: Method parameters.

        Returns:
            The ``result`` object of the response.

        Raises:
            RuntimeError: If the browser answers with an error.
        """
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def shot(self, url: str, file: Path, width: int, height: int, scale: float, wait: float,
             click: tuple[int, int] | None = None) -> None:
        """Load ``url`` at the given viewport and save a PNG.

        Args:
            url: Page to open.
            file: Output PNG path.
            width: Viewport width in CSS pixels.
            height: Viewport height in CSS pixels.
            scale: Device pixel ratio.
            wait: Seconds to let the page render.
        """
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                  deviceScaleFactor=scale, mobile=width < 800)
        self.call("Page.navigate", url=url)
        time.sleep(wait)
        if click:
            x, y = click
            self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
            time.sleep(0.3)
            for kind in ("mousePressed", "mouseReleased"):
                self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1)
                time.sleep(0.1)
            time.sleep(1.5)
        data = self.call("Page.captureScreenshot", format="png")["data"]
        file.write_bytes(base64.b64decode(data))
        print("OK", file.relative_to(ROOT))


def wait_http(url: str, seconds: float = 15) -> None:
    """Poll ``url`` until it answers.

    Args:
        url: Address to poll.
        seconds: Maximum wait.

    Raises:
        TimeoutError: If it never answers.
    """
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(url)


def open_tab() -> Tab:
    """Open a blank page in the debugged browser."""
    req = urllib.request.Request(f"http://127.0.0.1:{DEBUG_PORT}/json/new?about:blank", method="PUT")
    with urllib.request.urlopen(req) as resp:
        return Tab(json.load(resp)["webSocketDebuggerUrl"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="familygame-capturas-")
    edge = subprocess.Popen(
        [str(EDGE), "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
         "--ignore-gpu-blocklist", "--hide-scrollbars", "--mute-audio",  # software WebGL for Google Maps
         f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_http(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
        tab = open_tab()
        tab.call("Page.enable")
        tab.call("Emulation.setEmulatedMedia",
                 features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        base = f"http://127.0.0.1:{GAME_PORT}"
        for scene in sys.argv[1:] or SCENES:  # optionally only some scenes
            server = subprocess.Popen([str(PYTHON), "tools/demo.py", scene, str(GAME_PORT)], cwd=ROOT)
            try:
                wait_http(f"{base}/api/info")
                wait = 14 if scene in MAP_SCENES else 3
                tab.shot(f"{base}/tv", OUT / f"tv-{scene}.png", 1920, 1080, 1, wait)
                who = PHONE_SCENES.get(scene)
                if who:
                    tokens = json.loads((ROOT / "data" / "demo_tokens.json").read_text("utf-8"))
                    tab.call("Page.navigate", url=f"{base}/api/info")
                    time.sleep(0.5)
                    value = json.dumps(json.dumps(tokens[who]))
                    tab.call("Runtime.evaluate", expression=f"localStorage.setItem('fg.token', {value})")
                    tab.shot(f"{base}/", OUT / f"movil-{scene}.png", 390, 844, 2, wait,
                             click=(215, 330) if scene == "mapa" else None)
            finally:
                # the venv launcher spawns a child python: kill the whole tree
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(server.pid)], capture_output=True)
                time.sleep(0.8)
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(edge.pid)], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())

