"""Pure merged-PR release numbering and derived npm metadata synchronization."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass

AUTHORITY = "src/patent_sar_extractor/contracts.py"
PACKAGE = "frontend/package.json"
LOCK = "frontend/package-lock.json"
VERSION_PATHS = (AUTHORITY, PACKAGE, LOCK)
NUMBER = re.compile(r"(0|[1-9][0-9]*)\.([0-9])\.(0|[1-9][0-9]?)")
ASSIGNMENT = re.compile(r'^(__version__: Final = )"([^"\n]+)"$', re.MULTILINE)


@dataclass(frozen=True, order=True)
class ReleaseNumber:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: object) -> ReleaseNumber:
        if not isinstance(text, str) or len(text) > 32:
            raise ValueError("A canonical MAJOR.MINOR.PATCH release is required")
        match = NUMBER.fullmatch(text)
        if match is None:
            raise ValueError("Release minor must be 0–9 and patch must be 0–99")
        return cls(*(int(part) for part in match.groups()))

    def next(self) -> ReleaseNumber:
        patch = self.patch + 1
        minor = self.minor + patch // 100
        return ReleaseNumber(self.major + minor // 10, minor % 10, patch % 100)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def authority_version(source: str) -> ReleaseNumber:
    """Inspect source as data; never import or execute an incoming PR."""
    if len(source.encode()) > 1024 * 1024:
        raise ValueError("Product authority exceeds the bounded source limit")
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError) as error:
        raise ValueError("Product authority is not valid Python source") from error
    assignments = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
    ]
    if (
        len(assignments) != 1
        or not isinstance(assignments[0].value, ast.Constant)
        or len(ASSIGNMENT.findall(source)) != 1
    ):
        raise ValueError(
            "The single literal contracts.__version__ authority is required"
        )
    return ReleaseNumber.parse(assignments[0].value.value)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON metadata keys are not allowed")
        result[key] = value
    return result


def metadata(source: str) -> dict:
    if len(source.encode()) > 1024 * 1024:
        raise ValueError("Version metadata exceeds the bounded input limit")
    value = json.loads(source, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise TypeError("Version metadata must be a JSON object")
    return value


def prepare_versions(base_source: str, files: dict[str, str]) -> dict[str, str]:
    """Set the next mainline number, idempotently, without dependency churn."""
    base = authority_version(base_source)
    expected = base.next()
    current = authority_version(files[AUTHORITY])
    if current not in {base, expected}:
        raise ValueError("PR release is neither its base nor the next mainline number")
    output = dict(files)
    output[AUTHORITY] = ASSIGNMENT.sub(
        lambda match: f'{match[1]}"{expected}"', files[AUTHORITY]
    )
    package, lock = metadata(files[PACKAGE]), metadata(files[LOCK])
    if (
        package.get("name") != "x-patentsar-frontend"
        or lock.get("name") != package["name"]
    ):
        raise ValueError("Derived frontend metadata has a foreign product identity")
    packages = lock.get("packages")
    root_package = packages.get("") if isinstance(packages, dict) else None
    if (
        not isinstance(root_package, dict)
        or root_package.get("name") != package["name"]
    ):
        raise ValueError("The npm lock must retain its root package identity")
    for value in (package, lock, root_package):
        if ReleaseNumber.parse(value.get("version")) not in {base, expected}:
            raise ValueError("Derived frontend release metadata is inconsistent")
        value["version"] = str(expected)
    output[PACKAGE] = json.dumps(package, ensure_ascii=False, indent=2) + "\n"
    output[LOCK] = json.dumps(lock, ensure_ascii=False, indent=2) + "\n"
    return {name: content for name, content in output.items() if content != files[name]}


def verify_versions(base_source: str, files: dict[str, str]) -> ReleaseNumber:
    expected = authority_version(base_source).next()
    if authority_version(files[AUTHORITY]) != expected or prepare_versions(
        base_source, files
    ):
        raise ValueError(
            "PR must contain exactly the next release and synchronized metadata"
        )
    return expected
