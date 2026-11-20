"""HTTP interface of the question editor (separate from the game server)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from familygame.editor.service import EditorError, EditorPaths, EditorService

MAX_TEXT = 400_000


async def _body(request: Request) -> dict[str, Any]:
    """JSON body of a POST.

    Requiring ``application/json`` means a page from another site cannot post
    here without a CORS preflight, which this server never answers.
    """
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise EditorError("se esperaba JSON")
    raw = await request.body()
    if len(raw) > MAX_TEXT:
        raise EditorError("el texto es demasiado largo")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EditorError("JSON no válido") from exc
    if not isinstance(data, dict):
        raise EditorError("JSON no válido")
    return data


def create_editor_app(root: Path, paths: EditorPaths | None = None) -> Starlette:
    """Build the editor app for the project at ``root``.

    Args:
        root: Project folder (its ``web/`` holds the editor page).
        paths: Folders to work on; by default the project's own.
    """
    service = EditorService(paths or EditorPaths.from_root(root))
    web = root / "web"

    def state() -> dict[str, Any]:
        return {
            "categories": service.categories(),
            "types": service.types(),
            "errors": [*service.registry.errors, *service.formats.errors],
        }

    async def page(_: Request) -> Response:
        return FileResponse(web / "editor" / "index.html")

    async def get_state(_: Request) -> Response:
        return JSONResponse(state())

    async def reload(_: Request) -> Response:
        service.reload()
        return JSONResponse(state())

    async def review(request: Request) -> Response:
        try:
            data = await _body(request)
            items = service.review(str(data.get("text", "")), str(data.get("tipo", "test")))
        except EditorError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"items": items})

    async def add(request: Request) -> Response:
        try:
            data = await _body(request)
            new = data.get("nueva")
            result = service.add(
                str(data.get("text", "")),
                str(data.get("tipo", "test")),
                target=str(data.get("archivo") or "") or None,
                new=new if isinstance(new, dict) else None,
            )
        except EditorError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        result["categories"] = service.categories()
        return JSONResponse(result)

    app = Starlette(
        routes=[
            Route("/", page),
            Route("/api/estado", get_state),
            Route("/api/recargar", reload, methods=["POST"]),
            Route("/api/revisar", review, methods=["POST"]),
            Route("/api/anadir", add, methods=["POST"]),
            Mount("/static", StaticFiles(directory=web), name="static"),
        ]
    )
    app.state.service = service
    return app
