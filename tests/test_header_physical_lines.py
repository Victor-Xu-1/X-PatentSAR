"""Controlled narrow original headers, using the actual existing OCR engine."""

import copy
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.core.activity_artifacts import save_results
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_header_columns import observe_header_columns
from patent_sar_extractor.core.activity_header_evidence import (
    proof_id,
    validate_header_evidence,
)
from patent_sar_extractor.core.activity_header_identity import compact_header
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from tests.activity_source_support import original_coordinate_coverage


def scanned_headers(font="tibo", size=6, widths=(20, 39, 47, 43)):
    original = fitz.open()
    page = original.new_page()
    page.insert_text((70, 115), "Table 58. Binding activity", fontsize=8)
    xs = [70]
    for width in widths:
        xs.append(xs[-1] + width)
    ys = [135, 177, 193]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.4)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.4)
    headers = (
        ("No.",),
        ("TR-FRET", "BRD9", "IC50", "nM"),
        ("IKZF1", "NanoBiT", "DC50", "pM"),
        ("IKZF1", "NanoBiT", "Dmax", "%"),
    )
    for col, lines in enumerate(headers):
        for row, line in enumerate(lines):
            width = fitz.get_text_length(line, fontname=font, fontsize=size)
            assert width < xs[col + 1] - xs[col] - 5
            page.insert_text(
                ((xs[col] + xs[col + 1] - width) / 2, 144 + row * 8.5),
                line,
                fontname=font,
                fontsize=size,
            )
    for col, value in enumerate(("93", "0.145", "8.3", "79")):
        page.insert_text((xs[col] + 4, 187), value, fontsize=6)
    pix = page.get_pixmap(matrix=fitz.Matrix(240 / 72, 240 / 72), alpha=False)
    scanned = fitz.open()
    target = scanned.new_page()
    target.insert_image(target.rect, stream=pix.tobytes("png"))
    original.close()
    return scanned, target, {"xs": xs, "ys": ys}, headers


class HeaderPhysicalLineNativeTests(unittest.TestCase):
    def test_saved_header_replays_fields_native_claims_and_original_identity(self):
        doc, page, region, _ = scanned_headers()
        source = grid_schema(
            context_from_text("Table 58. Binding activity"),
            [["No.", "Noise", "Noise", "Noise"]],
        )
        with doc:
            observed = refine_scanned_header(page, region, source)
        proof = observed.header_resolution
        self.assertTrue(valid_header_proof(proof), proof)
        mutations = (
            lambda item: item.pop("column_contract"),
            lambda item: item["observations"][1]["matrix"][-1].__setitem__(
                2, "IC50 (nM)"
            ),
            lambda item: item["observations"][0]["columns"][1].update(
                native_text="BRD4 IC50 (nM)"
            ),
            lambda item: item["original_headers"].__setitem__(
                1, "TR-FRET BRD4 IC50 (nM)"
            ),
            lambda item: item["observations"][0]["columns"].pop(),
            lambda item: item.update(original_context="Table 59. Binding activity"),
        )
        for mutate in mutations:
            changed = copy.deepcopy(proof)
            mutate(changed)
            payload = {
                "schema": schema_ref(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
                "header_observations": {proof_id(changed): changed},
            }
            with (
                self.subTest(mutate=mutate),
                self.assertRaisesRegex(ValueError, "header column"),
            ):
                validate_header_evidence(payload)

    def test_real_coordinate_writer_and_qa_keep_narrow_source_fields(self):
        for hybrid in (False, True):
            doc, page, _region, _headers = scanned_headers()
            if hybrid:
                page.insert_text((40, 805), "Original appendix", fontsize=10)
            with doc, self.subTest(hybrid=hybrid):
                original_bytes = doc.tobytes()
                result = extract_coordinate_tables(doc, [0])
                packet = original_coordinate_coverage(doc, [0], result)
            self.assertEqual(len(result.rows), 1, result.coverage)
            row = result.rows[0]
            self.assertEqual(row.cpd, "Compound 93")
            self.assertEqual(
                row.activity_values,
                {
                    "TR-FRET BRD9 IC50 (nM)": "0.145",
                    "IKZF1 NanoBiT DC50 (pM)": "8.3",
                    "IKZF1 NanoBiT Dmax (%)": "79",
                },
            )
            self.assertFalse(row.needs_review, row)
            with tempfile.TemporaryDirectory() as root:
                save_results(
                    result.rows,
                    Path(root),
                    {},
                    coverage=packet,
                    header_observations=result.header_observations,
                )
                payload = load_json(Path(root) / "activity_data.json", {})
            self.assertIn(
                "Original PDF is required for activity text replay.",
                activity_evidence_errors(payload, [0]),
            )
            self.assertEqual(
                activity_evidence_errors(
                    payload,
                    [0],
                    open_original=lambda source=original_bytes: fitz.open(
                        stream=source, filetype="pdf"
                    ),
                ),
                [],
            )

    def test_narrow_serif_and_sans_headers_preserve_all_original_lines(self):
        for font, size, widths in (
            ("tibo", 6, (20, 39, 47, 43)),
            ("tiro", 6.2, (23, 42, 45, 46)),
            ("hebo", 5.8, (25, 44, 48, 45)),
        ):
            doc, page, region, headers = scanned_headers(font, size, widths)
            with doc:
                for dpi in (400, 600):
                    with self.subTest(font=font, dpi=dpi):
                        observed = observe_header_columns(page, region, 1, dpi)
                        self.assertEqual(
                            tuple(map(compact_header, observed.matrix[0])),
                            tuple(
                                compact_header("\n".join(lines)) for lines in headers
                            ),
                            observed.columns,
                        )
                        self.assertTrue(all(observed.verified), observed.columns)
                        for index, column in enumerate(observed.columns):
                            self.assertNotIn("0.145", column["raw_text"])
                            if len(headers[index]) > 1:
                                self.assertEqual(
                                    [part["text"] for part in column["parts"]],
                                    list(headers[index]),
                                )
                                self.assertTrue(
                                    all(
                                        part.get("method") == "physical_header_line"
                                        for part in column["parts"]
                                    )
                                )


if __name__ == "__main__":
    unittest.main()
