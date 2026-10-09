"""Select the smallest controlled browser fixture for the explicit CI scope."""

from __future__ import annotations

import json
from pathlib import Path

PREFIX = "frontend/e2e/"
COMMON = {"product-version.spec.ts"}
MODES = (
    (
        "sar",
        "sar-workbench.spec.ts",
        COMMON
        | {
            "topbar.spec.ts",
            "language-switch.spec.ts",
            "sar-workbench.spec.ts",
            "sar-study.spec.ts",
        },
    ),
    (
        "sar",
        "sar-study.spec.ts",
        COMMON | {"sar-workbench.spec.ts", "sar-study.spec.ts", "expert-visual.spec.ts"},
    ),
    (
        "llm-recovery",
        "llm-recovery-stack.spec.ts",
        COMMON | {"llm-recovery.spec.ts", "llm-recovery-stack.spec.ts"},
    ),
    (
        "llm-settings",
        "llm-settings.spec.ts",
        COMMON
        | {
            "topbar.spec.ts",
            "llm-settings.spec.ts",
            "identifier-labels.spec.ts",
            "llm-recovery.spec.ts",
        },
    ),
)


def fixture_mode(selected: set[str]) -> str:
    for mode, required, allowed in MODES:
        if PREFIX + required in selected and selected <= {
            PREFIX + name for name in allowed
        }:
            return mode
    if selected <= {
        PREFIX + name for name in COMMON | {"topbar.spec.ts", "language-switch.spec.ts"}
    }:
        return "read-only"
    return "execution"


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    scope = json.loads((root / ".github/verification_scope.json").read_text())
    print(fixture_mode(set(scope["browser_tests"])))
