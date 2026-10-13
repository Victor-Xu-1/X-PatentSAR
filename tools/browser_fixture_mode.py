"""Select the smallest controlled browser fixture for the explicit CI scope."""

from __future__ import annotations

import json
from pathlib import Path

PREFIX = "frontend/e2e/"
# Read-only specs can accompany any controlled feature fixture.
COMMON = {
    "topbar.spec.ts",
    "jobs-project-recovery.spec.ts",
    "product-version.spec.ts",
    "recent-density.spec.ts",
    "editor-viewport.spec.ts",
    "structure-details.spec.ts",
    "expert-controls.spec.ts",
    "column-filter-viewport.spec.ts",
}
MODES = (
    (
        "sar",
        "sar-local-comparison.spec.ts",
        COMMON | {"sar-local-comparison.spec.ts", "sar-catalog.spec.ts"},
    ),
    (
        "sar",
        "sar-catalog.spec.ts",
        COMMON | {"sar-catalog.spec.ts", "sar-reanalysis.spec.ts"},
    ),
    (
        "sar",
        "sar-reanalysis.spec.ts",
        COMMON | {"sar-reanalysis.spec.ts"},
    ),
    (
        "sar",
        "sar-task-history.spec.ts",
        COMMON | {"sar-task-history.spec.ts"},
    ),
    (
        "sar",
        "sar-supporting-deltas.spec.ts",
        COMMON
        | {
            "sar-supporting-deltas.spec.ts",
            "sar-single-site.spec.ts",
            "sar-interval-boundaries.spec.ts",
        },
    ),
    (
        "sar",
        "sar-multiple-bonds.spec.ts",
        COMMON
        | {
            "sar-multiple-bonds.spec.ts",
            "sar-single-site.spec.ts",
            "sar-multiport.spec.ts",
            "sar-hydrogen.spec.ts",
        },
    ),
    (
        "sar",
        "sar-log-potency.spec.ts",
        COMMON | {"sar-log-potency.spec.ts", "sar-interval-boundaries.spec.ts"},
    ),
    (
        "sar",
        "sar-interval-boundaries.spec.ts",
        COMMON | {"sar-interval-boundaries.spec.ts"},
    ),
    (
        "history",
        "history-trash-clear.spec.ts",
        COMMON | {"history-trash-clear.spec.ts", "sar-preview-coverage.spec.ts"},
    ),
    ("sar", "sar-preview-coverage.spec.ts", COMMON | {"sar-preview-coverage.spec.ts"}),
    ("sar", "sar-csv-defaults.spec.ts", COMMON | {"sar-csv-defaults.spec.ts"}),
    (
        "sar",
        "sar-indicator-defaults.spec.ts",
        COMMON | {"sar-indicator-defaults.spec.ts"},
    ),
    (
        "sar",
        "sar-manual-directions.spec.ts",
        COMMON | {"sar-manual-directions.spec.ts", "sar-single-site.spec.ts"},
    ),
    (
        "sar",
        "sar-aromatic.spec.ts",
        COMMON
        | {
            "sar-aromatic.spec.ts",
            "sar-threeport.spec.ts",
            "sar-hydrogen.spec.ts",
            "sar-single-site.spec.ts",
            "sar-multiport.spec.ts",
        },
    ),
    (
        "sar",
        "sar-threeport.spec.ts",
        COMMON
        | {
            "sar-threeport.spec.ts",
            "sar-hydrogen.spec.ts",
            "sar-single-site.spec.ts",
            "sar-multiport.spec.ts",
        },
    ),
    (
        "sar",
        "sar-hydrogen.spec.ts",
        COMMON
        | {"sar-hydrogen.spec.ts", "sar-single-site.spec.ts", "sar-multiport.spec.ts"},
    ),
    (
        "sar",
        "sar-multiport.spec.ts",
        COMMON
        | {
            "sar-multiport.spec.ts",
            "sar-single-site.spec.ts",
            "sar-chart-presentation.spec.ts",
        },
    ),
    (
        "sar",
        "sar-numbered-scope.spec.ts",
        COMMON | {"sar-numbered-scope.spec.ts"},
    ),
    (
        "sar",
        "sar-source-unit.spec.ts",
        COMMON | {"sar-source-unit.spec.ts"},
    ),
    (
        "sar",
        "sar-candidate-source.spec.ts",
        COMMON | {"sar-candidate-source.spec.ts"},
    ),
    (
        "sar",
        "sar-member-navigation.spec.ts",
        COMMON | {"sar-member-navigation.spec.ts", "sar-card-inspection.spec.ts"},
    ),
    (
        "sar",
        "sar-card-inspection.spec.ts",
        COMMON | {"sar-card-inspection.spec.ts"},
    ),
    (
        "sar",
        "sar-region-recovery.spec.ts",
        COMMON | {"sar-region-recovery.spec.ts", "sar-selection-viewport.spec.ts"},
    ),
    (
        "sar",
        "sar-selection-viewport.spec.ts",
        COMMON | {"sar-selection-viewport.spec.ts", "sar-atom-label.spec.ts"},
    ),
    (
        "sar",
        "sar-atom-label.spec.ts",
        COMMON | {"sar-atom-label.spec.ts"},
    ),
    (
        "sar",
        "correction-response.spec.ts",
        COMMON
        | {
            "correction-response.spec.ts",
            "expert-visual.spec.ts",
            "expert-controls.spec.ts",
        },
    ),
    (
        "read-only",
        "expert-visual.spec.ts",
        COMMON | {"expert-visual.spec.ts", "expert-controls.spec.ts"},
    ),
    (
        "sar",
        "sar-workbench.spec.ts",
        COMMON
        | {
            "language-switch.spec.ts",
            "sar-workbench.spec.ts",
            "sar-study.spec.ts",
        },
    ),
    (
        "sar",
        "sar-single-site.spec.ts",
        COMMON | {"sar-single-site.spec.ts", "sar-study.spec.ts"},
    ),
    (
        "sar",
        "sar-study.spec.ts",
        COMMON
        | {
            "sar-workbench.spec.ts",
            "sar-study.spec.ts",
            "expert-visual.spec.ts",
            "expert-controls.spec.ts",
        },
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
    if selected <= {PREFIX + name for name in COMMON | {"language-switch.spec.ts"}}:
        return "read-only"
    return "execution"


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    scope = json.loads((root / ".github/verification_scope.json").read_text())
    print(fixture_mode(set(scope["browser_tests"])))
