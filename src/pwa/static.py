from __future__ import annotations

from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import PwaSettings


def frontend_index_response(request: Request, settings: PwaSettings | None = None) -> Response:
    current = settings or PwaSettings.from_env()
    index = current.frontend_dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return PlainTextResponse("Bode Andarilho Bot - Online")


def frontend_routes(settings: PwaSettings | None = None) -> list[Route | Mount]:
    current = settings or PwaSettings.from_env()
    dist = current.frontend_dist
    if not dist.exists():
        return []

    async def manifest(request: Request) -> Response:
        path = dist / "manifest.webmanifest"
        return FileResponse(path) if path.exists() else Response(status_code=404)

    async def service_worker(request: Request) -> Response:
        path = dist / "sw.js"
        return FileResponse(path, media_type="application/javascript") if path.exists() else Response(status_code=404)

    async def fallback(request: Request) -> Response:
        requested_path = request.path_params.get("path", "")
        if requested_path.startswith(("api/", "telegram/", "webhook/")):
            return Response(status_code=404)
        requested = dist / requested_path
        try:
            inside_dist = dist == requested.resolve() or dist in requested.resolve().parents
        except OSError:
            inside_dist = False
        if inside_dist and requested.is_file():
            return FileResponse(requested)
        return frontend_index_response(request, current)

    routes: list[Route | Mount] = []
    assets = dist / "assets"
    if assets.exists():
        routes.append(Mount("/assets", app=StaticFiles(directory=str(assets)), name="pwa-assets"))
    routes.extend(
        [
            Route("/manifest.webmanifest", manifest, methods=["GET"]),
            Route("/sw.js", service_worker, methods=["GET"]),
            Route("/{path:path}", fallback, methods=["GET"]),
        ]
    )
    return routes
