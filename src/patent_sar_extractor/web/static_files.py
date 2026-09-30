"""Serve only built local frontend assets; never package evidence or API fallbacks."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from starlette.responses import Response

from .errors import WebError
from .files import SafeFiles


def ui_ready(frontend: Path) -> bool:
    if not frontend.is_dir() or frontend.is_symlink():
        return False
    try:
        with SafeFiles(frontend).open("index.html", max_bytes=2 * 1024 * 1024):
            return True
    except WebError:
        return False


def serve_frontend(frontend: Path, path: str) -> Response:
    if path == "api" or path.startswith("api/"):
        raise WebError(404, "endpoint_not_found", "API endpoint does not exist.")
    parts = Path(path).parts
    if any(part.startswith(".") for part in parts) or "\\" in path:
        raise WebError(404, "asset_unavailable", "Static asset is not available.")
    if not ui_ready(frontend):
        raise WebError(
            503,
            "ui_not_built",
            "Web UI is not built. Build and package the local frontend before opening the workspace.",
        )
    asset = path if path and Path(path).suffix else "index.html"
    if asset.endswith((".map", ".json")):
        raise WebError(
            404, "asset_unavailable", "Static evidence and source maps are not served."
        )
    data = SafeFiles(frontend).read(asset, max_bytes=16 * 1024 * 1024)
    media_type = mimetypes.guess_type(asset)[0] or "application/octet-stream"
    return Response(data, media_type=media_type)
