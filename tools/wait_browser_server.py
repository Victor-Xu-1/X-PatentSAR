"""Bounded HTTP startup gate for an already-started owned loopback process.

This never starts/stops a service or prepares scientific environments. A valid
health contract with the exact installed version proves HTTP availability;
model readiness remains a separate product/browser acceptance condition.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from importlib.metadata import version
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

LIMIT = 16384


class ServerNotReady(RuntimeError):
    """Refused, exited, mismatched or deadline-bound browser service."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise ServerNotReady("Cannot verify the owned server process") from exc
    return True


def validate_health(body: bytes, expected_version: str) -> None:
    if len(body) > LIMIT:
        raise ServerNotReady("Browser health response exceeds its byte budget")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise ServerNotReady("Malformed browser health response") from exc
    if not isinstance(value, dict):
        raise ServerNotReady("Browser health identity mismatch")
    product, schema = value.get("product"), value.get("schema")
    if (
        not isinstance(product, dict)
        or product.get("name") != "X-PatentSAR"
        or product.get("version") != expected_version
        or not isinstance(schema, dict)
        or schema.get("name") != "patentsar.web-api"
        or type(schema.get("version")) is not int
        or schema.get("version") != 1
        or type(value.get("ready")) is not bool
    ):
        raise ServerNotReady("Browser health identity mismatch")


def wait_for_server(
    pid: int, port: int, expected_version: str, *, timeout: float = 30
) -> None:
    if (
        type(pid) is not int
        or pid <= 0
        or type(port) is not int
        or not 1 <= port <= 65535
        or not math.isfinite(timeout)
        or not 0 < timeout <= 60
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", expected_version)
    ):
        raise ValueError("Require a positive owned PID, loopback port and <=60s bound")
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(f"http://127.0.0.1:{port}/api/v1/health")
    while True:
        if not process_alive(pid):
            raise ServerNotReady("Owned browser server exited before readiness")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ServerNotReady("Browser server startup deadline exceeded")
        try:
            with opener.open(request, timeout=min(1, remaining)) as response:
                body = response.read(LIMIT + 1)
            validate_health(body, expected_version)
            if not process_alive(pid):
                raise ServerNotReady("Owned browser server exited during readiness")
            if time.monotonic() > deadline:
                raise ServerNotReady("Browser server startup deadline exceeded")
            return
        except HTTPError as exc:
            if not 500 <= exc.code <= 599:
                raise ServerNotReady("Browser health HTTP identity mismatch") from exc
        except (URLError, OSError, TimeoutError):
            pass  # Only startup transport failures retry, within the same deadline.
        time.sleep(max(0, min(0.1, deadline - time.monotonic())))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        installed = version("x-patentsar")
        wait_for_server(args.pid, args.port, installed, timeout=args.timeout)
    except (ServerNotReady, ValueError) as exc:
        parser.exit(2, f"Browser startup failed: {exc}\n")
    print(f"Owned browser server serving X-PatentSAR {installed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
