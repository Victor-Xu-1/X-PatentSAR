"""Check or locally prepare exactly one next-mainline product release for a PR."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.version_policy import (
    AUTHORITY,
    VERSION_PATHS,
    prepare_versions,
    verify_versions,
)


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", *arguments], cwd=root, stderr=subprocess.PIPE, timeout=45
    )


def require_sha(value: str) -> str:
    if re.fullmatch(r"[a-f0-9]{40}", value) is None:
        raise ValueError("An exact 40-character base SHA is required")
    return value


def source_at(root: Path, revision: str, name: str) -> str:
    require_sha(revision)
    raw = git(root, "ls-tree", revision, "--", name).decode().strip()
    if not raw.startswith("100644 blob ") or raw.split("\t")[-1] != name:
        raise ValueError("Release metadata must be regular tracked files")
    content = git(root, "show", f"{revision}:{name}")
    if len(content) > 1024 * 1024:
        raise ValueError("Release metadata exceeds the bounded input limit")
    return content.decode("utf-8")


def local_files(root: Path) -> dict[str, str]:
    files = {}
    for name in VERSION_PATHS:
        path = root / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("Release metadata cannot follow symbolic links")
        raw = path.read_bytes()
        if len(raw) > 1024 * 1024:
            raise ValueError("Release metadata exceeds the bounded input limit")
        files[name] = raw.decode("utf-8")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=require_sha)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Prepare a local/fork PR; never commit or push",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        git(root, "merge-base", "--is-ancestor", args.base, "HEAD")
        base = source_at(root, args.base, AUTHORITY)
        files = local_files(root)
        if args.write:
            changes = prepare_versions(base, files)
            for name, content in changes.items():
                (root / name).write_text(content, encoding="utf-8")
        else:
            changes = {}
        version = verify_versions(base, local_files(root))
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"PR version check failed: {error}\n")
    print(
        f"Next merged-PR release v{version} verified; {len(changes)} metadata file(s) prepared."
    )


if __name__ == "__main__":
    main()
