"""Real loopback transport oracles; no provider/DNS/cloud endpoint is used."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from patent_sar_extractor.integrations.llm import client
from patent_sar_extractor.integrations.llm import http_transport as transport

TEST_KEY = "controlled-transport-test-only-key"


class LocalServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, mode):
        self.mode = mode
        self.stopping = threading.Event()
        self.received = threading.Event()
        self.requests = []
        super().__init__(("127.0.0.1", 0), LocalHandler)


class LocalHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        server = self.server
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        server.requests.append((self.path, self.headers.get("Authorization"), body))
        server.received.set()
        response = json.dumps(
            {
                "choices": [
                    {"message": {"content": "bounded-ok"}, "finish_reason": "stop"}
                ],
                "padding": "x" * 2400,
            }
        ).encode()
        if server.mode == "oversized":
            response = b"x" * 100000
        if server.mode == "retry" and len(server.requests) == 1:
            self.wfile.write(
                b"HTTP/1.1 503 Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            self.wfile.flush()
            return
        headers = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(response)).encode()
            + b"\r\nConnection: close\r\n\r\n"
        )
        try:
            if server.mode == "slow_headers":
                self.trickle(headers)
                self.wfile.write(response)
            elif server.mode == "slow_body":
                self.wfile.write(headers)
                self.wfile.flush()
                self.trickle(response)
            else:
                self.wfile.write(headers + response)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # The deadline oracle deliberately closes this owned connection.

    def trickle(self, data):
        started = time.monotonic()
        for index, value in enumerate(data):
            if self.server.stopping.is_set():
                return
            if time.monotonic() - started >= 2.3:
                self.wfile.write(data[index:])
                return  # Finite oracle, including before the deadline repair.
            self.wfile.write(bytes([value]))
            self.wfile.flush()
            if self.server.stopping.wait(0.03):
                return


class DeadlineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.object(
                client.requests,
                "post",
                side_effect=AssertionError(
                    "only the controlled child may open an HTTP socket"
                ),
            )
        )
        self.enterContext(
            patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "NETRC": os.devnull})
        )

    def serve(self, mode):
        server = LocalServer(mode)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}
        )
        thread.start()

        def stop():
            server.stopping.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive(), "owned local server must stop")

        self.addCleanup(stop)
        return server

    def call(self, server, **kwargs):
        options = {
            "timeout": 1,
            "max_retries": 0,
            "max_response_chars": 8192,
            "cache": False,
        }
        options.update(kwargs)

        # Test-only adapter routes the checked public API request to an owned
        # HTTP emulator. It performs no inference and adds no production opt-out.
        def local_wire(url, **wire):
            self.assertEqual(url, "https://api.example.org/v1/chat/completions")
            self.assertTrue(wire.pop("require_public"))
            return transport.bounded_post(
                f"http://127.0.0.1:{server.server_port}/v1/chat/completions", **wire
            )

        with patch.object(client, "bounded_post", side_effect=local_wire):
            return client.llm_chat(
                [{"role": "user", "content": "controlled local transport observation"}],
                config={
                    "endpoint": "https://api.example.org/v1",
                    "model": "controlled",
                    "api_key": TEST_KEY,
                    "cache_path": "",
                },
                **options,
            )

    def children(self):
        owned = []
        original = transport.subprocess.Popen

        def start(*args, **kwargs):
            process = original(*args, **kwargs)
            self.assertEqual(os.getpgid(process.pid), process.pid)
            owned.append((process, args, kwargs))
            return process

        mocked = self.enterContext(
            patch.object(transport.subprocess, "Popen", side_effect=start)
        )
        return owned, mocked

    def assert_reaped(self, owned):
        self.assertTrue(owned)
        for process, _, _ in owned:
            self.assertIsNotNone(process.returncode)
            self.assertFalse(
                Path(f"/proc/{process.pid}").exists(), "carrier must reap its own child"
            )
            for stream in (process.stdin, process.stdout, process.stderr):
                self.assertTrue(stream.closed)

    def assert_deadline(self, mode):
        server = self.serve(mode)
        owned, _ = self.children()
        started = time.monotonic()
        self.assertEqual(self.call(server), "")
        elapsed = time.monotonic() - started
        self.assertTrue(server.received.is_set())
        self.assertLess(
            elapsed,
            1.7,
            "absolute 1s deadline plus bounded cleanup, not socket-idle timeout",
        )
        self.assertEqual(len(server.requests), 1)
        self.assert_reaped(owned)

    def test_slow_headers_obey_absolute_deadline(self):
        self.assert_deadline("slow_headers")

    def test_slow_body_obeys_absolute_deadline(self):
        self.assert_deadline("slow_body")

    def test_fast_loopback_response_is_preserved(self):
        server = self.serve("fast")
        owned, _ = self.children()
        self.assertEqual(self.call(server), "bounded-ok")
        self.assertEqual(server.requests[0][0], "/v1/chat/completions")
        self.assertEqual(server.requests[0][1], f"Bearer {TEST_KEY}")
        process, args, kwargs = owned[0]
        self.assertNotIn(TEST_KEY, repr(args))
        self.assertEqual(args[0][1:3], ["-I", "-B"])
        self.assertEqual(kwargs["stdin"], subprocess.PIPE)
        self.assertTrue(kwargs["start_new_session"])
        self.assertNotIn("LLM_API_KEY", kwargs["env"])
        self.assertNotIn("VLM_API_KEY", kwargs["env"])
        self.assertEqual(process.returncode, 0)
        self.assert_reaped(owned)

    def test_body_limit_is_enforced_in_real_worker_without_retry(self):
        server = self.serve("oversized")
        owned, _ = self.children()
        self.assertEqual(self.call(server, max_response_chars=16, max_retries=1), "")
        self.assertEqual(len(server.requests), 1)
        self.assertEqual(len(owned), 1)
        self.assert_reaped(owned)

    def test_cancel_terminates_only_owned_child_and_does_not_retry(self):
        server = self.serve("slow_body")
        owned, _ = self.children()
        cancel = threading.Event()

        def request_cancel():
            server.received.wait(timeout=1)
            cancel.set()

        requester = threading.Thread(target=request_cancel)
        requester.start()
        self.addCleanup(lambda: requester.join(timeout=1))
        started = time.monotonic()
        self.assertEqual(self.call(server, timeout=3, max_retries=1, cancel=cancel), "")
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(len(owned), 1)
        self.assertEqual(len(server.requests), 1)
        self.assert_reaped(owned)

    def test_retry_counts_actual_requests_and_shares_one_absolute_deadline(self):
        server = self.serve("retry")
        owned, _ = self.children()
        attempts = []
        self.assertEqual(
            self.call(
                server,
                timeout=2,
                max_retries=1,
                before_request=lambda: attempts.append(1) or True,
            ),
            "bounded-ok",
        )
        self.assertEqual((len(attempts), len(server.requests), len(owned)), (2, 2, 2))
        self.assert_reaped(owned)

    def test_exhausted_budget_prevents_spawn_not_just_network(self):
        with patch.object(transport.subprocess, "Popen") as spawned:
            self.assertEqual(
                client.llm_chat(
                    [],
                    config={
                        "endpoint": "https://unit.invalid",
                        "model": "controlled",
                        "api_key": TEST_KEY,
                    },
                    timeout=1,
                    max_retries=1,
                    max_response_chars=32,
                    cache=False,
                    before_request=lambda: False,
                ),
                "",
            )
        spawned.assert_not_called()

    def test_cancellation_before_start_prevents_spawn_and_budget_consumption(self):
        cancel = threading.Event()
        cancel.set()
        budget = Mock(return_value=True)
        with patch.object(transport.subprocess, "Popen") as spawned:
            self.assertEqual(
                client.llm_chat(
                    [],
                    config={
                        "endpoint": "https://unit.invalid",
                        "model": "controlled",
                        "api_key": TEST_KEY,
                    },
                    timeout=1,
                    max_retries=1,
                    max_response_chars=32,
                    cache=False,
                    before_request=budget,
                    cancel=cancel,
                ),
                "",
            )
        spawned.assert_not_called()
        budget.assert_not_called()

    def test_parent_death_cannot_leave_live_transport_worker(self):
        server = self.serve("slow_body")
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "owned-worker-pid"
            caller = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import sys; from test_llm_http_transport import orphan_call; orphan_call(*sys.argv[1:])",
                    f"http://127.0.0.1:{server.server_port}/v1",
                    str(marker),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            def stop_caller():
                if caller.poll() is None:
                    caller.kill()
                caller.communicate(timeout=1)
                caller.stdout.close()
                caller.stderr.close()

            self.addCleanup(stop_caller)
            self.assertTrue(server.received.wait(timeout=3))
            pid = int(marker.read_text())
            caller.kill()  # Only the caller created by this test; never a service.
            caller.communicate(timeout=1)
            started = time.monotonic()
            while process_live(pid) and time.monotonic() - started < 1:
                time.sleep(0.02)
            self.assertFalse(
                process_live(pid),
                "kernel parent-death signal must terminate its own worker",
            )

    def test_production_public_guard_rejects_local_emulator_before_request(self):
        server = self.serve("fast")
        with self.assertRaises(ValueError):
            transport.bounded_post(
                f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                headers={},
                json={},
                timeout=1,
                deadline=time.monotonic() + 1,
                max_body_bytes=8192,
                require_public=True,
            )
        self.assertEqual(server.requests, [])


def process_live(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def orphan_call(endpoint, marker):
    """Controlled parent-death probe, with no credential in this caller's argv."""
    original = transport.subprocess.Popen

    def record(*args, **kwargs):
        process = original(*args, **kwargs)
        Path(marker).write_text(str(process.pid))
        return process

    with patch.object(transport.subprocess, "Popen", side_effect=record):
        transport.bounded_post(
            endpoint + "/chat/completions",
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            json={},
            timeout=5,
            deadline=time.monotonic() + 5,
            max_body_bytes=65536,
        )


class CarrierContractTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch.object(
                client.requests,
                "post",
                side_effect=AssertionError(
                    "unit test may not make a direct network/DNS call"
                ),
            )
        )

    def test_carrier_failure_has_no_fallback_or_retry(self):
        with (
            patch.object(
                client,
                "bounded_post",
                side_effect=transport.HttpCarrierError("do not log " + TEST_KEY),
            ) as posted,
            self.assertLogs(client.logger, level="WARNING") as logs,
        ):
            self.assertEqual(
                client.llm_chat(
                    [],
                    config={
                        "endpoint": "https://unit.invalid",
                        "model": "controlled",
                        "api_key": TEST_KEY,
                    },
                    timeout=1,
                    max_retries=1,
                    max_response_chars=32,
                    cache=False,
                ),
                "",
            )
        self.assertEqual(posted.call_count, 1)
        self.assertNotIn(TEST_KEY, " ".join(logs.output))

    def test_expired_deadline_never_spawns_worker(self):
        with (
            patch.object(transport.subprocess, "Popen") as spawned,
            self.assertRaises(requests.Timeout),
        ):
            transport.bounded_post(
                "https://unit.invalid",
                headers={},
                json={},
                timeout=1,
                deadline=time.monotonic() - 1,
                max_body_bytes=32,
            )
        spawned.assert_not_called()

    def test_cleanup_failure_is_explicit_and_targets_only_owned_handle(self):
        process = Mock()
        process.communicate.return_value = (b"", b"")
        process.returncode = 1
        process.poll.return_value = None
        process.kill.side_effect = OSError("protected-key-must-not-escape")
        with (
            patch.object(transport.subprocess, "Popen", return_value=process),
            self.assertRaises(transport.HttpCarrierError),
        ):
            transport.bounded_post(
                "https://unit.invalid",
                headers={},
                json={},
                timeout=1,
                deadline=time.monotonic() + 1,
                max_body_bytes=32,
            )
        process.kill.assert_called_once()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close.assert_called_once()

    def test_invalid_worker_protocol_is_not_a_network_fallback(self):
        for packet in (
            b"not-json",
            b'{"kind":"ok","body":"","extra":true}',
            b'{"kind":"worker_error","body":""}',
        ):
            with (
                self.subTest(packet=packet),
                self.assertRaises(transport.HttpCarrierError),
            ):
                transport._transport_result(packet, 32)

    def test_stored_key_alone_cannot_enable_legacy_or_bounded_http(self):
        with (
            patch.object(
                client.requests,
                "post",
            ) as posted,
            patch.object(client, "bounded_post") as carrier,
            patch.object(client.time, "sleep") as sleep,
            patch.dict(
                os.environ,
                {
                    "LLM_API_KEY": TEST_KEY,
                    "LLM_ENDPOINT": "https://unit.invalid",
                    "LLM_MODEL": "controlled",
                    "PATENTSAR_LLM_RESOLUTION_MODE": "off",
                    "PATENTSAR_LLM_RESOLUTION_DATA_CONSENT": "false",
                },
            ),
        ):
            self.assertEqual(client.llm_chat([], cache=False), "")
        posted.assert_not_called()
        sleep.assert_not_called()
        carrier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
