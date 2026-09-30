"""Loopback Host/Origin, private sessions, write CSRF, and body limits."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import secrets
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import WebError
from .storage import Store

COOKIE_NAME = "patentsar_session"
SESSION_SECONDS = 8 * 60 * 60


def loopback_host(host: str) -> str:
    if host == "localhost":
        return host
    try:
        if ipaddress.ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    raise WebError(
        400,
        "loopback_required",
        "Web server may bind only to a literal loopback address or localhost.",
    )


class Sessions:
    def __init__(self, store: Store) -> None:
        self.store = store

    def lookup(self, token: str | None) -> dict[str, Any] | None:
        if not token or len(token) > 200:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                (digest, time.time()),
            ).fetchone()
        return dict(row) if row else None

    def bootstrap(self, request: Request) -> JSONResponse:
        token = request.cookies.get(COOKIE_NAME)
        session = self.lookup(token)
        if session is None:
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            with self.store.connect(write=True) as connection:
                connection.execute(
                    "DELETE FROM sessions WHERE expires_at<=?", (time.time(),)
                )
                if (
                    connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                    >= 4096
                ):
                    raise WebError(
                        413,
                        "session_limit",
                        "Workspace session limit has been reached.",
                    )
                connection.execute(
                    "INSERT INTO sessions VALUES(?,?,?)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        csrf,
                        time.time() + SESSION_SECONDS,
                    ),
                )
            session = {"csrf_token": csrf}
        response = JSONResponse(
            {"csrf_token": session["csrf_token"], "user": {"name": "本地操作员"}}
        )
        assert token is not None
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
            max_age=SESSION_SECONDS,
        )
        return response


class SecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        store: Store,
        host: str,
        port: int,
        max_upload_bytes: int,
        body_timeout_seconds: float = 120,
        body_idle_seconds: float = 15,
    ) -> None:
        self.app = app
        self.sessions = Sessions(store)
        host = loopback_host(host)
        addresses = {host, "localhost", "127.0.0.1", "::1"}
        self.hosts = {
            f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
            for address in addresses
        }
        if port in (80, 443):
            self.hosts.update(
                f"[{address}]" if ":" in address else address for address in addresses
            )
        self.max_upload_bytes = max_upload_bytes
        self.body_timeout_seconds = body_timeout_seconds
        self.body_idle_seconds = body_idle_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            hosts = [
                v.decode("latin1") for k, v in scope["headers"] if k.lower() == b"host"
            ]
            if len(hosts) != 1 or hosts[0].lower() not in self.hosts:
                raise WebError(
                    403, "invalid_host", "Host is not an allowed loopback authority."
                )
            if (
                len(request.url.path) > 4096
                or len(scope.get("query_string", b"")) > 8192
            ):
                raise WebError(413, "request_limit", "Request URL exceeds its limit.")
            for header in (b"origin", b"x-csrf-token"):
                values = [
                    value for key, value in scope["headers"] if key.lower() == header
                ]
                if len(values) > 1:
                    raise WebError(
                        403,
                        "duplicate_security_header",
                        "Origin and CSRF headers must not be duplicated.",
                    )
            csrf_header = request.headers.get("x-csrf-token", "")
            if len(csrf_header) > 128 or not csrf_header.isascii():
                raise WebError(403, "csrf_required", "CSRF token is invalid.")
            origin = request.headers.get("origin")
            expected = f"{scope.get('scheme', 'http')}://{hosts[0]}"
            if origin is not None and origin != expected:
                raise WebError(
                    403,
                    "invalid_origin",
                    "Origin must exactly match this local server.",
                )
            if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                raise WebError(
                    403, "cross_site", "Cross-site requests are not allowed."
                )
            path = request.url.path
            is_api = path == "/api" or path.startswith("/api/")
            is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
            if is_api and path not in {"/api/v1/health", "/api/v1/session"}:
                session = self.sessions.lookup(request.cookies.get(COOKIE_NAME))
                if session is None:
                    raise WebError(
                        401,
                        "session_required",
                        "Start a same-origin local session before using the API.",
                    )
                if is_write and (
                    origin is None
                    or not hmac.compare_digest(csrf_header, session["csrf_token"])
                ):
                    raise WebError(
                        403,
                        "csrf_required",
                        "A session-bound CSRF token and valid Origin are required.",
                    )
            elif is_write:
                raise WebError(
                    405, "method_not_allowed", "This resource does not accept writes."
                )
        except WebError as exc:
            await JSONResponse(exc.payload(), status_code=exc.status)(
                scope, receive, send
            )
            return
        limit = (
            self.max_upload_bytes
            if request.headers.get("content-type", "").split(";", 1)[0]
            == "application/pdf"
            else 8 * 1024 * 1024
            if path.endswith("/export")
            else 65536
        )
        consumed = 0
        started = time.monotonic()

        async def bounded_receive() -> Message:
            nonlocal consumed
            remaining = self.body_timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise WebError(
                    408, "body_timeout", "Request body exceeded its receive timeout."
                )
            try:
                message = await asyncio.wait_for(
                    receive(), timeout=min(remaining, self.body_idle_seconds)
                )
            except TimeoutError as exc:
                raise WebError(
                    408, "body_timeout", "Request body exceeded its receive timeout."
                ) from exc
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise WebError(
                        413, "request_limit", "Request body exceeds its limit."
                    )
            return message

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                    (b"cross-origin-resource-policy", b"same-origin"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                    ),
                ]
            await send(message)

        await self.app(scope, bounded_receive, secure_send)
