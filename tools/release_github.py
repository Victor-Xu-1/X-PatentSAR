"""Bounded, same-origin GitHub REST transport for trusted release automation."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Release API redirects are refused")


class GitHub:
    def __init__(self, repository: str, token: str):
        if (
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None
            or not token
        ):
            raise ValueError("An explicit repository and workflow token are required")
        self.base = "https://api.github.com/repos/" + repository
        self.repository = repository
        self.token = token
        # Ignore unrelated proxy credentials; retain normal HTTPS certificate validation.
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirects()
        )

    def call(self, method: str, path: str, value: dict | None = None):
        if not path.startswith("/") or any(part in path for part in ("..", ":", "#")):
            raise ValueError("Release API paths must remain repository-local")
        data = None if value is None else json.dumps(value).encode()
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "X-PatentSAR-release-automation",
            },
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            raise ValueError(
                f"GitHub release API returned HTTP {error.code}; no retry was performed"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ValueError(
                "GitHub release API outcome is unavailable; inspect current state before retry"
            ) from None
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("GitHub release response exceeds the bounded limit")
        return json.loads(raw) if raw else None
