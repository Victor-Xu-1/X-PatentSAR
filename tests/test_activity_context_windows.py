"""Physical table ownership independent of printed caption availability."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.contracts import CHARACTERIZATION_ROLE_SCHEMA_VERSION
from patent_sar_extractor.core.activity_auxiliary_replay import original_pdf_reader
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import coverage_errors, coverage_packet
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_grid_roles import characterization_roles
from patent_sar_extractor.core.activity_header_evidence import proof_id
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_header_sources import (
    capture_header_sources,
    header_source_conflicts,
)
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.binding_source_regions import (
    identifier_references,
    reference_regions,
)
from patent_sar_extractor.core.cell_header_proof import physical_header_valid
from patent_sar_extractor.core.sar.contexts import compare_context
from patent_sar_extractor.core.source_cell_tokens import cell_text
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.web.artifacts import _activities
from patent_sar_extractor.web.sar.observation_contexts import ObservationContexts
from tests.header_support import observed_headers
from tests.test_activity_spatial_roles import ruled


def token(text, x, y, *, native=False, confidence=0.99):
    return {
        "text": text,
        "x": x,
        "y": y,
        "bbox": [x - 15, y - 4, x + 15, y + 4],
        "confidence": 1.0 if native else confidence,
        "source": "native" if native else "raster",
        "geometry_space": "rendered",
    }


def draw_grid(page, top, rows, *, xs=None):
    xs = xs or [40, 155, 335]
    ys = [top + 30 * i for i in range(len(rows) + 1)]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.5)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.5)
    for row, texts in enumerate(rows):
        for column, text in enumerate(texts):
            page.insert_text((xs[column] + 5, ys[row] + 19), text, fontsize=9)


def unnamed_page(doc):
    page = doc.new_page(width=500, height=600)
    draw_grid(page, 375, [["Compound No.", "IC50 (nM)"], ["47", "12.4"]])
    return page


def parallel_activity_page(
    doc,
    *,
    intro="",
    unknown_header=False,
    second_header=False,
    second_title=None,
    paragraph_caption=False,
    panel_assays=None,
    panel_ids=None,
    panel_cells=None,
):
    """One original header for parallel panels, not repeated synthetic headers."""
    page = doc.new_page(width=760, height=420)
    page.insert_text((40, 35), "WO2028/008765 PCT/EP2028/009876", fontsize=9)
    if intro:
        page.insert_text((40, 100), intro, fontsize=9)
    page.insert_text(
        (40, 130),
        ("[0042] " if paragraph_caption else "") + "Table 71. Binding activity",
        fontsize=9,
    )
    if second_title:
        page.insert_text((270, 130), second_title, fontsize=9)
    identifiers = [
        ("41", "89"),
        ("7E", "8E") if second_header else ("7E", "8E", "73C"),
        ("104D", "201", "305"),
    ]
    if panel_ids is not None:
        identifiers = panel_ids
    for panel, labels in enumerate(identifiers):
        left = 40 + 230 * panel
        xs = [left, left + 75, left + 150, left + 210]
        ys = [160, 190, 220, 250]
        if panel_assays and panel_assays[panel]:
            condition = f"Assay: {panel_assays[panel]}"
            if panel_cells and panel_cells[panel]:
                condition += f"; {panel_cells[panel]} cells"
            page.insert_text((left + 3, 149), condition, fontsize=9)
        rows = [[label, str(index + 1), "82"] for index, label in enumerate(labels)]
        if panel == 0 or panel == 1 and second_header:
            rows.insert(
                0,
                [
                    "Compound No.",
                    "Unknown score" if unknown_header else "IC50 (nM)",
                    "Dmax (%)",
                ],
            )
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]), width=0.5)
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y), width=0.5)
        for row, cells in enumerate(rows):
            for column, text in enumerate(cells):
                page.insert_text((xs[column] + 3, ys[row] + 18), text, fontsize=9)
    return identifiers


class ActivityContextWindowTests(unittest.TestCase):
    def test_unread_ink_fragment_cannot_become_an_observed_blank(self):
        import numpy as np

        from patent_sar_extractor.core.cell_text_chunks import observe_text_cell
        from patent_sar_extractor.core.source_role_fragments import fragment_texts

        bounds = [0, 0, 21, 20.4]
        for ink in (False, True):
            engine = Mock()
            readings = [
                observe_text_cell(
                    np.full(
                        (round(18 * dpi / 72), round(18 * dpi / 72), 3),
                        0 if ink else 255,
                        dtype=np.uint8,
                    ),
                    dpi,
                    engine,
                ).evidence(dpi, bounds)
                for dpi in (400, 600)
            ]
            fragment = {
                "status": "observed_columns",
                "source_cells": {
                    "xs": [0, 21],
                    "ys": [0, 20.4],
                    "native_hints": [[""]],
                    "observations": [
                        {"matrix": [[""]], "cells": [reading]} for reading in readings
                    ],
                },
            }
            with self.subTest(ink=ink):
                self.assertEqual(
                    fragment_texts(
                        {
                            "role_scope": {
                                "version": CHARACTERIZATION_ROLE_SCHEMA_VERSION,
                                "roles": {"columns": ["nmr"]},
                            }
                        },
                        fragment,
                        0,
                    ),
                    None if ink else ["", ""],
                )
            engine.assert_not_called()

    def long_raster_characterization(self, count):
        from patent_sar_extractor.core.activity_grid_role_observation import (
            observe_characterization,
        )
        from patent_sar_extractor.core.table_geometry import (
            detect_ruled_table_regions,
            page_tokens,
        )

        spectrum = "\n".join(
            ["1H NMR (400 MHz)"]
            + [f"{7 - index * 0.1:.2f} (m, 2H)" for index in range(count - 2)]
            + ["MS (ESI) m/z 413.1"]
        )
        with fitz.open() as native, fitz.open() as raster:
            source = native.new_page(width=600, height=650)
            source.insert_text(
                (40, 70), "Table 17. Compound characterization", fontsize=9
            )
            ruled(
                source,
                [40, 140, 360, 560],
                [90, 120, 600],
                [
                    ["Compound No.", "Preparation", "Characterization"],
                    ["Compound 73", "Prepared in analogy to Compound 91", ""],
                ],
            )
            self.assertGreaterEqual(
                source.insert_textbox(
                    fitz.Rect(364, 124, 556, 597), spectrum, fontsize=7
                ),
                0,
            )
            pixels = source.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = raster.new_page(width=600, height=650)
            page.insert_image(page.rect, stream=pixels.tobytes("png"))
            tokens = page_tokens(page, dpi=240, allow_tesseract=False)
            grid = detect_ruled_table_regions(page, dpi=240)[0]
            proof = observe_characterization(
                page, grid, tokens, "Table 17. Compound characterization"
            )
        self.assertIsNotNone(proof)
        return proof

    def test_single_line_final_chunk_remains_part_of_the_complete_original(self):
        from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope

        proof = self.long_raster_characterization(33)
        self.assertTrue(
            valid_role_scope(
                {
                    "bbox": [
                        proof["xs"][0],
                        proof["ys"][0],
                        proof["xs"][-1],
                        proof["ys"][-1],
                    ],
                    "role_scope": proof,
                }
            )
        )
        for observation in proof["observations"]:
            packet = observation["cells"][-1]["physical_text_chunks"]
            self.assertEqual(
                [len(chunk["row_bounds"]) for chunk in packet["chunks"]], [32, 1]
            )

    def test_long_raster_characterization_conserves_all_original_text_chunks(self):
        from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope

        proof = self.long_raster_characterization(40)
        record = {
            "bbox": [proof["xs"][0], proof["ys"][0], proof["xs"][-1], proof["ys"][-1]],
            "role_scope": proof,
        }
        self.assertTrue(valid_role_scope(record))
        from patent_sar_extractor.core.cell_frame_proof import valid_cell_frame
        from patent_sar_extractor.core.source_role_fragments import fragment_texts

        for observation in proof["observations"]:
            cell = observation["cells"][-1]
            packet = cell["physical_text_chunks"]
            self.assertEqual(len(packet["row_bounds"]), 40)
            self.assertEqual(
                [len(chunk["row_bounds"]) for chunk in packet["chunks"]], [32, 8]
            )
            self.assertTrue(
                valid_cell_frame(
                    {
                        "dpi": cell["render_dpi"],
                        "shape": packet["image_shape"],
                        "pixel_sha256": packet["pixel_sha256"],
                    },
                    cell,
                    cell["bbox"],
                    cell["render_dpi"],
                )
            )
        fragment = {
            "status": "observed_columns",
            "source_cells": {
                "xs": proof["xs"],
                "ys": proof["ys"][1:],
                "native_hints": [proof["native_hints"][1]],
                "observations": [
                    {
                        "method": item["method"],
                        "matrix": [item["matrix"][1]],
                        "cells": item["cells"][3:],
                    }
                    for item in proof["observations"]
                ],
            },
        }
        self.assertEqual(
            fragment_texts({"role_scope": proof}, fragment, 2),
            [item["matrix"][1][2] for item in proof["observations"]],
        )
        for change in (
            "missing",
            "reordered",
            "weak",
            "nested_endpoint",
            "foreign_fields",
        ):
            altered = copy.deepcopy(record)
            packet = altered["role_scope"]["observations"][0]["cells"][-1][
                "physical_text_chunks"
            ]
            if change == "missing":
                packet["chunks"].pop()
            elif change == "reordered":
                packet["chunks"].reverse()
            elif change == "weak":
                packet["chunks"][-1]["reading"]["confidence"] = 0.84
            elif change == "nested_endpoint":
                packet["chunks"][0]["reading"]["detection_parts"] = [
                    {"text": "IC50 (nM)", "confidence": 0.99, "bbox": None}
                ]
            else:
                packet["chunks"][0]["reading"]["role_scope"] = {}
            with self.subTest(change=change):
                self.assertFalse(valid_role_scope(altered))

    def test_rejected_characterization_is_saved_without_becoming_a_result(self):
        from patent_sar_extractor.core.binding_artifacts import write_binding_result
        from patent_sar_extractor.core.source_role_observations import (
            validate_role_catalog,
        )

        rejected = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with fitz.open() as document:
                page = document.new_page(width=600, height=400)
                page.insert_text(
                    (40, 70), "Table 17. Compound characterization", fontsize=9
                )
                ruled(
                    page,
                    [40, 160, 340, 560],
                    [90, 120, 200],
                    [
                        ["Compound No.", "Preparation", "Characterization"],
                        [
                            "73",
                            "Unknown original method",
                            "1H NMR (400 MHz); MS (ESI) m/z 413.1",
                        ],
                    ],
                )
                document.save(root / "source.pdf")
                source_sha = hashlib.sha256(
                    (root / "source.pdf").read_bytes()
                ).hexdigest()
                self.assertEqual(
                    reference_regions(
                        page, original_pdf_sha256=source_sha, evidence_sink=rejected
                    ),
                    [],
                )
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0]["reason"], "unresolved_column_roles")
            self.assertEqual(
                rejected[0]["source_cells"]["observations"][0]["matrix"][1][1],
                "Unknown original method",
            )
            extract(
                str(root / "source.pdf"),
                {"activity_pages": [0]},
                str(root / "activity"),
            )
            activity = load_json(root / "activity/activity_data.json", {})
            self.assertEqual(activity["rows"], [])
            self.assertTrue(activity["source_role_observations"])
            validate_role_catalog(activity["source_role_observations"])
            self.assertTrue(activity_evidence_errors(activity, [0]))
            write_binding_result(
                root / "binding",
                patent_id="controlled-source-roles",
                bindings=[],
                detected_style="original_cell_caption_heading",
                include_intermediates=False,
                total_structures=0,
                total_compound_blocks=0,
                table_pages=[],
                table_covered_count=0,
                no_binding=[],
                unbound_pages=[],
                original_pdf_sha256=source_sha,
                role_observations=rejected,
            )
            binding = load_json(root / "binding/bindings.json", {})
            self.assertEqual(binding["compound_catalog"]["entries"], [])
            self.assertEqual(len(binding["source_role_observations"]), 1)
            validate_role_catalog(
                binding["source_role_observations"], original_pdf_sha256=source_sha
            )

    def test_later_cell_budget_refusal_keeps_the_completed_original_read(self):
        from patent_sar_extractor.core.activity_grid_role_observation import (
            observe_role_cells,
        )

        original = []
        engine = Mock()
        with (
            fitz.open() as document,
            patch(
                "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
        ):
            page = document.new_page(width=600, height=600)
            result = observe_role_cells(
                page, {"xs": [0, 500], "ys": [0, 500]}, [], evidence_sink=original
            )
        self.assertIsNone(result)
        self.assertEqual(len(original), 1)
        self.assertEqual(
            [item["method"] for item in original[0]["observations"]],
            ["cell_ocr_400dpi"],
        )
        self.assertEqual(len(original[0]["observations"][0]["cells"]), 1)
        self.assertEqual(original[0]["observations"][0]["cells"][0]["confidence"], 0.0)
        engine.assert_not_called()  # Blank-cell fault fixture, not OCR acceptance.

    def test_text_row_budget_is_role_scoped_and_never_truncates_the_pixel_inventory(
        self,
    ):
        import numpy as np

        from patent_sar_extractor.core.cell_header_lines import header_line_frame

        for rows in (12, 32, 33):
            image = np.full((rows * 20 + 20, 160, 3), 255, dtype=np.uint8)
            for row in range(rows):
                image[10 + row * 20 : 14 + row * 20, 30:120] = 0
            header = header_line_frame(image, 8, 400)
            self.assertEqual(header["row_bounds"], [])
            body = header_line_frame(image, 8, 400, maximum_rows=32)
            self.assertEqual(len(body["row_bounds"]), rows if rows <= 32 else 0)
            self.assertEqual(body["status"], "unresolved")  # No OCR proof yet.
        with self.assertRaisesRegex(ValueError, "line frame"):
            header_line_frame(image, 8, 400, maximum_rows=True)

    def test_dense_raster_characterization_keeps_every_line_and_primary_id(self):
        from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
        from patent_sar_extractor.core.table_geometry import (
            detect_ruled_table_regions,
            page_tokens,
        )

        spectrum = "\n".join(
            ["1H NMR (400 MHz)"]
            + [f"{7 - index * 0.1:.2f} (m, 2H)" for index in range(10)]
            + ["MS (ESI) m/z 413.1"]
        )
        with fitz.open() as native, fitz.open() as raster:
            source = native.new_page(width=600, height=500)
            source.insert_text(
                (40, 70), "Table 17. Compound characterization", fontsize=9
            )
            ruled(
                source,
                [40, 140, 320, 560],
                [90, 120, 380],
                [
                    ["Compound No.", "Preparation", "Characterization"],
                    ["Compound 73", "Prepared in analogy to Compound 91", spectrum],
                ],
            )
            pixels = source.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = raster.new_page(width=600, height=500)
            page.insert_image(page.rect, stream=pixels.tobytes("png"))
            tokens = page_tokens(page, dpi=240, allow_tesseract=False)
            grids = detect_ruled_table_regions(page, dpi=240)
            regions = reference_regions(
                page, original_pdf_sha256="a" * 64, grids=grids, tokens=tokens
            )
        self.assertEqual(len(regions), 1)
        record = regions[0]
        self.assertTrue(valid_role_scope(record))
        self.assertEqual(
            [item["identifier"] for item in identifier_references(record)], ["73"]
        )
        observations = record["role_scope"]["observations"]
        self.assertEqual(
            [item["method"] for item in observations],
            ["cell_ocr_400dpi", "cell_ocr_600dpi"],
        )
        for observed in observations:
            cell = observed["cells"][-1]
            self.assertEqual(len(cell["physical_header_lines"]["row_bounds"]), 12)
            self.assertEqual(len(cell["parts"]), 12)
            self.assertGreaterEqual(cell["confidence"], 0.85)
            self.assertFalse(
                physical_header_valid(cell)
            )  # Actual headers still cap at8.
        for change in ("missing_line", "weak_line", "endpoint"):
            altered = copy.deepcopy(record)
            observation = altered["role_scope"]["observations"][0]
            cell = observation["cells"][-1]
            if change == "missing_line":
                cell["parts"].pop()
            elif change == "weak_line":
                cell["parts"][0]["confidence"] = 0.84
            else:
                cell["text"] += "; IC50 = 5 nM"
                observation["matrix"][-1][-1] = cell["text"]
            with self.subTest(change=change):
                self.assertFalse(valid_role_scope(altered))

    def test_declared_reference_list_needs_every_actual_result_table_and_row_proof(
        self,
    ):
        for include_second in (True, False):
            with self.subTest(include_second=include_second), fitz.open() as document:
                method = document.new_page(width=500, height=400)
                method.insert_text(
                    (40, 60),
                    "Example 87: Binding assay\nCells were seeded. Reagent was added.\n"
                    "Results are included in\nTables 71 and 88.",
                    fontsize=10,
                )
                for table in (71, 88) if include_second else (71,):
                    page = document.new_page(width=500, height=400)
                    page.insert_text(
                        (40, 80), f"Table {table}. Binding activity", fontsize=9
                    )
                    draw_grid(
                        page, 100, [["Compound No.", "IC50 (nM)"], ["47", "12.4"]]
                    )
                pages = list(range(len(document)))
                parsed = extract_coordinate_tables(document, pages)
                packet = coverage_packet(pages, parsed.coverage, parsed.rows)
                references = packet["references"]
                self.assertEqual(
                    {ref["table_id"] for ref in references}, {"Table 71", "Table 88"}
                )
                errors = coverage_errors(packet, pages, rows=parsed.rows)
                if include_second:
                    self.assertEqual(errors, [])
                    self.assertTrue(
                        all(ref["status"] == "resolved" for ref in references)
                    )
                else:
                    self.assertTrue(errors)
                    self.assertTrue(
                        any(ref["status"] != "resolved" for ref in references)
                    )

    def test_parallel_panels_keep_the_original_header_past_running_ids_and_references(
        self,
    ):
        for intro in ("", "Results are reported in Table 71."):
            with self.subTest(intro=intro), fitz.open() as document:
                identifiers = parallel_activity_page(document, intro=intro)
                parsed = extract_coordinate_tables(document, [0])
                self.assertEqual(
                    {row.cpd for row in parsed.rows},
                    {f"Compound {label}" for panel in identifiers for label in panel},
                )
                self.assertFalse(any(row.needs_review for row in parsed.rows))
                headers = {
                    (
                        source["header_region"]["page_no"],
                        tuple(source["header_region"]["bbox"]),
                    )
                    for row in parsed.rows
                    for source in row.activity_sources
                }
                self.assertEqual(len(headers), 1)
                packet = coverage_packet([0], parsed.coverage, parsed.rows)
                self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])
                altered = copy.deepcopy(packet)
                continued = next(
                    region
                    for region in altered["regions"]
                    if region.get("layout") and region["layout"]["data_start"] == 0
                )
                continued["layout"]["boundary_prefix"] += "\nAssay: different protocol"
                with self.assertRaisesRegex(ValueError, "boundary differs"):
                    coverage_errors(altered, [0], rows=parsed.rows)

    def test_parallel_panel_does_not_inherit_unknown_original_header_fields(self):
        with fitz.open() as document:
            identifiers = parallel_activity_page(document, unknown_header=True)
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual(
            {row.cpd for row in parsed.rows},
            {f"Compound {label}" for label in identifiers[0]},
        )
        self.assertTrue(all(row.needs_review for row in parsed.rows))
        self.assertTrue(
            any(region["status"] == "unresolved" for region in parsed.coverage)
        )

    def test_independent_original_captions_do_not_merge_or_lend_a_far_header(self):
        with fitz.open() as document:
            identifiers = parallel_activity_page(
                document, second_header=True, second_title="Table 71. Binding activity"
            )
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual(
            {row.cpd for row in parsed.rows},
            {f"Compound {label}" for panel in identifiers[:2] for label in panel},
        )
        origins = {
            tuple(source["header_region"]["bbox"])
            for row in parsed.rows
            for source in row.activity_sources
        }
        self.assertEqual(len(origins), 2)

    def test_paragraph_locator_does_not_hide_the_one_shared_original_caption(self):
        with fitz.open() as document:
            identifiers = parallel_activity_page(document, paragraph_caption=True)
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual(
            {row.cpd for row in parsed.rows},
            {f"Compound {label}" for panel in identifiers for label in panel},
        )

    def test_saved_shared_panel_context_cannot_be_omitted_or_drop_other_original_words(
        self,
    ):
        with fitz.open() as document:
            parallel_activity_page(document)
            parsed = extract_coordinate_tables(document, [0])
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])
        for change in ("missing_scope", "dropped_word"):
            with self.subTest(change=change):
                altered = copy.deepcopy(packet)
                child = next(
                    record
                    for record in altered["regions"]
                    if record.get("layout") and record["layout"]["data_start"] == 0
                )
                layout = child["layout"]
                if change == "missing_scope":
                    del layout["parallel_context"]
                else:
                    scope = layout["parallel_context"]
                    primary = scope["prefix"]
                    primary["tokens"].pop(0)
                    primary["text"] = cell_text(primary["tokens"], primary["bbox"])
                    scope["native_prefix"] = copy.deepcopy(primary)
                self.assertTrue(coverage_errors(altered, [0], rows=parsed.rows))

    def test_new_assay_section_before_a_continued_title_cannot_borrow_the_old_header(
        self,
    ):
        with fitz.open() as document:
            first = document.new_page(width=500, height=400)
            first.insert_text((40, 80), "Table 71. Binding activity", fontsize=9)
            draw_grid(first, 100, [["Compound No.", "IC50 (nM)"], ["47", "12.4"]])
            second = document.new_page(width=500, height=400)
            second.insert_text(
                (40, 40), "Example 6. Binding assay in BET cells", fontsize=9
            )
            second.insert_text((40, 75), "Table 71. Continued", fontsize=9)
            draw_grid(second, 100, [["48", "1.3"]])
            parsed = extract_coordinate_tables(document, [0, 1])
        self.assertEqual([row.cpd for row in parsed.rows], ["Compound 47"])
        self.assertTrue(
            any(record["status"] == "unresolved" for record in parsed.coverage)
        )

    def test_real_raster_parallel_panels_use_the_same_full_source_contract(self):
        with fitz.open() as drawing, fitz.open() as document:
            identifiers = parallel_activity_page(
                drawing, intro="Results are reported in Table 71."
            )
            original = drawing[0]
            page = document.new_page(
                width=original.rect.width, height=original.rect.height
            )
            page.insert_image(
                page.rect,
                stream=original.get_pixmap(
                    matrix=fitz.Matrix(3, 3), alpha=False
                ).tobytes("png"),
            )
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual(
            {row.cpd for row in parsed.rows},
            {f"Compound {label}" for panel in identifiers for label in panel},
        )
        self.assertFalse(any(row.needs_review for row in parsed.rows))
        self.assertEqual(
            coverage_errors(
                coverage_packet([0], parsed.coverage, parsed.rows),
                [0],
                rows=parsed.rows,
            ),
            [],
        )

    def test_shared_column_header_keeps_each_panels_explicit_assay_context(self):
        assays = ("alpha", "beta", "gamma")
        with fitz.open() as document:
            identifiers = parallel_activity_page(document, panel_assays=assays)
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual(
            {row.cpd for row in parsed.rows},
            {f"Compound {label}" for panel in identifiers for label in panel},
        )
        for index, panel in enumerate(identifiers):
            for label in panel:
                row = next(row for row in parsed.rows if row.cpd == f"Compound {label}")
                self.assertEqual(row.activity_sources[0]["assay"], assays[index])
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])

    def test_formal_writer_retains_repeated_compounds_in_distinct_parallel_assays(self):
        assays = ("alpha", "beta", "gamma")
        cells = ("A1", "B2", "C3")
        labels = [("41", "89"), ("41", "89", "73C"), ("41", "89", "305")]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with fitz.open() as document:
                parallel_activity_page(
                    document, panel_assays=assays, panel_ids=labels, panel_cells=cells
                )
                document.save(root / "source.pdf")
            extract(
                str(root / "source.pdf"),
                {"activity_pages": [0]},
                str(root / "activity"),
            )
            payload = load_json(root / "activity/activity_data.json", None)
            sha256 = hashlib.sha256((root / "source.pdf").read_bytes()).hexdigest()
            current = ObservationContexts(
                {
                    "run_root": str(root),
                    "sha256": sha256,
                    "expected_sha256": sha256,
                    "page_count": 1,
                }
            )
            self.assertTrue(current.exact)
            for assay, cell_line in zip(assays, cells):
                original_row = next(
                    row
                    for row in payload["rows"]
                    if row["cpd"] == "Compound 41"
                    and row["activity_sources"][0]["assay"] == assay
                )
                activity = next(
                    value
                    for value in _activities(
                        original_row, page_count=1, document_sha256=sha256
                    )
                    if value.name == "IC50 (nM)"
                )
                conditions = current.contexts(
                    "Compound 41",
                    activity,
                )
                self.assertEqual(len(conditions), 1)
                self.assertEqual(conditions[0]["assay"], assay)
                self.assertEqual(conditions[0]["cell_line"], cell_line)
            self.assertEqual(
                activity_evidence_errors(
                    payload, [0], open_original=original_pdf_reader(root / "source.pdf")
                ),
                [],
            )
        for label in ("41", "89"):
            rows = [row for row in payload["rows"] if row["cpd"] == f"Compound {label}"]
            self.assertEqual(len(rows), 3)
            self.assertEqual(
                {source["assay"] for row in rows for source in row["activity_sources"]},
                set(assays),
            )

    def test_adjacent_page_keeps_the_proved_parent_panels_context_not_the_left_root(
        self,
    ):
        with fitz.open() as document:
            parallel_activity_page(
                document,
                panel_assays=("alpha", "beta", "gamma"),
                panel_cells=("A1", "B2", "C3"),
            )
            next_page = document.new_page(width=760, height=420)
            next_page.insert_text((270, 75), "Table 71. Continued", fontsize=9)
            draw_grid(
                next_page,
                100,
                [["306", "3", "81"], ["307", "4", "82"]],
                xs=[270, 345, 420, 480],
            )
            parsed = extract_coordinate_tables(document, [0, 1])
        current = [row for row in parsed.rows if row.page_no == 2]
        self.assertEqual({row.cpd for row in current}, {"Compound 306", "Compound 307"})
        for row in current:
            self.assertEqual(row.activity_sources[0]["assay"], "beta")
            self.assertEqual(row.activity_sources[0]["cell_line"], "B2")
        self.assertEqual(
            coverage_errors(
                coverage_packet([0, 1], parsed.coverage, parsed.rows),
                [0, 1],
                rows=parsed.rows,
            ),
            [],
        )

    def test_declared_spectral_role_cannot_exclude_activity_or_unknown_columns(self):
        matrix = [["Compound No.", "Characterization"], ["99", "1H NMR (400 MHz)"]]
        self.assertEqual(
            characterization_roles(matrix, "Table 17. Compound characterization"),
            {"data_start": 1, "columns": ["identifier", "nmr"]},
        )
        self.assertIsNone(
            characterization_roles(matrix, "Table 17. NMR binding activity")
        )
        extra = [row + [value] for row, value in zip(matrix, ["Unknown", "0.5"])]
        self.assertIsNone(
            characterization_roles(extra, "Table 17. Compound characterization")
        )
        measured = [["Compound No.", "IC50 (nM)"], ["99", "12.4"]]
        self.assertIsNone(
            characterization_roles(measured, "Table 17. Compound characterization")
        )

    def test_anonymous_source_does_not_complete_missing_sar_conditions(self):
        basis, reasons, conflict = compare_context(
            [
                {
                    "value": "12.4",
                    "unit": "nM",
                    "context": {"target": None, "assay": None},
                }
            ],
            ordinal=False,
            confirmed=False,
        )
        self.assertEqual(basis, "insufficient")
        self.assertIn("context_incomplete", reasons)
        self.assertFalse(conflict)

    def test_real_hybrid_tables_keep_their_own_caption_and_source_inventory(self):
        with fitz.open() as drawing, fitz.open() as document:
            image_page = drawing.new_page(width=500, height=200)
            image_page.insert_text((40, 15), "Table 88. Binding activity", fontsize=9)
            draw_grid(image_page, 35, [["Compound No.", "IC50 (nM)"], ["47", "12.4"]])
            pixels = image_page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = document.new_page(width=500, height=600)
            page.insert_text(
                (40, 80), "Table 17. Compound characterization", fontsize=9
            )
            draw_grid(
                page,
                100,
                [["Compound No.", "Characterization"], ["99", "1H NMR (400 MHz)"]],
            )
            page.insert_image(fitz.Rect(0, 340, 500, 540), stream=pixels.tobytes("png"))
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual([row.cpd for row in parsed.rows], ["Compound 47"])
        self.assertEqual(parsed.rows[0].table_id, "Table 88")
        self.assertFalse(parsed.rows[0].needs_review)
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])
        altered = copy.deepcopy(packet)
        earlier = next(
            record
            for record in altered["regions"]
            if record["status"] == "non_activity"
        )
        del earlier["grid_axes"]
        with self.assertRaisesRegex(ValueError, "physical grid inventory"):
            coverage_errors(altered, [0], rows=parsed.rows)

    def test_known_caption_is_retained_when_both_short_rereads_are_unnamed(self):
        region = {"xs": [40, 160, 300], "ys": [375, 400, 425]}
        parts = [
            token("Table 71. Binding activity", 50, 80),
            token("No.", 90, 385),
            token("IC50 (nM)", 230, 385),
        ]
        observed = SourceTokens(
            parts, SourceLayout((), (0, 0, 500, 600)), (0, 0, 500, 600)
        )
        source = grid_schema(
            context_from_text("Table 71. Binding activity"), [["No.", "IC50 (nM)"]]
        )
        page = Mock(rect=fitz.Rect(0, 0, 500, 600))
        page.get_text.return_value = []
        with (
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.observe_header_columns",
                side_effect=lambda page, region, limit, dpi, tokens: observed_headers(
                    [["No.", "IC50 (nM)"]], region, limit, dpi
                ),
            ),
        ):
            selected = refine_scanned_header(page, region, source, tokens=observed)
        self.assertEqual(selected.context.table_id, "Table 71")
        self.assertEqual(
            selected.header_resolution["status"], "observed_header_consensus"
        )
        self.assertTrue(valid_header_proof(selected.header_resolution))
        erased = copy.deepcopy(selected.header_resolution)
        erased["resolved_context"] = ""
        self.assertFalse(valid_header_proof(erased))
        erased = copy.deepcopy(selected.header_resolution)
        erased["column_contract"] = 2
        self.assertFalse(valid_header_proof(erased))

    def test_unnamed_dose_groups_do_not_become_numbered_compounds(self):
        with fitz.open() as doc:
            page = doc.new_page(width=500, height=600)
            draw_grid(
                page, 375, [["Dose (nM)", "Response (%)"], ["1", "20"], ["10", "50"]]
            )
            parsed = extract_coordinate_tables(doc, [0])
        self.assertEqual(parsed.rows, [])
        self.assertTrue(
            any(record["status"] == "unresolved" for record in parsed.coverage)
        )

    def raster_artifact(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with fitz.open() as native, fitz.open() as raster:
            original = unnamed_page(native)
            pixels = original.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = raster.new_page(width=500, height=600)
            page.insert_image(page.rect, stream=pixels.tobytes("png"))
            raster.save(root / "original.pdf")
        extract(
            str(root / "original.pdf"),
            {"activity_pages": [0]},
            str(root / "output"),
        )
        self.raster_original = original_pdf_reader(root / "original.pdf")
        return load_json(root / "output/activity_data.json", None)

    def test_saved_anonymous_header_cannot_invent_a_context_blocker(self):
        original = self.raster_artifact()
        self.assertEqual(
            activity_evidence_errors(original, [0], open_original=self.raster_original),
            [],
        )
        changed = copy.deepcopy(original)
        key, proof = next(iter(changed["header_observations"].items()))
        proof["original_source"]["context_geometry"]["tables"].append(
            [40, 300, 335, 350]
        )
        replacement = proof_id(proof)
        changed["header_observations"] = {replacement: proof}
        for row in changed["rows"]:
            for source in row["activity_sources"]:
                if source.get("header_resolution", {}).get("evidence_ref") == key:
                    source["header_resolution"]["evidence_ref"] = replacement
        with self.assertRaisesRegex(ValueError, "physical grid inventory"):
            activity_evidence_errors(changed, [0], open_original=self.raster_original)

    def header_sources(self, *, current_native=False, weak_caption=False):
        region = {"xs": [40, 160, 300], "ys": [375, 400, 425]}
        older = token("Table 17. Characterization", 50, 80, native=True)
        parts = [
            older,
            token(
                "Table 88. Binding activity",
                50,
                350,
                confidence=0.2 if weak_caption else 0.99,
            ),
            token("No.", 90, 385),
            token("IC50 (nM)", 230, 385),
        ]
        native = [older]
        if current_native:
            native.append(token("Table 99. Different assay", 50, 350, native=True))
            parts.append(native[-1])
        observed = SourceTokens(
            parts,
            SourceLayout(tuple(native), (35, 340, 320, 460)),
            (35, 340, 320, 460),
        )
        snapshot = capture_header_sources(
            Mock(rect=fitz.Rect(0, 0, 500, 600)), region, 1, observed
        )
        schema = grid_schema(
            context_from_text("Table 88. Binding activity"), [["No.", "IC50 (nM)"]]
        )
        return snapshot, schema

    def test_earlier_native_caption_is_not_a_current_raster_table_conflict(self):
        snapshot, schema = self.header_sources()
        checked = header_source_conflicts(
            snapshot,
            [40, 375, 300, 400],
            list(schema.raw_headers),
            schema.context.raw_context,
            schema,
        )
        self.assertEqual(checked, ([False, False], False))

    def test_same_window_native_conflict_and_weak_new_boundary_still_veto(self):
        for options in ({"current_native": True}, {"weak_caption": True}):
            snapshot, schema = self.header_sources(**options)
            with self.subTest(options=options):
                checked = header_source_conflicts(
                    snapshot,
                    [40, 375, 300, 400],
                    list(schema.raw_headers),
                    schema.context.raw_context,
                    schema,
                )
                self.assertTrue(checked[1])

    def test_native_unnamed_grid_keeps_original_physical_identity(self):
        with fitz.open() as doc:
            unnamed_page(doc)
            parsed = extract_coordinate_tables(doc, [0])
        self.assertEqual([row.cpd for row in parsed.rows], ["Compound 47"])
        self.assertEqual(parsed.rows[0].table_id, "")
        self.assertIsNone(parsed.rows[0].activity_sources[0]["target"])
        self.assertEqual(
            coverage_errors(
                coverage_packet([0], parsed.coverage, parsed.rows),
                [0],
                rows=parsed.rows,
            ),
            [],
        )

    def test_raster_unnamed_grid_has_the_same_source_contract_not_a_fake_title(self):
        with fitz.open() as native, fitz.open() as raster:
            original = unnamed_page(native)
            pixels = original.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            page = raster.new_page(width=500, height=600)
            page.insert_image(page.rect, stream=pixels.tobytes("png"))
            parsed = extract_coordinate_tables(raster, [0])
        self.assertEqual([row.cpd for row in parsed.rows], ["Compound 47"])
        self.assertEqual(parsed.rows[0].table_id, "")
        self.assertFalse(parsed.rows[0].needs_review)
        self.assertEqual(
            coverage_errors(
                coverage_packet([0], parsed.coverage, parsed.rows),
                [0],
                rows=parsed.rows,
            ),
            [],
        )

    def test_new_unnamed_grid_cannot_borrow_context_across_an_earlier_grid(self):
        with fitz.open() as doc:
            page = unnamed_page(doc)
            page.insert_text(
                (40, 80), "Table 17. Target: OLD; Assay: characterization", fontsize=9
            )
            draw_grid(
                page,
                100,
                [["Compound No.", "Characterization"], ["99", "1H NMR (400 MHz)"]],
            )
            parsed = extract_coordinate_tables(doc, [0])
        row = next(row for row in parsed.rows if row.cpd == "Compound 47")
        self.assertEqual(row.table_id, "")
        self.assertIsNone(row.activity_sources[0]["target"])
        self.assertIsNone(row.activity_sources[0]["assay"])


if __name__ == "__main__":
    unittest.main()
