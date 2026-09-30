from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest
from pathlib import Path

import httpx2 as httpx
import uvicorn
from test_web_support import BASE_URL, WebFixture

from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.errors import WebError


class BoundaryTests(WebFixture, unittest.TestCase):
    def test_non_ascii_oversized_and_duplicate_security_headers(self):
        with self.client() as client:
            for value in (b"\xff", b"x" * 129):
                response = client.post(
                    "/api/v1/projects?filename=a.pdf",
                    content=self.pdf.read_bytes(),
                    headers=[
                        (b"content-type", b"application/pdf"),
                        (b"x-csrf-token", value),
                    ],
                )
                self.assertEqual(response.status_code, 403, response.text)
            for header, value in (
                ("Origin", BASE_URL),
                ("X-CSRF-Token", client.headers["X-CSRF-Token"]),
                ("Host", "127.0.0.1:18765"),
            ):
                response = client.get(
                    "/api/v1/projects", headers=[(header, value), (header, value)]
                )
                self.assertEqual(response.status_code, 403, response.text)

    def test_state_source_and_symlink_rejected_before_database_creation(self):
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / ".git").write_text("gitdir: external-test-fixture")
        state = checkout / "state"
        with self.assertRaises(WebError) as error:
            create_app(state)
        self.assertEqual(error.exception.code, "state_in_source")
        self.assertFalse(state.exists())
        package = (
            Path(create_app.__code__.co_filename).parent
            / "static"
            / "runtime-state-must-not-exist"
        )
        with self.assertRaises(WebError):
            create_app(package)
        self.assertFalse(package.exists())
        link = self.root / "linked-state"
        real = self.root / "real-state"
        real.mkdir(mode=0o700)
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(WebError):
            create_app(link)
        self.assertEqual(list(real.iterdir()), [])

    def test_real_uvicorn_http_session_upload_and_export_on_ephemeral_port(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        app = self.app(port=port)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            proxy_headers=False,
            log_level="error",
            lifespan="on",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while (
                not server.started and thread.is_alive() and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            self.assertTrue(server.started)
            origin = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=origin, timeout=5, trust_env=False) as client:
                self.assertEqual(client.get("/api/v1/projects").status_code, 401)
                csrf = client.get("/api/v1/session").json()["csrf_token"]
                client.headers.update({"Origin": origin, "X-CSRF-Token": csrf})
                project = self.upload(client)
                prefix = f"/api/v1/projects/{project['id']}"
                self.assertEqual(client.get(prefix + "/pages/1/image").status_code, 200)
                response = client.post(
                    prefix + "/export", json={"format": "json", "compound_ids": []}
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["review_only"])
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
        self.assertFalse(thread.is_alive())


class SlowBodyTests(WebFixture, unittest.IsolatedAsyncioTestCase):
    async def _slow_upload(self, *, total, idle, delay, chunks):
        app = self.app(body_timeout_seconds=total, body_idle_seconds=idle)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as client,
        ):
            token = (await client.get("/api/v1/session")).json()["csrf_token"]
            client.headers.update({"Origin": BASE_URL, "X-CSRF-Token": token})

            async def stream():
                yield b"%PDF-"
                for _ in range(chunks):
                    await asyncio.sleep(delay)
                    yield b"small"

            response = await client.post(
                "/api/v1/projects?filename=slow.pdf",
                content=stream(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(response.status_code, 408, response.text)
            self.assertEqual(response.json()["error"]["code"], "body_timeout")
            self.assertEqual(
                (await client.get("/api/v1/projects")).json(), {"items": []}
            )
        self.assertEqual(list((self.state / "uploads").iterdir()), [])

    async def test_idle_timeout_cleans_partial_upload(self):
        await self._slow_upload(total=0.3, idle=0.03, delay=0.08, chunks=1)

    async def test_total_timeout_cleans_trickling_upload(self):
        await self._slow_upload(total=0.08, idle=0.05, delay=0.02, chunks=10)
