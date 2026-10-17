"""Every proved original depiction must share recognition and chemical gates."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from lateral_structure_support import LateralStructureControls
from PIL import Image
from test_uniform_recognition import observation

from patent_sar_extractor.application.smiles_policy import _smiles_acceptance_errors
from patent_sar_extractor.application.stage_cache import _bindings_ocsr_digest
from patent_sar_extractor.core.formal_export import qualified_records
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.smiles_artifact import build_smiles_artifact


class ReprintRecognitionTests(LateralStructureControls, unittest.TestCase):
    def test_all_original_depictions_are_scheduled_not_only_primary_rows(self):
        _, payload = self.run_case(selected=True)
        entries = payload["compound_catalog"]["entries"]
        expected = {
            source["structure_id"]
            for entry in entries
            for source in [entry, *entry.get("additional_sources", [])]
        }
        self.assertEqual(
            {row["structure_id"] for row in recognition_inputs(payload).work_items},
            expected,
        )

    def test_formal_row_cannot_redirect_an_unchanged_original_owner(self):
        _, payload = self.run_case(selected=True)
        payload["final_bindings"][0] = {
            **payload["final_bindings"][0],
            "image_path": payload["final_bindings"][1]["image_path"],
        }
        with self.assertRaisesRegex(ValueError, "source"):
            recognition_inputs(payload)

    def test_relative_reprint_crop_uses_the_same_binding_root_as_the_worker(self):
        result, payload = self.run_case(selected=True)
        path = Path(result["output_files"]["json"])
        alias = payload["compound_catalog"]["entries"][0]["additional_sources"][0]
        image = Path(alias["image_path"])
        for field in ("image_path", "source_image_path", "ocsr_image_path"):
            if alias.get(field):
                alias[field] = os.path.relpath(Path(alias[field]), path.parent)
        path.write_text(json.dumps(payload))
        before = _bindings_ocsr_digest(str(path))
        with Image.open(image) as original:
            changed = original.convert("RGB")
            changed.putpixel((1, 1), (56, 34, 12))
            changed.save(image)
        self.assertNotEqual(before, _bindings_ocsr_digest(str(path)))

    def test_metadata_frame_changes_invalidate_without_independent_pixel_preparation(
        self,
    ):
        result, _ = self.run_case(selected=True)
        metadata = json.loads((self.root / "structures.json").read_text())
        folder = self.root / "structures"
        folder.mkdir()
        path = folder / "metadata.json"
        path.write_text(json.dumps(metadata))
        with patch(
            "patent_sar_extractor.core.ocsr.recognition_source_paths.source_geometry",
            side_effect=AssertionError(
                "Fingerprinting must not inspect/prepare image pixels"
            ),
        ):
            before = _bindings_ocsr_digest(result["output_files"]["json"])
            metadata["structures"][0]["bbox_pdf"][0] += 1
            path.write_text(json.dumps(metadata))
            self.assertNotEqual(
                before, _bindings_ocsr_digest(result["output_files"]["json"])
            )

    def test_changing_reprint_pixels_invalidates_the_only_recognition_checkpoint(self):
        result, payload = self.run_case(selected=True)
        path = Path(result["output_files"]["json"])
        entries = payload["compound_catalog"]["entries"]
        alias = entries[0]["additional_sources"][0]
        records = json.loads((self.root / "structures.json").read_text())["structures"]
        image = Path(
            next(
                row["image_path"]
                for row in records
                if row["structure_id"] == alias["structure_id"]
            )
        )
        before = _bindings_ocsr_digest(str(path))
        with Image.open(image) as original:
            changed = original.convert("RGB")
            changed.putpixel((0, 0), (12, 34, 56))
            changed.save(image)
        self.assertNotEqual(before, _bindings_ocsr_digest(str(path)))

    def test_clean_primary_results_cannot_accept_unobserved_reprints(self):
        _, payload = self.run_case(selected=True)
        formal = payload["final_bindings"]
        records = [observation(row) for row in formal]
        self.assertTrue(
            _smiles_acceptance_errors(build_smiles_artifact(records), payload)
        )

    def test_export_helper_also_requires_original_reprint_findings(self):
        _, payload = self.run_case(selected=True)
        bindings = payload["final_bindings"]
        with self.assertRaisesRegex(ValueError, "[Rr]eprint"):
            qualified_records(bindings, [observation(row) for row in bindings])

    def test_same_size_and_restored_timestamp_cannot_hide_changed_reprint_bytes(self):
        result, payload = self.run_case(selected=True)
        alias = payload["compound_catalog"]["entries"][0]["additional_sources"][0]
        image = Path(alias["image_path"])
        path = result["output_files"]["json"]
        initial = _bindings_ocsr_digest(path)
        info = image.stat()
        original = image.read_bytes()
        image.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        os.utime(image, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertNotEqual(_bindings_ocsr_digest(path), initial)

    def test_total_source_budget_refuses_overflow_not_partial_success(self):
        _, payload = self.run_case(selected=True)
        with (
            patch(
                "patent_sar_extractor.core.ocsr.recognition_inputs.MAX_CATALOG_RECORDS",
                3,
            ),
            self.assertRaisesRegex(ValueError, "exceeds"),
        ):
            recognition_inputs(payload)

    def test_artifact_budget_covers_all_roles_together(self):
        with (
            patch("patent_sar_extractor.smiles_artifact.MAX_RECOGNITION_SOURCES", 3),
            self.assertRaisesRegex(ValueError, "exceeds"),
        ):
            build_smiles_artifact([{}, {}], source_records=[{}], reprint_records=[{}])

    def artifact(self, payload, primary="CCO", reprint="OCC"):
        plan = recognition_inputs(payload)
        return build_smiles_artifact(
            [observation(row, primary) for row in plan.formal],
            source_records=[observation(row, primary) for row in plan.supplemental],
            reprint_records=[observation(row, reprint) for row in plan.reprints],
        )

    def test_same_complete_graph_under_different_smiles_order_is_consistent(self):
        _, payload = self.run_case(selected=True)
        for primary, repeated in (("CCO", "OCC"), ("CCO.[Na+]", "[Na+].OCC")):
            with self.subTest(primary=primary):
                artifact = self.artifact(payload, primary, repeated)
                self.assertEqual(_smiles_acceptance_errors(artifact, payload), [])

    def test_stereo_isotope_charge_components_and_connectivity_cannot_be_voted_away(
        self,
    ):
        _, payload = self.run_case(selected=True)
        cases = (
            ("CCO", "CCC"),
            ("C[C@H](F)Cl", "C[C@@H](F)Cl"),
            ("C[C@H](F)Cl", "CC(F)Cl"),
            ("F/C=C/F", "F/C=C\\F"),
            ("CCO", "[13CH3]CO"),
            ("CCN", "CC[NH3+]"),
            ("CCO.[Na+]", "CCO"),
            ("CCO.CCO", "CCO"),
        )
        for primary, repeated in cases:
            with self.subTest(primary=primary, repeated=repeated):
                artifact = self.artifact(payload, primary, repeated)
                for row in artifact["reprint_records"]:
                    row["token_confidence"] = {"minimum": 1.0, "mean": 1.0}
                self.assertTrue(_smiles_acceptance_errors(artifact, payload))

    def test_same_saved_canonical_graph_cannot_hide_a_different_raw_model_graph(self):
        _, payload = self.run_case(selected=True)
        artifact = self.artifact(payload, "CCO", "CCC")
        for row in artifact["reprint_records"]:
            row["canonical_smiles"] = artifact["records"][0]["canonical_smiles"]
        self.assertTrue(_smiles_acceptance_errors(artifact, payload))

    def test_alternate_molecular_text_cannot_override_verified_raw_identity(self):
        _, payload = self.run_case(selected=True)
        artifact = self.artifact(payload)
        artifact["reprint_records"][0]["smiles"] = "CCC"
        self.assertTrue(_smiles_acceptance_errors(artifact, payload))

    def test_unknown_query_and_extra_encoding_are_not_determinate_reprints(self):
        _, payload = self.run_case(selected=True)
        for raw in ("CC*", "CCO |atomProp:0.p.1|", "not-a-smiles"):
            with self.subTest(raw=raw):
                self.assertTrue(
                    _smiles_acceptance_errors(
                        self.artifact(payload, "CCO", raw), payload
                    )
                )

    def test_omitted_reordered_and_duplicate_reprints_remain_rejected(self):
        _, payload = self.run_case(selected=True)
        for mutation in (
            lambda rows: rows.pop(),
            lambda rows: rows.reverse(),
            lambda rows: rows.append(dict(rows[0])),
        ):
            artifact = self.artifact(payload)
            mutation(artifact["reprint_records"])
            self.assertTrue(_smiles_acceptance_errors(artifact, payload))

    def test_foreign_reprint_owner_is_a_technical_contract_error(self):
        _, payload = self.run_case(selected=True)
        artifact = self.artifact(payload)
        artifact["reprint_records"][0]["cpd_id"] = "Compound 999"
        with self.assertRaisesRegex(ValueError, "foreign"):
            _smiles_acceptance_errors(artifact, payload)

    def test_clean_syntax_flags_cannot_override_failed_source_execution(self):
        _, payload = self.run_case(selected=True)
        for field, value in (
            ("OCSR_status", "engine_unavailable"),
            ("OCSR_quality_flag", None),
            ("rdkit_valid", 1),
        ):
            with self.subTest(field=field):
                artifact = self.artifact(payload)
                artifact["reprint_records"][0][field] = value
                self.assertTrue(_smiles_acceptance_errors(artifact, payload))
