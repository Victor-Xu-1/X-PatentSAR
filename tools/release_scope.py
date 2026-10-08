"""Preserve author-selected regressions when automation adds version metadata."""

from __future__ import annotations

import json
import re

from tools.version_policy import metadata

SCOPE = ".github/verification_scope.json"
FIELDS = {
    "schema_version",
    "base_sha",
    "changed_paths",
    "python_modules",
    "frontend_tests",
    "browser_tests",
}
VERSION_TESTS = (
    "tests.test_release_policy.ReleaseNumberTests",
    "tests.test_standalone.StandalonePackagingTests.test_version_command_uses_product_version",
    "tests.test_standalone.StandalonePackagingTests.test_frontend_product_versions_match_the_single_authority",
)


def prepare_scope(source: str, base: str, paths: list[str]) -> str:
    if len(source.encode()) > 65536 or re.fullmatch(r"[a-f0-9]{40}", base) is None:
        raise ValueError("A bounded scope and exact base are required")
    value = metadata(source)
    if (
        set(value) != FIELDS
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("The existing six-field verification scope is required")
    if value["base_sha"] != base:
        raise ValueError(
            "Update the PR and its verification scope to current main first"
        )
    for name in ("changed_paths", "python_modules", "frontend_tests", "browser_tests"):
        items = value[name]
        if not isinstance(items, list) or len(items) > (
            512 if name == "changed_paths" else 32
        ):
            raise ValueError("Verification selection must stay explicitly bounded")
        if any(not isinstance(item, str) or len(item) > 256 for item in items):
            raise ValueError("Verification selections must be bounded names")
    selected = value["python_modules"]
    for case in VERSION_TESTS:
        if not any(case == item or case.startswith(item + ".") for item in selected):
            selected.append(case)
    if len(selected) > 32:
        raise ValueError(
            "Adding direct version consumers exceeds the test-selection limit"
        )
    value["changed_paths"] = sorted(set(paths) | {SCOPE})
    if len(value["changed_paths"]) > 512:
        raise ValueError("Release scope exceeds the changed-path limit")
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
