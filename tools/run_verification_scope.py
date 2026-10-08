"""Validate the checked-in CI scope and run only one explicitly selected phase."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import verification_scope as policy

ROOT = Path(__file__).resolve().parents[1]
GIT_DIFF = ("--no-ext-diff", "--no-textconv")
PHASES = ("validate", "python", "frontend", "browser")
Command = tuple[Path, list[str]]


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=root,
        encoding="utf-8",
        stderr=subprocess.PIPE,
        timeout=30,
    )


def git_changes(root: Path, base: str) -> dict[str, str]:
    policy.require_sha(base)
    try:
        _git(root, "cat-file", "-e", base + "^{commit}")
        _git(root, "merge-base", "--is-ancestor", base, "HEAD")
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            "Expected Git base is unavailable or not an ancestor of HEAD; "
            "checkout must include that base (history is never widened automatically)"
        ) from exc
    flags = [*GIT_DIFF, "--raw", "--no-renames", "-z"]
    raw = _git(root, "diff", *flags, base, "HEAD", "--")
    entries = raw.removesuffix("\0").split("\0") if raw else []
    if (raw and not raw.endswith("\0")) or len(entries) % 2:
        raise ValueError("Malformed NUL-delimited Git change inventory")
    changes = {}
    for metadata, name in zip(entries[::2], entries[1::2], strict=True):
        fields = metadata.removeprefix(":").split()
        if not metadata.startswith(":") or len(fields) != 5:
            raise ValueError("Malformed raw Git change metadata")
        if any(mode not in {"000000", "100644", "100755"} for mode in fields[:2]):
            raise ValueError("Git scope contains a symbolic link or non-regular file")
        if name in changes:
            raise ValueError("Duplicate path in Git change inventory")
        changes[name] = fields[-1]
    return changes


def load_scope(root: Path, manifest: str, base: str) -> policy.Scope:
    path = policy.safe_file(root, manifest)
    try:
        _git(root, "cat-file", "-e", "HEAD:" + manifest)
        _git(root, "diff", "--quiet", *GIT_DIFF, "HEAD", "--", manifest)
    except subprocess.CalledProcessError as exc:
        raise ValueError("Scope must be checked in at HEAD and unmodified") from exc
    with path.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Verification scope exceeds the 64 KiB limit")
    plan = json.loads(raw.decode("utf-8"), object_pairs_hook=policy.unique_object)
    return policy.validate_scope(
        plan, root=root, expected_base=base, changes=git_changes(root, base)
    )


def phase_commands(scope: policy.Scope, phase: str, root: Path) -> list[Command]:
    """Build explicit argv; empty test selections never start test tools."""
    commands: list[Command] = []
    python = [sys.executable, "-m"]
    frontend = root / "frontend"
    binaries = frontend / "node_modules/.bin"
    if phase == "frontend":
        paths = [
            str(root / name)
            for name in scope.changed_paths
            if re.fullmatch(r"frontend/.+\.(?:[cm]?[jt]s|[jt]sx|css)", name)
            and (root / name).is_file()
        ]
        for tool, option in (("prettier", "--check"), ("oxlint", "--deny-warnings")):
            selected = (
                paths
                if tool == "prettier"
                else [p for p in paths if not p.endswith(".css")]
            )
            if selected:
                commands.append((frontend, [str(binaries / tool), option, *selected]))
    if phase == "python":
        if scope.changed_python:
            for flags in (["check"], ["format", "--check"]):
                command = [*python, "ruff", *flags, *scope.changed_python]
                commands.append((root, command))
        if scope.python_modules:
            command = [*python, "unittest", "-v", *scope.python_modules]
            commands.append((root, command))
    elif phase in {"frontend", "browser"}:
        files = scope.frontend_tests if phase == "frontend" else scope.browser_tests
        if files:
            tool = "vitest" if phase == "frontend" else "playwright"
            arguments = [str(root / name) for name in files]
            if phase == "browser":
                arguments = ["^" + re.escape(name) + "$" for name in arguments]
            executable = str(binaries / tool)
            action = "run" if phase == "frontend" else "test"
            workers = "--maxWorkers=1" if phase == "frontend" else "--workers=1"
            commands.append((frontend, [executable, action, workers, *arguments]))
    elif phase != "validate":
        raise ValueError(f"Unknown verification phase: {phase}")
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=".github/verification_scope.json")
    parser.add_argument("--base", default=os.environ.get("PATENTSAR_CI_BASE"))
    parser.add_argument("--phase", choices=PHASES, default="validate")
    args = parser.parse_args(argv)
    try:
        if not args.base:
            raise ValueError("Set PATENTSAR_CI_BASE or --base; no implicit base")
        base = policy.require_sha(args.base)
        scope = load_scope(ROOT, args.manifest, base)
        if args.phase == "validate":
            print(f"python_count={len(scope.python_modules)}")
            print(f"frontend_count={len(scope.frontend_tests)}")
            print(f"browser_count={len(scope.browser_tests)}")
        environment = dict(os.environ)
        if args.phase == "python":
            # Owned analysis children use private working directories. Absolute
            # explicit test paths keep their imports on the same source revision.
            environment["PYTHONPATH"] = os.pathsep.join(
                str(ROOT / name) for name in ("src", "tests")
            )
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for cwd, command in phase_commands(scope, args.phase, ROOT):
            subprocess.run(command, cwd=cwd, env=environment, check=True, timeout=1200)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Verification scope failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
