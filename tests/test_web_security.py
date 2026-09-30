from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from test_web_support import BASE_URL, WebFixture

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.security import COOKIE_NAME


class SecurityTests(WebFixture, unittest.TestCase):
    def test_host_origin_bootstrap_and_csrf(self):
        with TestClient(self.app(), base_url=BASE_URL) as client:
            self.assertEqual(client.get("/api/v1/health").status_code, 200)
            self.assertEqual(client.get("/api/v1/projects").status_code, 401)
            self.assertEqual(
                client.get(
                    "/api/v1/health", headers={"Host": "attacker.invalid:18765"}
                ).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    "/api/v1/session", headers={"Origin": "https://attacker.invalid"}
                ).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    "/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"}
                ).status_code,
                403,
            )
            response = client.get("/api/v1/session")
            cookie = response.headers["set-cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=strict", cookie)
            self.assertEqual(client.get("/api/v1/projects").json(), {"items": []})
            token = response.json()["csrf_token"]
            data = self.pdf.read_bytes()
            headers = {"Content-Type": "application/pdf", "X-CSRF-Token": token}
            self.assertEqual(
                client.post(
                    "/api/v1/projects?filename=a.pdf", content=data, headers=headers
                ).status_code,
                403,
            )
            headers["Origin"] = BASE_URL
            headers["X-CSRF-Token"] = "wrong"
            self.assertEqual(
                client.post(
                    "/api/v1/projects?filename=a.pdf", content=data, headers=headers
                ).status_code,
                403,
            )
            headers["X-CSRF-Token"] = token
            self.assertEqual(
                client.post(
                    "/api/v1/projects?filename=a.pdf", content=data, headers=headers
                ).status_code,
                201,
            )

    def test_configured_port_and_loopback_aliases(self):
        with TestClient(self.app(), base_url="http://localhost:18765") as client:
            self.assertEqual(
                client.get(
                    "/api/v1/session", headers={"Origin": "http://localhost:18765"}
                ).status_code,
                200,
            )
            self.assertEqual(
                client.get("/api/v1/session", headers={"Origin": BASE_URL}).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    "/api/v1/health", headers={"Host": "127.0.0.1:8765"}
                ).status_code,
                403,
            )
        with self.assertRaises(WebError):
            self.app(host="0.0.0.0")

    def test_session_persists_and_tokens_are_bound(self):
        with self.client() as first:
            cookie = first.cookies.get(COOKIE_NAME)
            csrf = first.headers["X-CSRF-Token"]
        with self.client() as second:
            different = second.headers["X-CSRF-Token"]
            self.assertNotEqual(csrf, different)
            second.cookies.set(COOKIE_NAME, cookie, domain="127.0.0.1", path="/")
            self.assertEqual(second.get("/api/v1/projects").status_code, 200)
            response = second.post(
                "/api/v1/projects?filename=a.pdf",
                content=self.pdf.read_bytes(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(response.status_code, 403)
            second.headers["X-CSRF-Token"] = csrf
            self.upload(second)
        self.assertNotIn(
            cookie.encode(), (self.state / "workspace.sqlite3").read_bytes()
        )
        self.assertEqual(
            (self.state / "workspace.sqlite3").stat().st_mode & 0o777, 0o600
        )

    def test_uniform_errors_and_no_static_evidence(self):
        frontend = self.root / "built"
        frontend.mkdir()
        (frontend / "index.html").write_text(
            "<!doctype html><title>Controlled built SPA fixture</title>"
        )
        (frontend / ".bundle.json").write_text('{"secret":"not-public"}')
        with self.client(frontend_dir=frontend) as client:
            self.assertIn(
                "Controlled built SPA fixture", client.get("/projects/example").text
            )
            for path in (
                "/api/v1/not-real",
                "/.bundle.json",
                "/assets/absent.js",
                "/assets/..%2f.bundle.json",
            ):
                response = client.get(path)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(set(response.json()), {"error"})
            response = client.post(
                "/api/v1/projects/no/jobs",
                json={"advisory": False, "path": "/etc/passwd"},
            )
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("/etc/passwd", response.text)
            runtime = client.get("/api/v1/runtime").json()
            self.assertEqual(
                set(runtime["interpreters"][0]), {"role", "configured", "available"}
            )

    def test_api_only_and_missing_ui_are_explicit(self):
        with self.client() as client:
            self.assertTrue(client.get("/api/v1/health").json()["ready"])
            self.assertEqual(client.get("/").json()["error"]["code"], "ui_not_built")
        with self.client(frontend_dir=self.root / "not-built") as client:
            self.assertFalse(client.get("/api/v1/health").json()["ready"])
            self.assertEqual(client.get("/").status_code, 503)

    def test_second_server_does_not_recover_live_owner(self):
        with self.client() as first:
            with (
                self.assertRaises(WebError) as error,
                TestClient(self.app(), base_url=BASE_URL),
            ):
                self.fail("Second server must not acquire workspace")
            self.assertEqual(error.exception.code, "workspace_busy")
            self.assertEqual(first.get("/api/v1/projects").status_code, 200)
