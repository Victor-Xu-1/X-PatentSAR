"""Physical table ownership independent of printed caption availability."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.artifact_io import load_json
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
from patent_sar_extractor.core.sar.contexts import compare_context
from patent_sar_extractor.core.source_cell_tokens import cell_text
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.web.models import Activity
from patent_sar_extractor.web.sar.observation_contexts import ObservationContexts
from tests.header_support import observed_headers


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
                conditions = current.contexts(
                    "Compound 41",
                    Activity(
                        name="IC50 (nM)", value="1", unit="nM", page=1, assay=assay
                    ),
                )
                self.assertEqual(len(conditions), 1)
                self.assertEqual(conditions[0]["assay"], assay)
                self.assertEqual(conditions[0]["cell_line"], cell_line)
        self.assertEqual(activity_evidence_errors(payload, [0]), [])
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
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
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
            return load_json(root / "output/activity_data.json", None)

    def test_saved_anonymous_header_cannot_invent_a_context_blocker(self):
        original = self.raster_artifact()
        self.assertEqual(activity_evidence_errors(original, [0]), [])
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
            activity_evidence_errors(changed, [0])

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
