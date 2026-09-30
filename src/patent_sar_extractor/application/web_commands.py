"""CLI startup and operator import boundaries for the local Web workbench."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from patent_sar_extractor.paths import PACKAGE_ROOT, state_dir


def web_state_path(override: str = "") -> Path:
    configured = (
        override.strip() or os.environ.get("PATENTSAR_WEB_STATE_DIR", "").strip()
    )
    result = (
        Path(configured).expanduser().resolve() if configured else state_dir() / "web"
    )
    if result == Path(result.anchor) or result == Path.home().resolve():
        raise ValueError(
            "Choose a dedicated Web state directory, not a filesystem root or home directory"
        )
    if result.is_relative_to(PACKAGE_ROOT):
        raise ValueError(
            "Web state must be outside the installed source/package directory"
        )
    if any((parent / ".git").exists() for parent in (result, *result.parents)):
        raise ValueError("Web state must be outside Git checkouts")
    return result


def frontend_path(override: str = "", *, api_only: bool = False) -> Path | None:
    if api_only:
        if override.strip():
            raise ValueError("--api-only cannot be combined with --frontend-dir")
        return None
    assets = (
        Path(override).expanduser().resolve()
        if override.strip()
        else PACKAGE_ROOT / "web" / "static"
    )
    if not (assets / "index.html").is_file():
        raise ValueError(
            "Web assets are missing. Build frontend and run tools/build_frontend.py, or install a built Web wheel"
        )
    return assets


def cmd_serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn

        from patent_sar_extractor.web.app import create_app
        from patent_sar_extractor.web.errors import WebError
    except ModuleNotFoundError as error:
        if error.name in {"uvicorn", "fastapi", "pydantic"}:
            raise SystemExit(
                "Install Web dependencies: uv sync --frozen --extra web"
            ) from None
        raise
    try:
        root = web_state_path(args.state_dir)
        assets = frontend_path(args.frontend_dir, api_only=args.api_only)
        app = create_app(
            state_root=root,
            frontend_dir=assets,
            host=args.host,
            port=args.port,
            job_timeout_seconds=args.job_timeout_hours * 3600,
        )
    except (ValueError, WebError) as error:
        raise SystemExit(str(error)) from None
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=1,
        proxy_headers=False,
        access_log=False,
        limit_concurrency=24,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=20,
    )


def cmd_import_run(args: argparse.Namespace) -> None:
    try:
        from patent_sar_extractor.web.errors import WebError
        from patent_sar_extractor.web.service import import_run
    except ModuleNotFoundError as error:
        if error.name in {"pydantic", "fastapi"}:
            raise SystemExit(
                "Install Web dependencies: uv sync --frozen --extra web"
            ) from None
        raise
    try:
        project = import_run(
            web_state_path(args.state_dir),
            Path(args.run_dir),
            title=args.title or None,
            pdf_path=Path(args.pdf) if args.pdf else None,
        )
    except (ValueError, WebError) as error:
        raise SystemExit(str(error)) from None
    print(project.model_dump_json(indent=2))
