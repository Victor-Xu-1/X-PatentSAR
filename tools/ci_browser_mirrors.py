"""Repair only the ephemeral GitHub Ubuntu mirror list, keeping signed apt checks."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

MIRROR = Path("/etc/apt/apt-mirrors.txt")
HOSTS = {"azure.archive.ubuntu.com", "archive.ubuntu.com", "security.ubuntu.com"}


def official_https_mirrors(content: str) -> str:
    if len(content.encode()) > 16384:
        raise ValueError("CI mirror list exceeds its bound")
    output = []
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            output.append(line)
            continue
        fields = line.split()
        url = urlsplit(fields[0])
        if (
            url.scheme not in {"http", "https"}
            or url.hostname not in HOSTS
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"/ubuntu", "/ubuntu/"}
        ):
            raise ValueError("CI mirror is outside the reviewed Ubuntu source list")
        host = (
            "archive.ubuntu.com"
            if url.hostname == "azure.archive.ubuntu.com"
            else url.hostname
        )
        # apt's mirror protocol uses TAB for metadata. Spaces become part of
        # the URL and produce a misleading repository/signature failure.
        output.append("\t".join([f"https://{host}/ubuntu/", *fields[1:]]))
    if not any(line.startswith("https://") for line in output):
        raise ValueError("CI mirror list has no official repository")
    return "\n".join(output) + "\n"


def prepare() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.getuid() != 0:
        raise ValueError("Mirror preparation is scoped to the ephemeral GitHub runner")
    if not MIRROR.exists():
        return  # Standard official apt sources need no mirror-list adjustment.
    info = MIRROR.lstat()
    if not stat.S_ISREG(info.st_mode) or MIRROR.is_symlink():
        raise ValueError("CI mirror list must be a regular file")
    original = MIRROR.read_text(encoding="utf-8")
    changed = official_https_mirrors(original)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".patentsar-ci-mirrors-", dir=MIRROR.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(changed)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, stat.S_IMODE(info.st_mode))
        if MIRROR.read_text(encoding="utf-8") != original:
            raise ValueError("CI mirror list changed during preparation")
        os.replace(temporary, MIRROR)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    prepare()
