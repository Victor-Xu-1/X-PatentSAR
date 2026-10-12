"""Owned loopback startup gates; no product tasks, models or external requests."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tools import wait_browser_server as gate

HEALTH = {
    "product": {"name": "X-PatentSAR", "version": "0.1.79"},
    "schema": {"name": "patentsar.web-api", "version": 1},
    "ready": False,
}


class BrowserServerTests(unittest.TestCase):
    def serve(self, replies):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                status, body = replies[min(len(requests) - 1, len(replies) - 1)]
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(close)
        return server.server_port, requests

    def wait(self, port, **options):
        return gate.wait_for_server(os.getpid(), port, "0.1.79", **options)

    def test_waits_for_transient_startup_then_checks_actual_identity(self):
        port, requests = self.serve(
            [(503, b"starting"), (200, json.dumps(HEALTH).encode())]
        )
        # Model readiness is not HTTP startup. No inference/setup is requested.
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1"}):
            self.wait(port, timeout=1)
        self.assertEqual(requests, ["/api/v1/health"] * 2)

    def test_rejects_wrong_version_schema_or_product_without_retries(self):
        for change in (
            {"product": {"name": "X-PatentSAR", "version": "0.1.78"}},
            {"product": {"name": "other", "version": "0.1.79"}},
            {"schema": {"name": "patentsar.web-api", "version": 2}},
            {"ready": "true"},
        ):
            with self.subTest(change=change):
                port, requests = self.serve(
                    [(200, json.dumps(HEALTH | change).encode())]
                )
                with self.assertRaisesRegex(gate.ServerNotReady, "identity"):
                    self.wait(port, timeout=1)
                self.assertEqual(len(requests), 1)

    def test_rejects_malformed_oversized_or_redirected_health(self):
        for reply in ((200, b"not-json"), (200, b"x" * 16385), (302, b"")):
            with self.subTest(reply=reply[0]):
                port, requests = self.serve([reply])
                with self.assertRaises(gate.ServerNotReady):
                    self.wait(port, timeout=1)
                self.assertEqual(len(requests), 1)

    def test_refuses_dead_owner_before_contacting_a_listener(self):
        port, requests = self.serve([(200, json.dumps(HEALTH).encode())])
        with (
            patch.object(gate, "process_alive", return_value=False),
            self.assertRaisesRegex(gate.ServerNotReady, "exited"),
        ):
            self.wait(port, timeout=1)
        self.assertEqual(requests, [])

    def test_refused_connection_has_a_hard_deadline(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            started = time.monotonic()
            with self.assertRaisesRegex(gate.ServerNotReady, "deadline"):
                self.wait(port, timeout=0.05)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_invalid_or_unbounded_inputs_never_contact_a_server(self):
        for pid, port, timeout in (
            (0, 18766, 1),
            (True, 18766, 1),
            (1, 0, 1),
            (1, 18766, 61),
            (1, 18766, float("nan")),
        ):
            with (
                self.subTest(values=(pid, port, timeout)),
                self.assertRaises(ValueError),
            ):
                gate.wait_for_server(pid, port, "0.1.79", timeout=timeout)


class BrowserWorkflowTests(unittest.TestCase):
    def test_ci_waits_after_starting_owned_server_before_browser_phase(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text()
        start = workflow.index("server_pid=$!")
        wait = workflow.index("tools/wait_browser_server.py --pid")
        browser = workflow.index("tools/run_verification_scope.py --phase browser")
        self.assertLess(start, wait)
        self.assertLess(wait, browser)
