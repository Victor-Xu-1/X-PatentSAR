"""Normal binder, worker-plan and safe Web replay over a synthetic catalogue."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from catalog_source_support import original_catalogue
from recognition_source_support import complete_observation_artifact

from patent_sar_extractor import contracts
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.core.ocsr.candidate_coverage import candidate_coverage_errors
from patent_sar_extractor.web.candidate_observations import read_source_observations
from patent_sar_extractor.web.files import SafeFiles
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary, primary


class AuxiliaryBindingConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="patentsar-aux-source-")
        cls.root = Path(cls.directory.name)
        cls.metadata_path = cls.root / "structures/metadata.json"
        write_json_atomic(
            cls.metadata_path,
            contracts.artifact_identity(
                contracts.STRUCTURES_SCHEMA, contracts.STRUCTURES_SCHEMA_VERSION
            ),
        )
        reader = ControlledAuxiliary(
            ("Compound 27B", "Compound 27B", "Compound 73", "Compound 73")
        )
        with (
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", primary),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=reader,
            ),
        ):
            cls.pdf, _, cls.bindings = original_catalogue(
                cls.root,
                cls.root,
                labels=("27B", "73"),
                identities=("controlled-a", "controlled-b"),
                selected=False,
                raster=True,
            )
        cls.metadata = load_json(cls.metadata_path, {})
        cls.observations = complete_observation_artifact(
            cls.bindings,
            pdf=cls.pdf,
            structures=cls.metadata_path,
            binding_dir=cls.root / "structure_bindings",
        )
        cls.sha = cls.bindings["source_reference_scope"]["original_pdf_sha256"]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_same_binder_writer_and_complete_worker_plan_keep_literal_original_ids(
        self,
    ):
        self.assertEqual(
            [b["cpd"] for b in self.bindings["compound_catalog"]["entries"]],
            ["Compound 27B", "Compound 73"],
        )
        for binding in self.bindings["compound_catalog"]["entries"]:
            observations = binding["exact_caption_evidence"]["observations"]
            self.assertEqual(sum("auxiliary_text" in o for o in observations), 2)
        self.assertEqual(
            candidate_coverage_errors(
                self.root,
                {"input_pdf": str(self.pdf)},
                self.metadata,
                self.bindings,
                self.observations,
            ),
            [],
        )

    def test_safe_web_replays_actual_original_and_never_loads_an_ocr(self):
        payloads = {
            "structures": self.metadata,
            "bindings": self.bindings,
            "smiles": self.observations,
        }
        files = SafeFiles(self.root)
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError("Read-side inference is forbidden"),
        ):
            self.assertTrue(read_source_observations(files, payloads, self.sha).errors)
            self.assertEqual(
                read_source_observations(
                    files, payloads, self.sha, open_original=lambda: fitz.open(self.pdf)
                ).errors,
                [],
            )
            changed = copy.deepcopy(self.bindings)
            for binding in changed["compound_catalog"]["entries"]:
                binding["exact_caption_evidence"]["observations"][-1]["auxiliary_text"][
                    "views"
                ][0]["requests"][0]["pixel_sha256"] = "f" * 64
            payloads["bindings"] = changed
            self.assertTrue(
                read_source_observations(
                    files, payloads, self.sha, open_original=lambda: fitz.open(self.pdf)
                ).errors
            )
