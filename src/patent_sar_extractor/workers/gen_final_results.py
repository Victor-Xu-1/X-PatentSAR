#!/usr/bin/env python3
"""Source-led export facade. Scientific rejection never becomes acceptance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The external base interpreter uses only this first-party package.
if __package__ in (None, ""):
    import runpy

    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "worker_bootstrap.py"),
        run_name="__main__",
    )

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    PAGE_CLASSIFICATION_SCHEMA,
    PAGE_CLASSIFICATION_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.formal_export import qualified_records
from patent_sar_extractor.core.formal_structure import (
    FORMAL_SCOPE,
    SOURCE_EXECUTION_MODE,
    coverage_errors,
)
from patent_sar_extractor.failures import write_failure_marker
from patent_sar_extractor.smiles_artifact import (
    smiles_artifact_is_current,
    smiles_records,
    smiles_source_records,
)
from patent_sar_extractor.workers.final_data import build_smiles_maps, load_data
from patent_sar_extractor.workers.final_sdf import generate_sdf
from patent_sar_extractor.workers.final_workbook import build_grade_note, generate_excel


def export_validation(
    bindings_path: str,
    smiles_path: str,
    activity_path: str,
    classification_path: str | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """Technical errors raise; scientific errors retain all expected source IDs."""
    with open(bindings_path, encoding="utf-8") as stream:
        binding_payload = json.load(stream)
    if not artifact_identity_matches(
        binding_payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION
    ):
        raise ValueError("Incompatible binding artifact for export")
    errors = coverage_errors(binding_payload)
    with open(smiles_path, encoding="utf-8") as stream:
        smiles = json.load(stream)
    if not smiles_artifact_is_current(smiles) or smiles_source_records(smiles):
        raise ValueError("Incompatible or nonuniform recognition artifact")
    if smiles.get("formal_acceptance_scope") != FORMAL_SCOPE:
        raise ValueError(
            "Recognition artifact does not declare source-led formal coverage"
        )
    with open(activity_path, encoding="utf-8") as stream:
        activity = json.load(stream)
    if not artifact_identity_matches(
        activity, ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION
    ):
        raise ValueError("Incompatible activity artifact for export")
    pages = None
    if classification_path:
        with open(classification_path, encoding="utf-8") as stream:
            classification = json.load(stream)
        if not artifact_identity_matches(
            classification,
            PAGE_CLASSIFICATION_SCHEMA,
            PAGE_CLASSIFICATION_SCHEMA_VERSION,
        ):
            raise ValueError("Incompatible classification proof for export")
        pages = classification.get("activity_pages")
        if not isinstance(pages, list) or any(
            type(page) is not int or page < 0 for page in pages
        ):
            raise ValueError("Malformed activity classification for export")
    errors.extend(activity_evidence_errors(activity, pages))
    bindings, records, findings = qualified_records(
        binding_payload["final_bindings"],
        smiles_records(smiles),
        str(Path(bindings_path).parent.parent),
    )
    errors.extend(findings)
    return bindings, records, list(dict.fromkeys(errors))


def main():
    parser = argparse.ArgumentParser(
        description="Export the proved printed-ID structure corpus"
    )
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--smiles", required=True)
    parser.add_argument("--activity", required=True)
    parser.add_argument("--classification")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--patent", default="")
    parser.add_argument("--rdkit-python", default=sys.executable)
    parser.add_argument(
        "--continue-on-scientific-errors",
        action="store_true",
        help="Write qualified observations and retain rejection, never weaken chemistry/ownership",
    )
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    bindings, records, errors = export_validation(
        args.bindings, args.smiles, args.activity, args.classification
    )
    _, _, _, _, activity, assays = load_data(
        args.bindings, args.smiles, activity_path=args.activity
    )
    with open(args.bindings, encoding="utf-8") as stream:
        expected = json.load(stream)["final_bindings"]
    receipt = {
        "execution_mode": SOURCE_EXECUTION_MODE,
        "formal_acceptance_scope": FORMAL_SCOPE,
        "formal_acceptance_authority": False,
        "qualified_only": True,
        "hard_errors": errors,
        "strict_coverage": {
            "expected_cpds": [row["cpd"] for row in expected],
            "expected_structure_ids": [row["structure_id"] for row in expected],
            "exported_cpds": [row["cpd"] for row in bindings],
            "exported_structure_ids": [row["structure_id"] for row in bindings],
        },
    }
    if errors:
        write_failure_marker(output.parent, "final_export", errors)
        if not args.continue_on_scientific_errors:
            write_json_atomic(output / "export_validation.json", receipt)
            raise RuntimeError(
                "Strict source-led export rejected: " + "; ".join(errors[:12])
            )
    maps = build_smiles_maps(records)
    with open(args.activity, encoding="utf-8") as stream:
        activity_rows = json.load(stream)["rows"]
    workbook = output / f"{args.patent}_final.xlsx"
    sdf = output / f"{args.patent}_final.sdf"
    generate_excel(
        bindings,
        *maps,
        activity,
        assays,
        str(workbook),
        str(Path(args.bindings).parent.parent),
        activity_rows=activity_rows,
    )
    result = generate_sdf(
        bindings,
        *maps,
        activity,
        assays,
        build_grade_note(assays),
        str(sdf),
        args.rdkit_python,
    )
    if result["returncode"] or result["failed"] or result["success"] != len(bindings):
        raise RuntimeError(
            "Qualified SDF producer failed to publish exact source coverage"
        )
    write_json_atomic(output / "export_validation.json", receipt)
    # Only final deterministic QA may clear a failure marker.


if __name__ == "__main__":
    main()
