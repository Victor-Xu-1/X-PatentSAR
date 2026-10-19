"""One source catalogue, without a second expanded copy of the same records."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from catalog_source_support import original_catalogue

from patent_sar_extractor import contracts
from patent_sar_extractor.artifact_catalog import pack_shared_json, read_artifact_json
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.binding_records import binding_records
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.ocsr.candidate_inputs import load_source_observation_plan
from patent_sar_extractor.core.ocsr.candidate_observations import (
    validate_candidate_observations,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs


class BindingRecordAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="patentsar-record-authority-"
        )
        cls.root = Path(cls.temporary.name)
        write_json_atomic(
            cls.root / "structures/metadata.json",
            contracts.artifact_identity(
                contracts.STRUCTURES_SCHEMA, contracts.STRUCTURES_SCHEMA_VERSION
            ),
        )
        cls.pdf, cls.path, cls.payload = original_catalogue(
            cls.root, cls.root, labels=("23A", "37"), selected=False
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_normal_writer_saves_one_authoritative_source_record_collection(self):
        with self.path.open("rb") as stream:
            saved = read_artifact_json(stream)
        self.assertEqual(
            [r["cpd"] for r in saved["compound_catalog"]["entries"]],
            ["Compound 23A", "Compound 37"],
        )
        self.assertNotIn("final_bindings", list(saved))

    def test_normal_recognition_reads_the_canonical_catalogue_without_a_duplicate(self):
        payload = copy.deepcopy(self.payload)
        payload.pop("final_bindings", None)
        plan = recognition_inputs(payload)
        self.assertEqual(
            [row["cpd"] for row in plan.formal], ["Compound 23A", "Compound 37"]
        )

    def test_a_second_conflicting_record_authority_remains_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload["final_bindings"] = [
            {"cpd": "Compound 99", "structure_id": "not-an-original-source"}
        ]
        with self.assertRaises(ValueError):
            recognition_inputs(payload)

    def test_current_missing_catalogue_or_empty_competing_collection_refuses(self):
        for field in ("final_bindings", "bindings"):
            payload = copy.deepcopy(self.payload)
            payload[field] = []
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "competing record authority"),
            ):
                binding_records(payload)
        payload = copy.deepcopy(self.payload)
        payload.pop("compound_catalog")
        with self.assertRaisesRegex(ValueError, "original source catalogue"):
            binding_records(payload, legacy=True)

    def test_counts_are_exact_integers_not_coercible_saved_success(self):
        for count in (True, 2.0, "2", None, 1, 3):
            for location in ("numbered_compounds", "final_bindings_count"):
                payload = copy.deepcopy(self.payload)
                destination = (
                    payload["compound_catalog"]
                    if location == "numbered_compounds"
                    else payload
                )
                destination[location] = count
                with (
                    self.subTest(count=count, location=location),
                    self.assertRaisesRegex(ValueError, "record count"),
                ):
                    binding_records(payload)

    def test_source_reference_ledger_is_independent_of_the_only_catalogue(self):
        payload = copy.deepcopy(self.payload)
        payload["compound_catalog"]["entries"].pop()
        payload["compound_catalog"]["numbered_compounds"] = 1
        payload["final_bindings_count"] = 1
        self.assertEqual(len(binding_records(payload)), 1)
        with self.assertRaisesRegex(ValueError, "source-reference proof"):
            coverage_errors(payload)

    def test_saved_complete_observations_cannot_follow_a_redirected_catalogue_image(
        self,
    ):
        from recognition_source_support import complete_observation_artifact

        original = copy.deepcopy(self.payload)
        artifact = complete_observation_artifact(
            original,
            pdf=self.pdf,
            structures=self.root / "structures/metadata.json",
            binding_dir=self.root / "structure_bindings",
        )
        payload = copy.deepcopy(original)
        row = payload["compound_catalog"]["entries"][0]
        other = self.root / "foreign-observation.png"
        from PIL import Image

        Image.new("RGB", (60, 35), "red").save(other)
        for field in ("image_path", "source_image_path", "ocsr_image_path"):
            row[field] = str(other)
        plan = load_source_observation_plan(
            recognition_inputs(payload),
            structures_json=self.root / "structures/metadata.json",
            pdf_path=self.pdf,
            binding_dir=self.root / "structure_bindings",
            binding_pdf_sha256=payload["source_reference_scope"]["original_pdf_sha256"],
        )
        # Original detector assets still require their own observations; the
        # changed catalogue cannot reuse a previously complete scientific result.
        with self.assertRaisesRegex(ValueError, "inventory.*changed"):
            validate_candidate_observations(plan, artifact)

    def test_legacy_rows_need_explicit_review_and_cannot_gain_current_acceptance(self):
        payload = copy.deepcopy(self.payload)
        payload["schema"]["version"] -= 1
        payload["final_bindings"] = payload["compound_catalog"]["entries"]
        with self.assertRaisesRegex(ValueError, "current source identity"):
            binding_records(payload)
        self.assertEqual(len(binding_records(payload, legacy=True)), 2)
        with self.assertRaisesRegex(ValueError, "current source-led identity"):
            coverage_errors(payload)


class CatalogueTransportBudgetTests(unittest.TestCase):
    def test_large_differing_catalogues_keep_all_rows_with_the_existing_budget(self):
        # Transport-only numeric observations, not chemical or OCR truth claims.
        for count in (17, 1191, 1600):
            with self.subTest(count=count):
                rows = [
                    {"original_id": f"S-{n:04}", "observations": list(range(850))}
                    for n in range(count)
                ]
                payload = {"compound_catalog": {"entries": rows}}
                restored = read_artifact_json(json.dumps(pack_shared_json(payload)))
                self.assertEqual(restored, payload)
                self.assertEqual(len(restored["compound_catalog"]["entries"]), count)
                if count >= 1191:
                    with self.assertRaisesRegex(ValueError, "node expansion"):
                        pack_shared_json({**payload, "final_bindings": rows})
