"""Generic heading boundaries from supplied observations, never patent IDs/pages."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.contracts import (
    REVIEW_EXCERPT_METADATA_SCHEMA,
    REVIEW_EXCERPT_METADATA_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.core.page_classifier import classify_pdf
from patent_sar_extractor.core.review_excerpt import (
    create_review_excerpt_pdf,
    infer_candidate_page_window,
)


def cover_and_body() -> list[str]:
    return [
        "KINASE MODULATORS\nPublished:\nwith international search report (Art. 21(3))",
        "[0001] Definitions include, for example, an aryl group.",
        "BACKGROUND\nDefinitions of the substituents follow.",
        "[0042] EXAMPLES\nExample 17: Preparation of a compound; NMR.",
        "The resulting material was purified; LCMS m/z 310.2.",
        "Biological activity\nIC50 (nM) observations follow.",
        "CLAIMS\n1. A compound of formula (I).",
        "INTERNATIONAL SEARCH REPORT\nA. Classification of subject matter",
    ]


class PatentBoundaryTests(unittest.TestCase):
    def window(self, texts, **kwargs):
        return infer_candidate_page_window(texts, start_backoff_pages=0, **kwargs)

    def test_cover_isr_wording_and_prose_example_do_not_collapse_padded_window(self):
        result = infer_candidate_page_window(cover_and_body())
        self.assertEqual(result["candidate_pages"], [3, 4, 5])
        self.assertEqual(result["claim_page_idx"], 6)

    def test_prose_references_are_not_body_headings(self):
        result = self.window(
            [
                "For example, an aryl group may be selected.",
                "[0010] The Examples illustrate the invention.",
                "The Detailed Description explains the definitions.",
                "Example 4 is referenced for the general definition.",
                "Compound No. Structure\n7 NH 8 HN",
                "Assay observations follow.",
                "What is claimed is:\n1. A compound.",
            ],
            synthesis_pages=[4],
        )
        self.assertEqual(result["candidate_pages"], [4, 5])
        self.assertEqual(result["start_reason"], "first_classified_candidate_page")

    def test_normalized_numbered_and_standalone_body_headings(self):
        headings = (
            "[0042]\u00a0Example\u00a0XVII: Preparation of a compound",
            "[0042]\nExample 27\nPreparation of a compound",
            "(IV) EXAMPLES",
            "III. Experimental Section",
            "12 Detailed Description of the Invention",
            "Preparation VII: A compound",
            "实施例十二：化合物的制备",
            "[００４２] 实 施 例 ２７：制备",
            "具体实施方式",
            "合成例二：化合物的合成",
        )
        for heading in headings:
            with self.subTest(heading=heading):
                result = self.window(
                    ["Bibliographic front matter", heading, "Body", "CLAIMS"]
                )
                self.assertEqual(result["start_page_idx"], 1)
                self.assertEqual(result["start_reason"], "body_start_heading")
                self.assertEqual(result["candidate_pages"], [1, 2])

    def test_actual_claims_headings_stop_after_body(self):
        headings = (
            "C L A I M S\n1. A compound.",
            "CLAIMS\n1. A compound.",
            "Claims: 1. A compound.",
            "IV. CLAIMS\n1. A compound.",
            "[0500] What is claimed is:\n1. A compound.",
            "[0500] We claim:\n1. A compound.",
            "The following claims:\n1. A compound.",
            "权 利 要 求 书\n1. 一种化合物。",
            "权利要求\n1. 一种化合物。",
        )
        for heading in headings:
            with self.subTest(heading=heading):
                result = self.window(
                    ["EXAMPLES", "NMR and LCMS observations", heading, "Appendix"]
                )
                self.assertEqual(result["candidate_pages"], [0, 1])
                self.assertEqual(result["claim_page_idx"], 2)

    def test_actual_isr_headers_not_cover_references(self):
        for heading in (
            "INTERNATIONAL SEARCH\nREPORT\nA. Classification of subject matter",
            "INTERNATIONAL\nSEARCH\nREPORT",
            "INTERNATIONAL SEARCH REPORT\nA. Classification of subject matter",
            "I N T E R N A T I O N A L S E A R C H R E P O R T",
            "国际检索报告\n检索结果",
            "PCT / ISA / 210",
        ):
            with self.subTest(heading=heading):
                result = self.window(
                    ["Example 13: Synthesis", "Body", heading, "Annex"]
                )
                self.assertEqual(result["candidate_pages"], [0, 1])

    def test_foreign_claim_headers_with_known_layout_are_terminal(self):
        for heading in (
            "REVENDICATIONS\n1. Un composé.",
            "PATENTANSPRÜCHE\n1. Eine Verbindung.",
            "REIVINDICACIONES\n1. Un compuesto.",
            "特許請求の範囲\n請求項１",
        ):
            with self.subTest(heading=heading):
                result = self.window(["EXAMPLES", "Body", heading, "Annex"])
                self.assertEqual(result["candidate_pages"], [0, 1])

    def test_terminal_phrases_in_body_prose_do_not_cut_content(self):
        for prose in (
            "The international search report is referenced for background.",
            "Claims are discussed here, not presented as a section.",
            "[0100] The following claims may describe other embodiments.",
            "权利要求书中的术语在此定义。",
            "Form PCT/ISA/210 is referenced in this paragraph.",
            "The Examples and Preparation 4 are cross-references.",
        ):
            with self.subTest(prose=prose):
                result = self.window(
                    ["EXAMPLES", prose, "Further original body", "CLAIMS"]
                )
                self.assertEqual(result["candidate_pages"], [0, 1, 2])

    def test_real_terminal_heading_in_padding_does_not_precede_real_body(self):
        result = infer_candidate_page_window(
            [
                "INTERNATIONAL SEARCH REPORT",
                "Front page",
                "Example 8: Synthesis",
                "Body",
                "CLAIMS",
            ],
            start_backoff_pages=2,
        )
        self.assertEqual(result["end_page_idx"], 3)
        self.assertEqual(result["claim_page_idx"], 4)
        self.assertIn(2, result["candidate_pages"])

    def test_claims_after_body_on_same_page_keep_original_body_page(self):
        result = self.window(
            ["Example 8: Synthesis\nNMR data\nCLAIMS\n1. A compound.", "Annex"]
        )
        self.assertEqual(result["candidate_pages"], [0])
        self.assertEqual(result["claim_page_idx"], 0)

    def test_mixed_last_body_and_claims_page_is_not_discarded(self):
        result = self.window(
            [
                "EXAMPLES",
                "NMR: original analytical data\nCLAIMS\n1. A compound.",
                "Annex",
            ]
        )
        self.assertEqual(result["candidate_pages"], [0, 1])
        self.assertEqual(result["claim_page_idx"], 1)

    def test_flattened_or_uncertain_foreign_ocr_is_retained_not_guessed(self):
        result = self.window(
            ["EXAMPLES", "WO 2028/012345 PCT/XY2028/001234 CLAlM5 other text", "Annex"]
        )
        self.assertEqual(result["candidate_pages"], [0, 1, 2])
        self.assertIsNone(result["claim_page_idx"])

    def test_wrapped_known_title_normalization_does_not_find_prose_example(self):
        result = self.window(
            [
                "For\nexample, the substituent may be selected.",
                "Detailed\nDescription of the Invention",
                "Original body",
                "CLAIMS",
            ]
        )
        self.assertEqual(result["candidate_pages"], [1, 2])

    def test_no_body_evidence_never_truncates_unknown_document_at_terminal_words(self):
        result = self.window(["Bibliographic text", "CLAIMS", "Unknown annex"])
        self.assertEqual(result["candidate_pages"], [0, 1, 2])
        self.assertEqual(result["start_reason"], "fallback_document_start")

    def test_classified_signals_and_padding_remain_bounded_without_headings(self):
        result = infer_candidate_page_window(
            ["Front", "Front", "Body", "Table", "Continuation", "Appendix", "Appendix"],
            synthesis_pages=[-1, 3, 3, 99],
            activity_pages=[4],
            start_backoff_pages=1,
        )
        self.assertEqual(result["candidate_pages"], [2, 3, 4, 5, 6])
        self.assertEqual(
            result["end_reason"], "last_detected_candidate_page_plus_padding"
        )

    def test_empty_document_has_no_candidate_or_invented_coordinates(self):
        result = infer_candidate_page_window([])
        self.assertEqual(result["candidate_pages"], [])
        self.assertIsNone(result["start_page_idx"])
        self.assertEqual(result["end_reason"], "empty_pdf")

    def make_pdf(self, root, texts):
        pdf = root / "controlled.pdf"
        with fitz.open() as document:
            for text in texts:
                document.new_page().insert_text((40, 60), text, fontsize=9)
            document.save(pdf)
        return pdf

    def test_classifier_uses_same_boundary_without_ocr_or_model_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            texts = cover_and_body()
            pdf = self.make_pdf(root, texts)
            with patch(
                "patent_sar_extractor.core.page_classifier.update_page_ocr_cache",
                return_value={
                    "page_texts": {str(i): text for i, text in enumerate(texts)}
                },
            ) as observations:
                result = classify_pdf(str(pdf), str(root / "classification"))
            self.assertEqual(observations.call_count, 1)
            self.assertEqual(result["candidate_pages"], [3, 4, 5])
            self.assertIn(3, result["synthesis_pages"])
            self.assertIn(5, result["activity_pages"])

    def test_native_review_excerpt_keeps_layout_and_original_pdf_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = self.make_pdf(root, cover_and_body())
            before = hashlib.sha256(pdf.read_bytes()).hexdigest()
            with patch(
                "patent_sar_extractor.core.review_excerpt._load_ocr_engine",
                return_value=None,
            ):
                metadata = create_review_excerpt_pdf(str(pdf), str(root / "review.pdf"))
            self.assertEqual(
                [page["source_page_idx"] for page in metadata["pages"]], [3, 4, 5]
            )
            self.assertTrue(
                artifact_identity_matches(
                    metadata,
                    REVIEW_EXCERPT_METADATA_SCHEMA,
                    REVIEW_EXCERPT_METADATA_SCHEMA_VERSION,
                )
            )
            self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), before)
            with fitz.open(root / "review.pdf") as document:
                self.assertEqual(len(document), 3)
                self.assertIn("EXAMPLES", document[0].get_text())


if __name__ == "__main__":
    unittest.main()
