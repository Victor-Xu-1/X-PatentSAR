"""Strict, read-only validation of an explicit, bounded CI verification plan."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TESTS = {
    "python_modules": (
        r"tests\.test_[A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}",
        "tests/test_*.py",
    ),
    "frontend_tests": (r"frontend/tests/.+\.test\.tsx?", "frontend/tests/**/*"),
    "browser_tests": (
        r"frontend/e2e/[A-Za-z0-9_./-]+\.spec\.(?:[cm]?[jt]s|[jt]sx)",
        "frontend/e2e/**/*.spec.*",
    ),
}
FIELDS = {"schema_version", "base_sha", "changed_paths", *TESTS}


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Duplicate JSON field in verification scope")
    return value


@dataclass(frozen=True)
class Scope:
    base_sha: str
    changed_paths: tuple[str, ...]
    python_modules: tuple[str, ...]
    frontend_tests: tuple[str, ...]
    browser_tests: tuple[str, ...]
    changed_python: tuple[str, ...]


def require_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Base must be an explicit lowercase 40-character Git SHA")
    return value


def safe_file(root: Path, name: str, *, deleted: bool = False) -> Path:
    parts = name.split("/")
    if (
        not 1 <= len(name) <= 240
        or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name)
        or any(part in {".", ".."} or part.startswith("-") for part in parts)
    ):
        raise ValueError(f"Unsafe repository path: {name!r}")
    path = root
    for part in ("", *parts):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Symbolic link in repository path: {name}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Repository path escapes root: {name}")
    if not path.is_file() and not (deleted and not path.exists()):
        raise ValueError(f"Repository file is missing or not regular: {name}")
    return path


def _strings(value: object, field: str, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{field} must be a list with at most {limit} items")
    if any(type(item) is not str or not 1 <= len(item) <= 240 for item in value):
        raise ValueError(
            f"{field} must contain nonempty strings of at most 240 characters"
        )
    if len(set(value)) != len(value):
        raise ValueError(f"Duplicate selection in {field}")
    return tuple(value)


def _validate_tests(root: Path, category: str, selections: tuple[str, ...]) -> None:
    pattern, inventory_glob = TESTS[category]
    files = set()
    for selection in selections:
        if not re.fullmatch(pattern, selection):
            raise ValueError(f"Unsafe {category} selection: {selection!r}")
        name = selection
        if category == "python_modules":
            name = "tests/" + selection.split(".")[1] + ".py"
        safe_file(root, name)
        files.add(name)
    inventory = {
        path.relative_to(root).as_posix()
        for path in root.glob(inventory_glob)
        if path.is_file()
        and (
            category == "python_modules"
            or re.fullmatch(pattern, path.relative_to(root).as_posix())
        )
    }
    if files and inventory and files >= inventory:
        raise ValueError(f"Selecting all existing test files is forbidden: {category}")
    if category == "python_modules" and any(
        left.startswith(right + ".") for left in selections for right in selections
    ):
        raise ValueError("Overlapping Python test selections are forbidden")
    if category == "frontend_tests" and any(
        name.removeprefix("frontend/").lower()
        in other.removeprefix("frontend/").lower()
        for name in files
        for other in inventory - files
    ):
        raise ValueError("Ambiguous Vitest filename filter would select unlisted files")


def validate_scope(
    plan: object, *, root: Path, expected_base: str, changes: Mapping[str, str]
) -> Scope:
    """Validate against caller-supplied Git facts; never execute or import tests."""
    require_sha(expected_base)
    if not isinstance(plan, dict) or set(plan) != FIELDS:
        raise ValueError("Scope must contain exactly the six schema_version 1 fields")
    if type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    if type(plan["base_sha"]) is not str or plan["base_sha"] != expected_base:
        raise ValueError("Scope base_sha is stale or differs from the expected base")
    changed = _strings(plan["changed_paths"], "changed_paths", 256)
    if set(changed) != set(changes):
        raise ValueError(
            f"Scope changed_paths differs from Git: missing={sorted(set(changes) - set(changed))}; "
            f"extra={sorted(set(changed) - set(changes))}"
        )
    for name in changed:
        if changes[name] not in {"A", "M", "D", "T"}:
            raise ValueError(f"Unsupported Git change status: {changes[name]}")
        safe_file(root, name, deleted=changes[name] == "D")
    selected = {field: _strings(plan[field], field, 32) for field in TESTS}
    if any(name.endswith(".py") for name in changed) and not selected["python_modules"]:
        raise ValueError("Python changes require explicit nonempty python_modules")
    for field, selections in selected.items():
        _validate_tests(root, field, selections)
    python_files = tuple(
        name for name in changed if name.endswith(".py") and changes[name] != "D"
    )
    return Scope(
        expected_base,
        changed,
        selected["python_modules"],
        selected["frontend_tests"],
        selected["browser_tests"],
        python_files,
    )
