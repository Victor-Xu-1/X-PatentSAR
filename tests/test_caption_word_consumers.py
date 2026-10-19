"""Normal source plan/worker/reuse/QA/Web on a controlled original catalogue."""

import copy
import tempfile
import unittest
from pathlib import Path

import fitz
from catalog_source_support import original_catalogue
from recognition_source_support import complete_observation_artifact
from test_candidate_stage import CandidateStageControls
from test_caption_word_ownership import merged_role_hints

from patent_sar_extractor import contracts
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.core.ocsr.candidate_coverage import candidate_coverage_errors
from patent_sar_extractor.core.table_geometry import (
    detect_ruled_table_regions,
    page_tokens,
)
from patent_sar_extractor.web.candidate_observations import read_source_observations
from patent_sar_extractor.web.files import SafeFiles


class CaptionWordConsumersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="patentsar-caption-words-")
        cls.root = Path(cls.temporary.name)
        structures = cls.root / "structures/metadata.json"
        write_json_atomic(
            structures,
            contracts.artifact_identity(
                contracts.STRUCTURES_SCHEMA, contracts.STRUCTURES_SCHEMA_VERSION
            ),
        )

        def source(page, **options):
            tokens = page_tokens(page, **options)
            grid = detect_ruled_table_regions(page, dpi=240)[0]
            return merged_role_hints(tokens, grid)

        cls.pdf, cls.bind_path, cls.bindings = original_catalogue(
            cls.root,
            cls.root,
            labels=("53Q", "61R"),
            identities=("S-53", "S-61"),
            selected=False,
            raster=True,
            token_reader=source,
        )
        cls.metadata_path = structures
        cls.metadata = load_json(structures, {})
        cls.observations = complete_observation_artifact(
            cls.bindings,
            pdf=cls.pdf,
            structures=structures,
            binding_dir=cls.bind_path.parent,
        )
        cls.original_sha = cls.bindings["source_reference_scope"]["original_pdf_sha256"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_binder_writer_and_core_final_qa_keep_the_same_original_ids(self):
        self.assertEqual(
            [b["cpd"] for b in self.bindings["final_bindings"]],
            ["Compound 53Q", "Compound 61R"],
        )
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

    def test_safe_web_reader_requires_original_pdf_and_exact_word_source(self):
        files = SafeFiles(self.root)
        payloads = {
            "structures": self.metadata,
            "bindings": self.bindings,
            "smiles": self.observations,
        }
        self.assertTrue(
            read_source_observations(files, payloads, self.original_sha).errors
        )
        self.assertEqual(
            read_source_observations(
                files,
                payloads,
                self.original_sha,
                open_original=lambda: fitz.open(self.pdf),
            ).errors,
            [],
        )
        changed = copy.deepcopy(self.bindings)
        for item in [
            *changed["final_bindings"],
            *changed["compound_catalog"]["entries"],
        ]:
            proof = item["exact_caption_evidence"]["observations"][-1][
                "caption_word_form"
            ]
            proof["readings"][0]["partitions"][0]["words"][0]["pixel_sha256"] = "f" * 64
        payloads["bindings"] = changed
        self.assertTrue(
            read_source_observations(
                files,
                payloads,
                self.original_sha,
                open_original=lambda: fitz.open(self.pdf),
            ).errors
        )
        self.assertTrue(
            candidate_coverage_errors(
                self.root,
                {"input_pdf": str(self.pdf)},
                self.metadata,
                changed,
                self.observations,
            )
        )

    def test_normal_worker_reuses_observations_without_repairing_or_renumbering(self):
        self.output = self.root
        self.invocations = []
        for _ in range(2):
            state = CandidateStageControls.state(self)
            state.n_bound = 2
            CandidateStageControls.execute(self, state)
            self.assertEqual(state.scientific_errors, {})
        self.assertEqual(len(self.invocations), 1)
        self.assertTrue(state.progress.checkpoint_reused)
        output = load_json(state.smiles_json, {})
        self.assertEqual(
            [r["cpd_id"] for r in output["records"]], ["Compound 53Q", "Compound 61R"]
        )
        self.assertEqual(output["candidate_records"], [])
