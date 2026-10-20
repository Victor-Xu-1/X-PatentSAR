"""Read-only acceptance regressions; contract fixtures are not extraction evidence."""

from __future__ import annotations

import copy
import hashlib
import io
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from patent_sar_extractor import contracts
from patent_sar_extractor.core.activity_coverage import coverage_packet, source_record
from patent_sar_extractor.core.binding_catalog import compound_catalog
from patent_sar_extractor.core.binding_source_references import reference_scope
from patent_sar_extractor.core.ocsr.candidate_inventory import (
    inventory_digest,
    original_candidate_inventory,
)
from patent_sar_extractor.core.ocsr.generation import observe_generation
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import (
    observe_stereo_symbols,
    source_checked_qc,
)
from patent_sar_extractor.core.structure_inventory import inventory_packet
from patent_sar_extractor.smiles_artifact import build_smiles_artifact
from patent_sar_extractor.web.acceptance import ARTIFACTS, authority
from tests.test_caption_reading_semantics import binding as caption_binding


def complete_payloads():
    payloads = {
        name: contracts.artifact_identity(schema, version)
        for name, (_, schema, version) in ARTIFACTS.items()
    }
    payloads["summary"].update(
        status="complete",
        steps={name: {"status": "ok"} for name in contracts.CORE_STAGE_ORDER},
        main_chain=list(contracts.CORE_STAGE_ORDER),
    )
    payloads["classification"].update(page_count=1, activity_pages=[0])
    payloads["activity"].update(
        active_cpds=["Compound 1"],
        rows=[
            {"cpd": "Compound 1", "activity_values": {"IC50(nM)": "1"}, "page_no": 1}
        ],
        coverage=coverage_packet(
            [0],
            [
                source_record(
                    1, "text", None, "Control", "IC50(nM)", "parsed", "declared_text", 1
                )
            ],
            [SimpleNamespace(page_no=1)],
        ),
    )
    binding = {
        **caption_binding(
            [{"method": "native_cell", "text": "Compound 1"}],
            cpd="Compound 1",
            structure_id="S0",
            diagram=(20, 40, 120, 140),
        ),
        "structure_id": "S0",
        "page_no": 1,
        "image_path": "/controlled-source/controlled.png",
        "bbox_pdf": [20, 40, 120, 140],
        "source_pdf_sha256": "a" * 64,
        "struct_x0": 20,
        "struct_y0": 40,
        "struct_x1": 120,
        "struct_y1": 140,
        "struct_area": 10000,
        "struct_width": 100,
        "struct_height": 100,
        "authoritative_table_source_label": "Compound 1",
    }
    payloads["structures"]["structures"] = [binding]
    payloads["structures"].update(
        total_structures=1,
        source_inventory=inventory_packet(
            1,
            [
                {
                    "page_no": 1,
                    "status": "detected",
                    "scope": "full_page",
                    "candidates": 1,
                }
            ],
        ),
    )
    payloads["bindings"].update(
        execution_mode="production_structure_led",
        compound_catalog=compound_catalog([binding], []),
        source_sections=[],
        source_reference_scope=reference_scope([], "a" * 64),
    )
    payloads["smiles"].update(
        execution_mode="production_decimer",
        formal_acceptance_scope="proved_printed_identifier_structure_corpus",
        source_records=[],
        reprint_records=[],
        records=[
            {
                "cpd_id": "Compound 1",
                "structure_id": "S0",
                "ocsr_source_structure_id": "S0",
                "canonical_smiles": "CCO",
                "rdkit_valid": True,
                "OCSR_quality_flag": "ok",
                "OCSR_status": "success",
            }
        ],
    )
    # Explicit graph/source-risk controls, not a model recognition assertion.
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image, format="PNG")
    screened = source_checked_qc(
        qc_smiles("CCO"), observe_stereo_symbols(image.getvalue())
    )
    payloads["smiles"]["records"][0].update(
        screened,
        raw_smiles="CCO",
        generation=observe_generation(["<start>", "C", "C", "O", "<end>"])[1],
        image_hash=hashlib.sha256(image.getvalue()).hexdigest(),
        ocsr_original_input=binding["image_path"],
        page_no=1,
        OCSR_engine="decimer",
        model_fingerprint="b" * 64,
    )
    # Explicit scalar/protocol controls for this pure decision unit. Native
    # filesystem replay is independently covered by test_candidate_projection;
    # these declared values are not a PDF/recognizer/scientific acceptance.
    inventory, entries = original_candidate_inventory(
        payloads["structures"],
        {
            **contracts.artifact_identity(
                contracts.STEP_MANIFEST_SCHEMA, contracts.STEP_MANIFEST_SCHEMA_VERSION
            ),
            "fingerprint": {
                "step": "structures",
                "pdf_sha256": "a" * 64,
                "params": {
                    "structure_pages": [0],
                    "structure_worker_contract_version": contracts.STRUCTURE_WORKER_VERSION,
                },
            },
        },
        "a" * 64,
        Path("/controlled-source"),
        read_digest=lambda _path: hashlib.sha256(image.getvalue()).hexdigest(),
    )
    inventory["entries"] = [
        {**entries[0], "observation": {"role": "formal", "index": 0}}
    ]
    inventory["identity"] = inventory_digest(inventory)
    payloads["smiles"] = build_smiles_artifact(
        payloads["smiles"]["records"], candidate_inventory=inventory
    )
    payloads["qa"].update(ok=True, acceptance={"ok": True, "hard_errors": []})
    return payloads


