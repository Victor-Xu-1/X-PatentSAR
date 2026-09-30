"""Bounded installer diagnostics: fixed codes plus a private, sanitized tail."""

from __future__ import annotations

import codecs
import errno
import re
from collections import deque
from urllib.error import HTTPError, URLError

MESSAGES = {
    "installer_failed": "The pinned installer failed; existing environments were preserved.",
    "network_error": "An official dependency/model download failed. Check network/proxy availability.",
    "tls_error": "TLS validation failed for an official download; certificate checks remain enabled.",
    "dependency_resolution": "The pinned dependency set could not be resolved for this platform.",
    "unsupported_wheel": "A required pinned wheel is unavailable for this Python/platform.",
    "hash_mismatch": "Downloaded content failed its reviewed digest; it was not activated.",
    "disk_full": "Approved storage has insufficient free space; nothing was activated.",
    "permission_denied": "The owned storage or executable is not accessible; operator files were preserved.",
    "operation_cancelled": "The operation was cancelled; no success result was published.",
    "operation_timeout": "A bounded operation stage timed out; owned children were stopped.",
    "verification_failed": "Actual module/model checks failed; the component was not activated.",
    "invalid_content": "The private plan or component content did not satisfy its safety contract.",
    "cleanup_failed": "Owned-child shutdown was not verified; retain the operation owner and inspect it.",
    "ownership_failed": "The child kernel identity could not be established; no unowned PID was signalled.",
    "output_limit": "Installer output exceeded its safety bound; owned children were stopped.",
}


class EnvironmentFailure(RuntimeError):
    def __init__(self, code: str, tail: list[str] | None = None) -> None:
        if code not in MESSAGES:
            raise ValueError("Unknown environment failure code")
        super().__init__(MESSAGES[code])
        self.code = code
        self.message = MESSAGES[code]
        self.tail = [safe for line in (tail or [])[-12:] if (safe := safe_line(line))]


def safe_line(value: str) -> str | None:
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value).strip()
    value = re.sub(r"^[×╰─▶│└├╭┬╮╯\s]+", "", value)
    if len(value) > 2048 or re.search(
        r"(?i)token|secret|password|authorization|cookie|credential|api[_-]?key|bearer",
        value,
    ):
        return None
    if not re.match(
        r"(?i)^(error:|caused by:|because |failed to |no solution |no matching |http |hash mismatch|permission denied|no space left)",
        value,
    ):
        return None
    value = re.sub(r"https?://\S+", "<official-source>", value)
    value = re.sub(r"(?<!\w)/[^\s,;\])]+", "<private-path>", value)
    value = re.sub(r"[A-Za-z]:[\\/][^\s]+", "<private-path>", value)
    return "".join(c for c in value if c.isprintable())[:500]


class DiagnosticTail:
    def __init__(self) -> None:
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending = ""
        self.dropping = False
        self.lines: deque[str] = deque(maxlen=12)

    def feed(self, data: bytes) -> None:
        parts = (self.pending + self.decoder.decode(data)).split("\n")
        for line in parts[:-1]:
            if not self.dropping and (safe := safe_line(line)):
                self.lines.append(safe)
            self.dropping = False
        self.pending = parts[-1]
        if len(self.pending) > 2048:
            self.pending = ""
            self.dropping = True

    def finish(self) -> list[str]:
        if not self.dropping and (safe := safe_line(self.pending)):
            self.lines.append(safe)
        return list(self.lines)

    def failure(self) -> EnvironmentFailure:
        tail = self.finish()
        value = " ".join(tail).lower()
        code = "installer_failed"
        for words, candidate in (
            (("no space left", "disk full"), "disk_full"),
            (("permission denied",), "permission_denied"),
            (("hash mismatch", "hash does not match"), "hash_mismatch"),
            (("certificate", "tls", "ssl"), "tls_error"),
            (("no solution", "unsatisfiable"), "dependency_resolution"),
            (("no matching", "compatible wheel", "no wheel"), "unsupported_wheel"),
            (
                ("http", "download", "connection", "resolve host", "dns", "timed out"),
                "network_error",
            ),
        ):
            if any(word in value for word in words):
                code = candidate
                break
        return EnvironmentFailure(code, tail)


def failure_from_exception(error: Exception) -> EnvironmentFailure:
    if isinstance(error, EnvironmentFailure):
        return error
    if isinstance(error, InterruptedError):
        return EnvironmentFailure("operation_cancelled")
    if isinstance(error, TimeoutError):
        return EnvironmentFailure("operation_timeout")
    if isinstance(error, HTTPError):
        return EnvironmentFailure(
            "network_error", [f"HTTP status={error.code} source=official"]
        )
    if isinstance(error, URLError):
        return EnvironmentFailure("network_error")
    if isinstance(error, OSError):
        if error.errno == errno.ENOSPC:
            return EnvironmentFailure("disk_full")
        if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            return EnvironmentFailure("permission_denied")
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return EnvironmentFailure("invalid_content")
    return EnvironmentFailure("verification_failed")
