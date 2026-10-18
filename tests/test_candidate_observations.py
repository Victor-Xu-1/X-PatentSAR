"""Whole detected-image observations do not invent printed compound ownership."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STEP_MANIFEST_SCHEMA,
    STEP_MANIFEST_SCHEMA_VERSION,
    STRUCTURE_WORKER_VERSION,
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core.ocsr.candidate_inputs import load_source_observation_plan
from patent_sar_extractor.core.ocsr.candidate_inventory import inventory_digest
from patent_sar_extractor.core.ocsr.candidate_observations import (
    build_candidate_plan,
    validate_candidate_observations,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import RecognitionPlan
from patent_sar_extractor.core.ocsr.smiles_converter import SmilesConverter
from patent_sar_extractor.core.ocsr.stereo_rescue_pass import eligible
from patent_sar_extractor.core.structure_inventory import inventory_packet
from patent_sar_extractor.smiles_artifact import (
    build_smiles_artifact,
    smiles_artifact_is_current,
    smiles_candidate_records,
    smiles_records,
)


class ControlledDecimer:
    def __init__(self, **kwargs):
        self.calls = []
        self.closed = False

    def runtime_identity(self):
        return {"fingerprint": "a" * 64}

    def is_available(self):
        return True

    def predict(self, image, *, timeout):
        if self.closed:
            raise RuntimeError("Primary model was used after cleanup")
        self.calls.append(image)
        return {"status": "success", "raw_smiles": "CCO", "model_fingerprint": "a" * 64}

    def close(self):
        self.closed = True


class CandidateSourceControls:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_sha = "a" * 64
        self.metadata = {
            **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
            "total_structures": 2,
            "structures": [],
            "source_inventory": inventory_packet(
                3,
                [
                    {
                        "page_no": p,
                        "status": "detected",
                        "scope": "full_page",
                        "candidates": n,
                    }
                    for p, n in ((1, 1), (2, 1), (3, 0))
                ],
            ),
        }
        for number in (1, 2):
            image = Image.new("RGB", (120, 80), "white")
            ImageDraw.Draw(image).line(
                (10, 20, 30 + number * 20, 60), fill="black", width=2
            )
            image.save(self.root / f"source-{number}.png")
            self.metadata["structures"].append(
                {
                    "structure_id": f"S{number}",
                    "page_no": number,
                    "bbox_pdf": [10, 20, 130, 100],
                    "image_path": f"source-{number}.png",
                }
            )
        self.manifest = {
            **artifact_identity(STEP_MANIFEST_SCHEMA, STEP_MANIFEST_SCHEMA_VERSION),
            "fingerprint": {
                "step": "structures",
                "pdf_sha256": self.original_sha,
                "params": {
                    "structure_pages": [0, 1, 2],
                    "structure_worker_contract_version": STRUCTURE_WORKER_VERSION,
                },
            },
        }
        self.owner = {
            **self.metadata["structures"][0],
            "cpd": "Compound 7",
            "bind_status": "bound",
            "image_path": str(self.root / "source-1.png"),
            "source_pdf_sha256": self.original_sha,
        }
        self.pdf = self.root / "original.pdf"
        with fitz.open() as document:
            for number in range(3):
                page = document.new_page(width=200, height=200)
                if number < 2:
                    page.insert_image(
                        fitz.Rect(10, 20, 130, 100),
                        filename=str(self.root / f"source-{number + 1}.png"),
                    )
            document.save(self.pdf)
        self.original_sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.manifest["fingerprint"]["pdf_sha256"] = self.original_sha
        self.owner["source_pdf_sha256"] = self.original_sha

    def plan(self, *, metadata=None, manifest=None, sources=None):
        return build_candidate_plan(
            self.metadata if metadata is None else metadata,
            self.manifest if manifest is None else manifest,
            RecognitionPlan([self.owner], [], []) if sources is None else sources,
            original_pdf_sha256=self.original_sha,
            metadata_dir=self.root,
            binding_dir=self.root,
        )

    def records(self, plan):
        def observed(item):
            path = Path(item["image_path"])
            return {
                "cpd_id": item.get("cpd", ""),
                "structure_id": item["structure_id"],
                "ocsr_source_structure_id": item.get("source_structure_id")
                or item["structure_id"],
                "page_no": item["page_no"],
                "image_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
                "ocsr_original_input": str(path),
                "OCSR_status": "success",
                "OCSR_engine": "decimer",
                "model_fingerprint": "a" * 64,
                "raw_smiles": "CCO",
                **(
                    {"candidate_source_id": item["candidate_source_id"]}
                    if "candidate_source_id" in item
                    else {}
                ),
            }

        return {
            "candidate_inventory": copy.deepcopy(plan.inventory),
            "records": [observed(self.owner)],
            "source_records": [],
            "reprint_records": [],
            "candidate_records": [observed(item) for item in plan.candidates],
        }

    def converter(self):
        engines = patch.dict(
            "patent_sar_extractor.core.ocsr.smiles_converter.ENGINE_MAP",
            {"decimer": ControlledDecimer},
        )
        engines.start()
        self.addCleanup(engines.stop)
        return SmilesConverter(
            ["decimer"],
            [],
            cache_path=str(self.root / "observations.sqlite3"),
            preprocess=False,
        )


class CandidateObservationTests(CandidateSourceControls, unittest.TestCase):
    def test_coordinator_replays_the_same_complete_plan_and_original_input(self):
        metadata = self.root / "metadata.json"
        write_json_atomic(metadata, self.metadata)
        write_json_atomic(str(metadata) + ".manifest.json", self.manifest)
        actual = load_source_observation_plan(
            RecognitionPlan([self.owner], [], []),
            structures_json=metadata,
            pdf_path=self.pdf,
            binding_dir=self.root,
            binding_pdf_sha256=self.original_sha,
        )
        self.assertEqual(actual.inventory, self.plan().inventory)
        with self.assertRaises(ValueError):
            load_source_observation_plan(
                RecognitionPlan([self.owner], [], []),
                structures_json=metadata,
                pdf_path=self.pdf,
                binding_dir=self.root,
                binding_pdf_sha256="f" * 64,
            )

    def test_artifact_roundtrip_keeps_candidate_graphs_outside_the_compound_selector(
        self,
    ):
        plan = self.plan()
        records = self.records(plan)
        artifact = build_smiles_artifact(
            records["records"],
            candidate_records=records["candidate_records"],
            candidate_inventory=plan.inventory,
        )
        self.assertTrue(
            smiles_artifact_is_current(artifact, require_all_candidates=True)
        )
        self.assertEqual(
            [r["cpd_id"] for r in smiles_records(artifact)], ["Compound 7"]
        )
        self.assertEqual(
            [r["cpd_id"] for r in smiles_candidate_records(artifact)], [""]
        )
        self.assertEqual(artifact["recognition_input_scope"], "all_detected_images")
        changed = copy.deepcopy(artifact)
        changed["candidate_records"][0]["cpd_id"] = "Compound 7"
        self.assertFalse(smiles_artifact_is_current(changed))
        with self.assertRaises(ValueError):
            build_smiles_artifact(
                records["records"], candidate_records=records["candidate_records"]
            )

    def test_a_source_only_component_artifact_does_not_claim_whole_detection_coverage(
        self,
    ):
        artifact = build_smiles_artifact([self.records_for_owner()])
        self.assertTrue(smiles_artifact_is_current(artifact))
        self.assertFalse(
            smiles_artifact_is_current(artifact, require_all_candidates=True)
        )
        self.assertEqual(artifact["recognition_input_scope"], "proved_sources_only")

    def test_saved_candidate_records_require_their_exact_source_and_model_shape(self):
        plan = self.plan()
        records = self.records(plan)
        artifact = build_smiles_artifact(
            records["records"],
            candidate_records=records["candidate_records"],
            candidate_inventory=plan.inventory,
        )
        self.assertTrue(
            smiles_artifact_is_current(artifact, require_all_candidates=True)
        )
        for field, value in (
            ("candidate_source_id", None),
            ("candidate_source_id", "f" * 64),
            ("structure_id", "another-structure"),
            ("ocsr_source_structure_id", "another-raw-source"),
            ("ocsr_source_structure_id", None),
            ("ocsr_source_structure_id", ""),
            ("page_no", 2.0),
            ("ocsr_original_input", "relative.png"),
            ("image_hash", "f" * 64),
            ("model_fingerprint", None),
            ("OCSR_engine", "molscribe"),
            ("cpd_num", 7),
            ("prefix", "Compound"),
            ("OCSR_status", "not_processed"),
            ("raw_smiles", []),
        ):
            changed = copy.deepcopy(artifact)
            changed["candidate_records"][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertFalse(
                    smiles_artifact_is_current(changed, require_all_candidates=True)
                )

    def test_saved_inventory_cannot_change_an_original_path_into_a_relative_path(self):
        plan = self.plan()
        records = self.records(plan)
        artifact = build_smiles_artifact(
            records["records"],
            candidate_records=records["candidate_records"],
            candidate_inventory=plan.inventory,
        )
        inventory = artifact["candidate_inventory"]
        inventory["entries"][0]["image_path"] = "relative.png"
        inventory["identity"] = inventory_digest(
            {key: value for key, value in inventory.items() if key != "identity"}
        )
        self.assertFalse(
            smiles_artifact_is_current(artifact, require_all_candidates=True)
        )

    def test_one_default_queue_recognizes_proved_and_unassigned_sources(self):
        plan = self.plan()
        converter = self.converter()
        results = converter.convert_batch(plan.work_items)
        self.assertEqual(len(results), 2)
        self.assertEqual([row["cpd_id"] for row in results], ["Compound 7", ""])
        self.assertEqual(
            results[1]["candidate_source_id"], plan.candidates[0]["candidate_source_id"]
        )
        payload = {
            "candidate_inventory": plan.inventory,
            "records": results[:1],
            "source_records": [],
            "reprint_records": [],
            "candidate_records": results[1:],
        }
        validate_candidate_observations(plan, payload)
        self.assertTrue(converter.engines["decimer"].closed)

    def test_a_document_without_any_number_still_has_model_observations(self):
        plan = self.plan(sources=RecognitionPlan([], [], []))
        results = self.converter().convert_batch(plan.work_items)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(row["cpd_id"] == "" for row in results))

    def test_a_forged_candidate_label_is_not_a_normal_model_input(self):
        candidate = copy.deepcopy(self.plan().candidates[0])
        candidate["cpd"] = "Compound 99"
        with self.assertRaises(ValueError):
            self.converter().convert_batch([candidate])

    def test_unassigned_candidates_cannot_consume_the_bounded_stereo_rescue(self):
        result = {
            "OCSR_engine": "decimer",
            "OCSR_status": "review_required",
            "OCSR_quality_flag": "stereochemistry_not_retained",
            "stereochemistry": {
                "status": "no_unknown_detected",
                "unknown_bond_boxes": [],
            },
        }
        self.assertTrue(eligible(result))
        self.assertFalse(eligible({**result, "candidate_source_id": "a" * 64}))

    def test_identical_raw_images_share_the_existing_model_cache_not_their_ids(self):
        self.metadata["structures"][1]["image_path"] = "source-1.png"
        plan = self.plan()
        first = self.converter()
        results = first.convert_batch(plan.work_items)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(first.engines["decimer"].calls), 1)
        self.assertEqual([r["structure_id"] for r in results], ["S1", "S2"])
        second = self.converter()
        self.assertEqual(len(second.convert_batch(plan.work_items)), 2)
        self.assertEqual(second.engines["decimer"].calls, [])

    def test_all_pages_and_candidates_are_conserved_without_repeating_an_exact_source(
        self,
    ):
        plan = self.plan()
        self.assertEqual([r["structure_id"] for r in plan.candidates], ["S2"])
        self.assertEqual(len(plan.inventory["source_inventory"]["pages"]), 3)
        self.assertEqual(
            [r["observation"] for r in plan.inventory["entries"]],
            [{"role": "formal", "index": 0}, {"role": "candidate", "index": 0}],
        )
        self.assertEqual(plan.candidates[0]["cpd"], "")
        self.assertEqual(plan.candidates[0]["bind_status"], "candidate")
        validate_candidate_observations(plan, self.records(plan))

    def test_zero_proved_identifiers_still_schedule_every_original_candidate(self):
        plan = self.plan(sources=RecognitionPlan([], [], []))
        self.assertEqual([r["structure_id"] for r in plan.candidates], ["S1", "S2"])
        self.assertTrue(all(r["cpd"] == "" for r in plan.candidates))

    def test_equal_ids_or_image_pixels_do_not_replace_different_source_geometry(self):
        for mutation in ("page", "geometry"):
            owner = copy.deepcopy(self.owner)
            if mutation == "page":
                owner["page_no"] = 2
            elif mutation == "geometry":
                owner["bbox_pdf"] = [11, 20, 130, 100]
            with self.subTest(mutation=mutation):
                plan = self.plan(sources=RecognitionPlan([owner], [], []))
                self.assertEqual(len(plan.candidates), 2)

    def test_a_proved_source_from_another_document_is_not_a_current_input(self):
        owner = {**self.owner, "source_pdf_sha256": "b" * 64}
        with self.assertRaises(ValueError):
            self.plan(sources=RecognitionPlan([owner], [], []))

    def test_foreign_producer_and_partial_page_inventories_are_rejected(self):
        for mutation in (
            "foreign",
            "missing_page",
            "partial",
            "failed_page",
            "old_worker",
        ):
            metadata, manifest = (
                copy.deepcopy(self.metadata),
                copy.deepcopy(self.manifest),
            )
            if mutation == "foreign":
                manifest["fingerprint"]["pdf_sha256"] = "b" * 64
            elif mutation == "missing_page":
                metadata["source_inventory"]["pages"].pop()
            elif mutation == "partial":
                metadata["source_inventory"]["pages"][0]["scope"] = "region"
            elif mutation == "failed_page":
                metadata["source_inventory"]["pages"][2]["status"] = "failed"
            else:
                manifest["fingerprint"]["params"][
                    "structure_worker_contract_version"
                ] = "0"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.plan(metadata=metadata, manifest=manifest)

    def test_producer_schema_version_cannot_be_a_boolean_or_float(self):
        for version in (True, 1.0, "1"):
            manifest = copy.deepcopy(self.manifest)
            manifest["schema"]["version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.plan(manifest=manifest)

    def test_a_candidate_result_cannot_acquire_a_printed_identifier(self):
        plan = self.plan()
        for field in ("cpd_id", "cpd", "compound_id"):
            records = self.records(plan)
            records["candidate_records"][0][field] = "Compound 7"
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_candidate_observations(plan, records)

    def test_missing_swapped_or_foreign_observations_cannot_be_hidden(self):
        plan = self.plan()
        for mutation in (
            "missing",
            "source",
            "crop",
            "page",
            "inventory",
            "input_path",
        ):
            records = self.records(plan)
            if mutation == "missing":
                records["candidate_records"] = []
            elif mutation == "source":
                records["candidate_records"][0]["structure_id"] = "S3"
            elif mutation == "crop":
                records["candidate_records"][0]["image_hash"] = "c" * 64
            elif mutation == "page":
                records["candidate_records"][0]["page_no"] = 1
            elif mutation == "input_path":
                records["candidate_records"][0]["ocsr_original_input"] = str(
                    self.root / "source-1.png"
                )
            else:
                records["candidate_inventory"]["entries"].pop()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_candidate_observations(plan, records)

    def test_an_unavailable_image_is_retained_as_an_unavailable_observation(self):
        self.metadata["structures"][1]["image_path"] = "missing.png"
        plan = self.plan()
        self.assertEqual(len(plan.candidates), 1)
        records = {
            "candidate_inventory": copy.deepcopy(plan.inventory),
            "records": [self.records_for_owner()],
            "source_records": [],
            "reprint_records": [],
            "candidate_records": [
                {
                    "cpd_id": "",
                    "structure_id": "S2",
                    "ocsr_source_structure_id": "S2",
                    "candidate_source_id": plan.candidates[0]["candidate_source_id"],
                    "page_no": 2,
                    "image_hash": None,
                    "ocsr_original_input": str(self.root / "missing.png"),
                    "OCSR_status": "image_missing",
                    "raw_smiles": None,
                }
            ],
        }
        validate_candidate_observations(plan, records)

    def records_for_owner(self):
        path = Path(self.owner["image_path"])
        return {
            "cpd_id": self.owner["cpd"],
            "structure_id": "S1",
            "ocsr_source_structure_id": "S1",
            "page_no": 1,
            "image_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            "ocsr_original_input": str(path),
            "OCSR_status": "success",
            "OCSR_engine": "decimer",
            "model_fingerprint": "a" * 64,
            "raw_smiles": "CCO",
        }

    def test_source_changes_after_capture_cannot_pass_as_current_observations(self):
        plan = self.plan()
        records = self.records(plan)
        Image.new("RGB", (120, 80), "black").save(self.root / "source-2.png")
        with self.assertRaises(ValueError):
            validate_candidate_observations(plan, records)
