"""Fixed official-source assets, bounded downloads and member-level SHA checks."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from patent_sar_extractor.workers.environment_files import file_sha256

from .environment_errors import EnvironmentFailure


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        parsed = urlsplit(newurl)
        if (
            parsed.username
            or parsed.password
            or parsed.scheme != "https"
            or parsed.hostname
            not in {
                "files.pythonhosted.org",
                "zenodo.org",
            }
        ):
            raise ValueError("Asset redirect left its official source allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(
    url: str,
    cache_root: Path,
    *,
    size: int,
    sha256: str | None = None,
    md5: str | None = None,
    cancel: threading.Event,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    # Callers only pass catalog constants, never plan/request URLs.
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"files.pythonhosted.org", "zenodo.org"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Source is outside the fixed official asset allowlist")
    key = sha256 or md5
    if not key:
        raise ValueError("A pinned asset digest is required")
    target = cache_root / (key + ".asset")
    if target.exists():
        _verify(target, size, sha256, md5)
        if progress:
            progress(size, size)
        return target
    temporary = cache_root / (key + f".{os.getpid()}.partial")
    proxies = {}
    for protocol in ("http", "https"):
        value = os.environ.get(protocol.upper() + "_PROXY")
        if value:
            proxy = urlsplit(value)
            if (
                not proxy.username
                and not proxy.password
                and proxy.hostname in {"127.0.0.1", "localhost", "::1"}
            ):
                proxies[protocol] = value
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies), OfficialRedirect()
    )
    deadline = time.monotonic() + 1800
    owned = False
    reported = 0.0
    try:
        if cancel.is_set():
            raise InterruptedError("Asset download cancelled")
        with opener.open(url, timeout=30) as response:
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            owned = True
            with os.fdopen(fd, "wb") as output:
                received = 0
                # read1 yields available network bytes instead of waiting for a
                # whole MiB during a slow stream; deadlines/progress stay live.
                while data := response.read1(64 * 1024):
                    if cancel.is_set():
                        raise InterruptedError("Asset download cancelled")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Asset download exceeded its lifetime")
                    received += len(data)
                    if received > size:
                        raise ValueError("Official asset exceeded declared size")
                    output.write(data)
                    stamp = time.monotonic()
                    if progress and stamp - reported >= 1:
                        progress(received, size)
                        reported = stamp
                output.flush()
                os.fsync(output.fileno())
        _verify(temporary, size, sha256, md5)
        # Never overwrite existing unknown cache content, including a racing writer.
        os.link(temporary, target, follow_symlinks=False)
        if progress:
            progress(size, size)
    finally:
        if owned:
            temporary.unlink(missing_ok=True)
    return target


def _verify(path: Path, size: int, sha256: str | None, md5: str | None) -> None:
    if path.is_symlink() or path.stat().st_size != size:
        raise ValueError("Asset size/type differs from the pinned source")
    if sha256 and file_sha256(path) != sha256:
        raise EnvironmentFailure("hash_mismatch")
    if md5:
        digest = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as stream:
            while data := stream.read(1024 * 1024):
                digest.update(data)
        if digest.hexdigest() != md5:
            raise EnvironmentFailure("hash_mismatch")


def extract_model_group(
    archive: Path, root: Path, group: dict[str, Any], cancel: threading.Event
) -> None:
    """Extract only fixed expected model members, never zip.extractall()."""
    with zipfile.ZipFile(archive) as source:
        for item in group["files"]:
            if cancel.is_set():
                raise InterruptedError("Model extraction cancelled")
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Untrusted model member")
            info = source.getinfo(relative.as_posix())
            if info.file_size != item["size"] or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Archive model member has wrong size/type")
            target = root / "DECIMER-V2" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as stream, target.open("xb") as output:
                while data := stream.read(1024 * 1024):
                    if cancel.is_set():
                        raise InterruptedError("Model extraction cancelled")
                    output.write(data)
            if file_sha256(target) != item["sha256"]:
                raise EnvironmentFailure("hash_mismatch")
        marker = root / "DECIMER-V2" / group["directory"] / ".model_url"
        with marker.open("x", encoding="utf-8") as output:
            output.write(group["url"])