def partial_payloads(status="running"):
    payloads = complete_payloads()
    for name in ("locator", "structures", "bindings", "smiles", "qa"):
        payloads[name] = None
    payloads["summary"].update(
        status=status,
        steps={"classify": {"status": "ok"}, "activity": {"status": "running"}},
    )
    return payloads


class AcceptanceTests(unittest.TestCase):
    def test_saved_qa_cannot_replace_or_omit_the_complete_original_inventory(self):
        for mutation in ("scope", "metadata"):
            payloads = complete_payloads()
            if mutation == "scope":
                payloads["smiles"].update(
                    candidate_inventory=None,
                    recognition_input_scope="proved_sources_only",
                )
            else:
                payloads["structures"]["changed_input"] = True
            with self.subTest(mutation=mutation):
                result, historical = authority(payloads, pdf_verified=True, marker=None)
                self.assertEqual(result.state, "failed")
                self.assertFalse(historical)
                self.assertIn("detected-image", str(result.errors))

    def test_successful_qa_cannot_hide_a_missing_original_page_inventory(self):
        payloads = complete_payloads()
        payloads["structures"].pop("source_inventory")
        result, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "failed")
        self.assertIn("structure-page coverage", str(result.errors))

    def test_empty_activity_is_legitimate_only_with_coverage_proof(self):
        payloads = complete_payloads()
        payloads["activity"].update(active_cpds=[], rows=[])
        result, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "failed")
        payloads["classification"]["activity_pages"] = []
        payloads["activity"]["coverage"] = coverage_packet([], [], [])
        result, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "accepted")

    def test_resumed_successful_stage_does_not_replay_a_previous_failure_as_current(
        self,
    ):
        payloads = partial_payloads()
        payloads["summary"]["steps"]["bind"] = {"status": "ok"}
        marker = {
            **contracts.artifact_identity(
                contracts.FAILURE_MARKER_SCHEMA, contracts.FAILURE_MARKER_SCHEMA_VERSION
            ),
            "stage": "bind",
            "errors": ["previous binding failure"],
        }
        result, _ = authority(payloads, pdf_verified=True, marker=marker)
        self.assertEqual(result.state, "not_run")
        self.assertNotIn("previous binding failure", str(result.errors))
        payloads["summary"]["steps"]["bind"] = {"status": "failed"}
        failed, _ = authority(payloads, pdf_verified=True, marker=marker)
        self.assertEqual(failed.state, "failed")
        self.assertIn("previous binding failure", failed.errors)

    def test_current_failure_marker_is_failed_not_historical_when_downstream_absent(
        self,
    ):
        marker = {
            **contracts.artifact_identity(
                contracts.FAILURE_MARKER_SCHEMA, contracts.FAILURE_MARKER_SCHEMA_VERSION
            ),
            "stage": "activity",
            "errors": ["Activity rows conflict before binding."],
        }
        result, historical = authority(
            partial_payloads("failed_accuracy_gate"), pdf_verified=True, marker=marker
        )
        self.assertEqual(result.state, "failed")
        self.assertFalse(historical)
        self.assertIn("Activity rows conflict before binding.", result.errors)

    def test_current_running_and_checkpointed_runs_are_not_historical_or_accepted(self):
        for status in ("running", "started", "classifying"):
            with self.subTest(status=status):
                result, historical = authority(
                    partial_payloads(status), pdf_verified=True, marker=None
                )
                self.assertEqual(result.state, "not_run")
                self.assertFalse(historical)
                self.assertTrue(result.errors)

    def test_summary_stage_failure_remains_failed_without_marker(self):
        payloads = partial_payloads()
        payloads["summary"]["steps"]["activity"] = {
            "status": "failed",
            "acceptance_errors": ["Ambiguous activity row at /private/patent.pdf."],
        }
        result, historical = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "failed")
        self.assertFalse(historical)
        self.assertIn("[path]", result.errors[0])
        self.assertNotIn("/private", str(result.errors))

    def test_missing_current_artifact_does_not_become_historical_or_accepted(self):
        for name in ARTIFACTS:
            with self.subTest(name=name):
                payloads = complete_payloads()
                payloads[name] = None
                result, historical = authority(payloads, pdf_verified=True, marker=None)
                self.assertNotEqual(result.state, "accepted")
                self.assertFalse(historical)

    def test_stale_or_unversioned_present_artifact_remains_historical(self):
        for name in ARTIFACTS:
            with self.subTest(name=name):
                payloads = complete_payloads()
                payloads[name]["ruleset"]["version"] = "0.0.0"
                result, historical = authority(payloads, pdf_verified=True, marker=None)
                self.assertEqual(result.state, "historical")
                self.assertTrue(historical)
        payloads["smiles"] = []
        result, historical = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "historical")
        self.assertTrue(historical)

    def test_current_invalid_shapes_or_modes_fail_without_historical_claim(self):
        for name, field, value in (
            ("activity", "rows", {}),
            ("activity", "active_cpds", []),
            ("bindings", "final_bindings", {}),
            ("bindings", "execution_mode", "diagnostic"),
            ("smiles", "records", {}),
            ("smiles", "execution_mode", "diagnostic"),
            ("structures", "structures", {}),
            ("summary", "steps", []),
        ):
            with self.subTest(name=name, field=field):
                payloads = complete_payloads()
                payloads[name][field] = value
                result, historical = authority(payloads, pdf_verified=True, marker=None)
                self.assertEqual(result.state, "failed")
                self.assertFalse(historical)

    def test_current_complete_run_requires_original_both_qa_checks_and_no_marker(self):
        baseline = complete_payloads()
        accepted, historical = authority(baseline, pdf_verified=True, marker=None)
        self.assertEqual(accepted.state, "accepted")
        self.assertFalse(historical)
        for field in ("ok", "acceptance"):
            payloads = copy.deepcopy(baseline)
            if field == "ok":
                payloads["qa"][field] = False
            else:
                payloads["qa"][field]["ok"] = False
            result, _ = authority(payloads, pdf_verified=True, marker=None)
            self.assertEqual(result.state, "failed")
        for marker in ({}, {"errors": "invalid"}, {"errors": ["traceback secret"]}):
            result, _ = authority(baseline, pdf_verified=True, marker=marker)
            self.assertEqual(result.state, "failed")
            self.assertNotIn("secret", str(result.errors))
        result, historical = authority(baseline, pdf_verified=False, marker=None)
        self.assertEqual(result.state, "failed")
        self.assertFalse(historical)

    def test_summary_failure_cannot_be_overridden_by_complete_qa_artifacts(self):
        payloads = complete_payloads()
        payloads["summary"]["status"] = "failed_accuracy_gate"
        result, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "failed")

    def test_current_running_summary_cannot_reuse_a_completed_qa_decision(self):
        payloads = complete_payloads()
        payloads["summary"]["status"] = "running"
        result, historical = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(result.state, "not_run")
        self.assertFalse(historical)

    def test_empty_and_untrusted_failure_error_collections_remain_bounded(self):
        payloads = partial_payloads("failed_accuracy_gate")
        for errors in ([], "invalid", [None], ["Repeated failure"] * 1000):
            with self.subTest(errors_type=type(errors).__name__):
                result, _ = authority(
                    payloads, pdf_verified=True, marker={"errors": errors}
                )
                self.assertEqual(result.state, "failed")
                self.assertTrue(result.errors)
                self.assertLessEqual(len(result.errors), 100)
