"""Generated unruled sources must survive actual original-PDF admission."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import original_pdf_reader
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_text_capture import capture_text_page
from patent_sar_extractor.core.activity_text_sources import (
    text_line_qualified,
    text_page_qualified,
)
from patent_sar_extractor.core.page_ocr_cache import (
    build_page_ocr_cache,
    save_page_ocr_cache,
)

TEXT = "Table B. Target: JAK; Assay: binding\nNo. | IC50 (nM)\n31 | 9"


def original(path, text=TEXT, *, covered=False):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), text, fontsize=9)
        if covered:
            page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        doc.save(path)


class DeclaredTextOriginalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pdf = self.root / "original.pdf"
        original(self.pdf)
        extract(str(self.pdf), {"activity_pages": [0]}, str(self.root / "out"))
        self.data = json.loads((self.root / "out/activity_data.json").read_text())

    def check(self, path):
        return activity_evidence_errors(
            self.data, [0], open_original=original_pdf_reader(path)
        )

    def test_native_unruled_rows_retain_physical_source_and_accept_actual_original(
        self,
    ):
        self.assertEqual(self.check(self.pdf), [])
        self.assertTrue(self.data["coverage"].get("text_sources"))
        self.assertEqual(self.data["rows"][0]["activity_values"], {"IC50 (nM)": "9"})

    def test_missing_original_is_not_a_valid_text_source(self):
        self.assertTrue(activity_evidence_errors(self.data, [0]))

    def test_changed_original_value_or_condition_is_not_accepted(self):
        for text in (TEXT.replace("31 | 9", "31 | 7"), TEXT.replace("JAK", "BET")):
            path = self.root / "foreign.pdf"
            original(path, text)
            with self.subTest(text=text):
                self.assertTrue(self.check(path))

    def test_hidden_native_text_cannot_outvote_visible_original(self):
        path = self.root / "covered.pdf"
        original(path, covered=True)
        self.assertTrue(self.check(path))

    def test_saved_catalog_cannot_omit_a_physical_line_or_change_its_order(self):
        for mode in ("omit", "reverse", "remove"):
            data = json.loads(json.dumps(self.data))
            if mode == "remove":
                data["coverage"]["text_sources"] = {}
            elif mode == "omit":
                data["coverage"]["text_sources"]["1"]["lines"].pop()
            else:
                data["coverage"]["text_sources"]["1"]["lines"].reverse()
            with self.subTest(mode=mode):
                self.assertTrue(
                    activity_evidence_errors(
                        data, [0], open_original=original_pdf_reader(self.pdf)
                    )
                )

    def test_native_source_capture_and_readback_never_start_ocr(self):
        with patch(
            "patent_sar_extractor.core.activity_text_capture.get_ocr_engine",
            side_effect=AssertionError("Native text cannot load OCR"),
        ):
            extract(
                str(self.pdf), {"activity_pages": [0]}, str(self.root / "native-only")
            )
            data = json.loads(
                (self.root / "native-only/activity_data.json").read_text()
            )
            self.assertEqual(
                activity_evidence_errors(
                    data, [0], open_original=original_pdf_reader(self.pdf)
                ),
                [],
            )

    def test_display_rotation_preserves_native_original_identifier_value_and_context(
        self,
    ):
        for angle in (90, 180, 270):
            path = self.root / f"rotated-{angle}.pdf"
            with fitz.open(self.pdf) as doc:
                doc[0].set_rotation(angle)
                doc.save(path)
            with self.subTest(angle=angle):
                extract(
                    str(path), {"activity_pages": [0]}, str(self.root / f"out-{angle}")
                )
                data = json.loads(
                    (self.root / f"out-{angle}/activity_data.json").read_text()
                )
                self.assertEqual([row["cpd"] for row in data["rows"]], ["Compound 31"])
                self.assertEqual(data["rows"][0]["activity_values"], {"IC50 (nM)": "9"})
                self.assertEqual(
                    activity_evidence_errors(
                        data, [0], open_original=original_pdf_reader(path)
                    ),
                    [],
                )

    def test_new_capture_keeps_covered_native_text_as_unresolved(self):
        path = self.root / "covered-source.pdf"
        original(path, covered=True)
        extract(str(path), {"activity_pages": [0]}, str(self.root / "covered"))
        data = json.loads((self.root / "covered/activity_data.json").read_text())
        self.assertTrue(data["rows"][0]["needs_review"])
        self.assertTrue(
            activity_evidence_errors(data, [0], open_original=original_pdf_reader(path))
        )

    def test_native_proof_cannot_downgrade_its_origin_to_skip_complete_original(self):
        self.data["coverage"]["text_sources"]["1"]["origin"] = "located"
        self.assertTrue(self.check(self.pdf))

    def test_partial_capture_is_not_a_complete_text_page_after_projection(self):
        source = self.data["coverage"]["text_sources"]["1"]
        source["lines"].pop()
        from patent_sar_extractor.core.source_page_lines import observed_page_text

        self.assertFalse(text_page_qualified(source, observed_page_text(source)))

    def test_unknown_scanned_locations_cannot_be_filled_from_saved_strings(self):
        with fitz.open() as doc:
            page = doc.new_page()
            source = capture_text_page(page, TEXT, [])
            self.assertEqual(source["lines"], [])
            self.assertFalse(text_page_qualified(source, TEXT))

    def test_bad_original_header_keeps_its_continued_rows_in_review(self):
        path = self.root / "continued.pdf"
        with fitz.open() as doc:
            first = doc.new_page()
            first.insert_text((40, 60), TEXT, fontsize=9)
            first.draw_rect(first.rect, color=None, fill=(1, 1, 1))
            doc.new_page().insert_text((40, 60), "44 | 0.3", fontsize=9)
            doc.save(path)
        extract(str(path), {"activity_pages": [0]}, str(self.root / "continued"))
        data = json.loads((self.root / "continued/activity_data.json").read_text())
        self.assertEqual(
            [row["cpd"] for row in data["rows"]], ["Compound 31", "Compound 44"]
        )
        self.assertTrue(all(row["needs_review"] for row in data["rows"]))
        self.assertTrue(
            activity_evidence_errors(data, [0], open_original=original_pdf_reader(path))
        )

    def test_untrusted_catalog_shapes_never_become_qualified(self):
        source = self.data["coverage"]["text_sources"]["1"]
        for field, value in (
            ("origin", []),
            ("version", True),
            ("page_size", [True, 800]),
            ("lines", None),
        ):
            changed = {**source, field: value}
            with self.subTest(field=field):
                self.assertFalse(text_page_qualified(changed, TEXT))


class RasterDeclaredTextTests(unittest.TestCase):
    def test_actual_existing_ocr_retains_scanned_unruled_source_and_rejects_changed_pixels(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "scan.pdf"
            with fitz.open() as original_doc, fitz.open() as scanned:
                native = original_doc.new_page(width=480, height=240)
                native.insert_text((35, 45), "Table A. Binding activity", fontsize=12)
                for y, label, value in (
                    (75, "Compound ID", "IC50 (nM)"),
                    (105, "Compound 31", "9"),
                    (135, "Compound 44", "0.3"),
                ):
                    native.insert_text((35, y), label, fontsize=12)
                    native.insert_text((280, y), value, fontsize=12)
                image = native.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                scanned.new_page(width=480, height=240).insert_image(
                    native.rect, stream=image.tobytes("png")
                )
                scanned.save(pdf)
            cache_path = root / "page-cache.json"
            cache = build_page_ocr_cache(str(pdf), [0], workers=1, min_native_chars=1)
            save_page_ocr_cache(str(cache_path), cache)
            original_cache = cache_path.read_bytes()
            result = extract(
                str(pdf),
                {"activity_pages": [0], "ocr_cache_path": str(cache_path)},
                str(root / "out"),
            )
            data = json.loads((root / "out/activity_data.json").read_text())
            self.assertEqual(result["n_rows"], 2, cache["page_texts"])
            summary = [
                (
                    line["text"],
                    text_line_qualified(line),
                    [
                        (r.get("method"), r.get("text"), r.get("confidence"))
                        for r in line["observations"]
                    ],
                )
                for line in data["coverage"]["text_sources"]["1"]["lines"]
            ]
            self.assertEqual(
                activity_evidence_errors(
                    data, [0], open_original=original_pdf_reader(pdf)
                ),
                [],
                summary,
            )
            self.assertEqual(cache_path.read_bytes(), original_cache)
            for line in data["coverage"]["text_sources"]["1"]["lines"]:
                self.assertTrue(text_line_qualified(line))
                self.assertIn("nomination", line)
            self.assertTrue(data["coverage"]["text_sources"]["1"]["lines"])
            changed = root / "changed.pdf"
            with fitz.open(pdf) as doc:
                doc[0].draw_rect(doc[0].rect, color=None, fill=(1, 1, 1))
                doc.save(changed)
            self.assertTrue(
                activity_evidence_errors(
                    data, [0], open_original=original_pdf_reader(changed)
                )
            )


if __name__ == "__main__":
    unittest.main()
