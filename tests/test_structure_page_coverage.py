"""Regression coverage for structure pages independent of activity membership."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import build_page_ocr_cache
from patent_sar_extractor.core.structure_page_locator import locate_structure_pages


class StructurePageCoverageTests(unittest.TestCase):
    def locate(self, texts: list[str], classification: dict, active: list[str]):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "controlled.pdf"
            with fitz.open() as document:
                for text in texts:
                    document.new_page().insert_text((50, 60), text, fontsize=8)
                document.save(pdf)
            cache = root / "page_ocr_cache.json"
            write_json_atomic(
                cache,
                {
                    "page_texts": {str(page): text for page, text in enumerate(texts)},
                    "ocr_line_map": {
                        str(page): [{"text": text, "y0": 100, "y1": 120}]
                        for page, text in enumerate(texts)
                    },
                },
            )
            with patch(
                "patent_sar_extractor.core.structure_page_locator.build_page_ocr_cache"
            ) as build:
                result = locate_structure_pages(
                    str(pdf),
                    {**classification, "page_count": len(texts)},
                    active,
                    ocr_cache_path=str(cache),
                )
            build.assert_not_called()
            return result

    def test_zero_activity_keeps_numbered_synthesis_and_structure_tables(self):
        result = self.locate(
            [
                "Example 101. Preparation of Compound 101. MS m/z 450.2; NMR.",
                "Cmpd No. Structure 201. HN 202. NH",
                "Compound No. IC50 (nM)\n101 20\n201 40",
            ],
            {
                "synthesis_pages": [0],
                "candidate_pages": [0, 1, 2],
                "activity_pages": [2],
            },
            [],
        )
        self.assertEqual(result["selected_pages"], [0, 1])
        self.assertEqual(result["unmatched_cpds"], [])
        self.assertEqual(result["crop_regions"], {})

    def test_active_subset_does_not_hide_other_numbered_structures(self):
        result = self.locate(
            [
                "Example 1. Synthesis of Compound 1; NMR.",
                "Background and summary of the invention.",
                "Example 42. Preparation of Compound 42; LCMS m/z 532.1.",
                "Compound No. IC50 (nM)\n1 5\n42 30",
                "Cmpd No. Structure 90. HN 91. NH",
            ],
            {
                "synthesis_pages": [0, 2],
                "candidate_pages": [0, 1, 2, 3, 4],
                "activity_pages": [3],
            },
            ["Compound 1"],
        )
        self.assertEqual(result["selected_pages"], [0, 2, 4])
        self.assertEqual(result["matched_cpds"], {"Compound 1": [0]})
        self.assertEqual(result["crop_regions"], {})
        self.assertEqual(set(result["ocr_text_map"]), {"0", "2", "4"})

    def test_small_disjoint_tables_survive_primary_active_catalog_selection(self):
        result = self.locate(
            [
                "Cmpd No. Structure 91. HN 92. NH",
                "Background information.",
                "Cmpd No. Structure 1. HN 2. NH 3. O 4. N 5. NH 6. HN",
            ],
            {"synthesis_pages": [2], "candidate_pages": [2]},
            [f"Compound {number}" for number in range(1, 7)],
        )
        self.assertEqual(result["selected_pages"], [0, 2])
        self.assertEqual(result["structure_table_pages"], [2])
        self.assertEqual(result["structure_table_coverage_count"], 6)

    def test_structure_evidence_is_not_vetoed_by_activity_page_class(self):
        result = self.locate(
            ["Cmpd No. Structure IC50 (nM) 9. HN 10. NH"],
            {"synthesis_pages": [0], "candidate_pages": [0], "activity_pages": [0]},
            [],
        )
        self.assertEqual(result["selected_pages"], [0])

    def test_generic_formula_and_assay_prose_do_not_trigger_a_whole_pool_scan(self):
        result = self.locate(
            [
                "A compound of formula (I) with variable R groups is claimed.",
                "Test Example 1. Compound 1 IC50 was measured with 1 mg of buffer.",
                "Compound No. IC50 EC50\n1 10 20\n2 30 40",
            ],
            {
                "synthesis_pages": [0, 1],
                "candidate_pages": [0, 1, 2],
                "activity_pages": [1, 2],
            },
            ["Compound 1"],
        )
        self.assertEqual(result["selected_pages"], [])
        self.assertEqual(result["unmatched_cpds"], ["Compound 1"])

    def test_cached_numbered_tables_are_found_when_classification_pool_is_empty(self):
        result = self.locate(
            ["Cmpd No. Structure 11. HN 12. NH"],
            {"synthesis_pages": [], "candidate_pages": []},
            [],
        )
        self.assertEqual(result["selected_pages"], [0])

    def test_formula_prose_with_claim_numbers_and_atom_words_is_not_a_table(self):
        result = self.locate(
            [
                "A compound of Formula I. 1. H and N, C1-C6 alkyl. 2. OH and S.",
                "CLAIMS 1. A compound of Formula I: H N O. 2. The compound of claim 1.",
                "Prodrugs have structures in which a compound is modified. 1. H 2. N.",
                "Cmpd No. Structure 1. HN 2. NH",
            ],
            {"candidate_pages": [0, 1, 2, 3]},
            [],
        )
        self.assertEqual(result["selected_pages"], [3])

    def test_only_evidenced_synthesis_continuations_are_expanded(self):
        result = self.locate(
            [
                "Example 1. Preparation of Compound 1; MS m/z 350.1.",
                "The resulting material was purified. NMR: 7.4; yield 30%.",
                "What is claimed: a compound of formula (I).",
            ],
            {"synthesis_pages": [0, 1, 2], "candidate_pages": [0, 1, 2]},
            [],
        )
        self.assertEqual(result["selected_pages"], [0, 1])

    def test_numbered_captions_with_atom_labels_are_kept_without_activity(self):
        result = self.locate(
            ["Compound 8A\nHN O N Cl", "Compound 8A has an IC50 of 15 nM."],
            {"candidate_pages": [0, 1], "activity_pages": [1]},
            [],
        )
        self.assertEqual(result["selected_pages"], [0])

    def test_plain_numeric_lists_are_not_numbered_structure_evidence(self):
        result = self.locate(
            [
                "\n".join(
                    f"{number} a bibliographic reference" for number in range(1, 10)
                )
            ],
            {"candidate_pages": [0]},
            [],
        )
        self.assertEqual(result["selected_pages"], [])

    def test_headerless_numbered_structure_cells_continue_the_catalog(self):
        result = self.locate(
            [
                "Cmpd No. Structure 1. HN 2. NH",
                "3. HN 4. NH",
                "References and bibliography.",
            ],
            {"candidate_pages": [0, 1, 2]},
            [],
        )
        self.assertEqual(result["selected_pages"], [0, 1])
        self.assertEqual(
            result["structure_page_evidence"]["1"], "structure_table_continuation"
        )

    def test_missing_ocr_reads_union_of_classified_pools_once_using_native_pdf(self):
        texts = [
            "Example 1. Preparation of Compound 1 was completed. NMR and LCMS data.",
            "Example 8. Preparation of Compound 8 was completed. NMR and LCMS data.",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "native.pdf"
            with fitz.open() as document:
                for text in texts:
                    document.new_page().insert_text((50, 60), text, fontsize=8)
                document.save(pdf)
            with (
                patch(
                    "patent_sar_extractor.core.structure_page_locator.build_page_ocr_cache",
                    wraps=build_page_ocr_cache,
                ) as build,
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=AssertionError(
                        "native PDF must not start an OCR model"
                    ),
                ),
            ):
                result = locate_structure_pages(
                    str(pdf),
                    {"synthesis_pages": [0], "candidate_pages": [1], "page_count": 2},
                    [],
                )
            self.assertEqual(build.call_count, 1)
            self.assertEqual(build.call_args.args[1], [0, 1])
            self.assertEqual(result["selected_pages"], [0, 1])


if __name__ == "__main__":
    unittest.main()
