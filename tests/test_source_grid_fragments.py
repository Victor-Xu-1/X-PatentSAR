"""Independent original open-row controls; never actual patent computation."""

import copy
import unittest
from unittest.mock import patch

import fitz
from test_activity_spatial_roles import ruled
from test_heading_characterization_roles import characterization_page

from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.source_fragment_links import resolved_fragments
from patent_sar_extractor.core.source_grid_edges import edge_intervals
from patent_sar_extractor.core.source_role_fragments import (
    fragment_texts,
    validate_fragments,
)


def split_row(
    *,
    gap=False,
    caption="Table 17. Continued",
    shift=0,
    conflicting_id=False,
    missing_column=False,
    extra_title=False,
    tail_end=650,
    right_kind="Compound",
    show_right_id=True,
):
    doc = fitz.open()
    first = characterization_page(doc)
    for x in (40, 530) if missing_column else (40, 140, 315, 530):
        first.draw_line((x, 250), (x, tail_end))
    first.insert_text((48, 270), "Compound 105", fontsize=9)
    first.insert_text((148, 270), "Prepared in analogy to\nCompound 118", fontsize=9)
    first.insert_text((325, 270), "1H NMR (400 MHz) 7.3 ppm", fontsize=9)
    if extra_title:
        first.insert_text((40, 680), "Compound 63: Preparation", fontsize=9)
    if gap:
        doc.new_page(width=560, height=700)
    page = doc.new_page(width=560, height=700)
    page.insert_text((40, 30), caption, fontsize=9)
    xs = [x + shift for x in (40, 140, 315, 530)]
    ruled(
        page,
        xs,
        [125, 155, 220, 285],
        [
            [f"{right_kind} No.", "Preparation", "Characterization"],
            [
                f"{right_kind} 211",
                "Prepared in analogy to Compound 213",
                "1H NMR (400 MHz) 7.5 ppm; MS m/z 470.1",
            ],
            [
                f"{right_kind} 212",
                "Prepared in analogy to Compound 214",
                "1H NMR (400 MHz) 7.6 ppm; MS m/z 484.1",
            ],
        ],
    )
    for x in xs:
        page.draw_line((x, 50), (x, 125))
    if conflicting_id:
        page.insert_text((xs[0] + 8, 75), "Compound 106", fontsize=9)
    elif right_kind != "Compound" and show_right_id:
        page.insert_text((xs[0] + 8, 75), f"{right_kind} 105", fontsize=9)
    page.insert_text((xs[2] + 8, 75), "MS (ESI) m/z 441.1", fontsize=9)
    return doc


def observe(doc):
    sections = []
    blocks = observed_heading_blocks(
        doc, list(range(len(doc))), {}, source_sections=sections
    )
    payload = {
        "source_sections": sections,
        "source_reference_scope": reference_scope(sections),
        "source_issues": [],
    }
    regions = [
        s["source_region"] for s in sections if s["role"] == "characterization_region"
    ]
    return blocks, payload, regions


def scanned_split_row():
    native = split_row()
    scanned = fitz.open()
    try:
        for original in native:
            raster = original.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            )
            page = scanned.new_page(width=560, height=700)
            page.insert_image(page.rect, stream=raster)
            page.insert_text((40, 690), "WO2026000011", fontsize=8)
    finally:
        native.close()
    return scanned


class SourceGridFragmentTests(unittest.TestCase):
    def test_unqualified_native_open_row_is_replayed_but_not_promoted(self):
        from patent_sar_extractor.core.role_original_replay import (
            original_role_source_errors,
        )
        from patent_sar_extractor.core.source_cell_claims import cell_source_status

        with split_row() as doc:
            # A real non-rule stroke inside the open cell prevents a positive
            # text-only claim even if the printed words themselves are readable.
            doc[0].draw_line((75, 300), (95, 320))
            _blocks, _payload, regions = observe(doc)
            region = regions[0]
            fragment = region["row_fragments"][0]
            reading = fragment["source_cells"]["observations"][0]["cells"][0]
            self.assertIn("native_window", reading)
            self.assertEqual(cell_source_status(reading), "unqualified")
            validate_fragments(region)
            self.assertIsNone(fragment_texts(region, fragment, 0))
            self.assertEqual(original_role_source_errors(doc, [(1, reading)]), [])
            changed = copy.deepcopy(reading)
            changed["native_window"]["paints"][0]["seqno"] += 1
            self.assertTrue(original_role_source_errors(doc, [(1, changed)]))

    def test_native_open_row_role_is_bound_to_actual_original_grid_and_paints(self):
        from patent_sar_extractor.core.role_original_replay import (
            original_role_source_errors,
        )
        from patent_sar_extractor.core.role_text_sources import role_text_cells

        with split_row() as doc:
            _blocks, payload, regions = observe(doc)
            self.assertEqual(len(resolved_fragments(regions)), 2)
            sources = [
                item
                for item in role_text_cells(payload)
                if item[1].get("method") == "original_open_native_cell"
            ]
            self.assertTrue(sources)
            self.assertEqual(original_role_source_errors(doc, sources), [])
            forged = copy.deepcopy(sources)
            forged[0][1]["grid_edges"]["rule_frame"]["pixel_sha256"] = "0" * 64
            self.assertTrue(original_role_source_errors(doc, forged))
            doc[0].draw_line((75, 300), (95, 320))
            self.assertTrue(original_role_source_errors(doc, sources))

    def test_same_number_with_changed_terminal_intermediate_role_never_links(self):
        for repeat in (True, False):
            with (
                self.subTest(repeat=repeat),
                split_row(right_kind="Intermediate", show_right_id=repeat) as doc,
            ):
                _, payload, regions = observe(doc)
                self.assertEqual(resolved_fragments(regions), set())
                self.assertTrue(
                    any(
                        issue["reason"] == "unresolved_original_open_row"
                        for issue in reference_issues(payload, [])
                    )
                )

    def test_shared_native_view_is_not_counted_twice_against_one_context_row(self):
        with split_row(tail_end=350) as doc:
            doc[0].insert_text((40, 375), "X " * 300, fontsize=1)
            _, _, regions = observe(doc)
        chunks = regions[0]["fragment_context"]["suffix"]
        self.assertEqual(
            sum(len(s["tokens"]) for chunk in chunks for s in chunk["sources"]), 300
        )

    def test_actual_binding_writer_keeps_partial_products_and_replays_open_rows(self):
        import tempfile
        from pathlib import Path

        from patent_sar_extractor.artifact_io import load_json
        from patent_sar_extractor.core.structure_binder import bind
        from tests import test_binding_modules as controls

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, metadata, profile = controls.BindingModuleTests().pdf_fixture(
                root, extra_caption=True
            )
            with fitz.open(pdf) as source, split_row() as extra:
                source.insert_pdf(extra, from_page=0, to_page=0)
                source.saveIncr()
            result = bind(str(pdf), profile, str(root / "binding"), str(metadata))
            self.assertEqual(result["bound"], 3)
            self.assertIn(
                "Compound 105", [issue["cpd"] for issue in result["source_issues"]]
            )
            self.assertNotIn(
                "Compound 118", [issue["cpd"] for issue in result["source_issues"]]
            )
            saved = load_json(root / "binding/bindings.json", {})
            saved["source_issues"] = []
            placeholders = [{"cpd": f"Compound {n}"} for n in (73, 84, 105)]
            with self.assertRaisesRegex(ValueError, "label-role reference ownership"):
                reference_issues(saved, placeholders)
            # Retain the actual caption owners; added synthetic ID placeholders
            # still cannot repair an unresolved original open-row continuation.
            entries = [*saved["compound_catalog"]["entries"], *placeholders]
            self.assertTrue(
                any(
                    issue["reason"] == "unresolved_original_open_row"
                    for issue in reference_issues(saved, entries)
                )
            )

    def test_native_empty_cell_with_vector_ink_is_not_a_proved_blank(self):
        with split_row() as doc:
            page = doc[-1]
            page.draw_polyline([(50, 65), (80, 65), (65, 90), (80, 90)])
            with (
                patch(
                    "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
                    side_effect=RuntimeError(
                        "controlled original ink needs the existing OCR"
                    ),
                ),
                self.assertRaisesRegex(RuntimeError, "original ink"),
            ):
                observe(doc)

    def test_complete_boundary_context_is_chunked_without_silent_cutoff(self):
        with split_row(tail_end=350) as doc:
            page = doc[0]
            for row in range(60):
                page.insert_text((40, 365 + row * 5), "WO2026000011 " * 12, fontsize=3)
            _, _, regions = observe(doc)
        region = regions[0]
        chunks = region["fragment_context"]["suffix"]
        self.assertGreater(len(chunks), 1)
        self.assertEqual(
            sum(
                len(source["tokens"]) for chunk in chunks for source in chunk["sources"]
            ),
            720,
        )
        validate_fragments(region)
        changed = copy.deepcopy(region)
        changed["fragment_context"]["suffix"].pop()
        with self.assertRaisesRegex(ValueError, "context.*coverage"):
            validate_fragments(changed)

    def test_two_equally_compatible_next_sources_are_not_chosen_by_order(self):
        with split_row() as doc:
            _, _, regions = observe(doc)
        duplicate = copy.deepcopy(regions[1])
        duplicate["region_id"] = "b" * 64
        self.assertEqual(resolved_fragments([*regions, duplicate]), set())

    def test_original_page_edge_keeps_visible_tail_inside_the_pdf(self):
        with split_row(tail_end=700) as doc:
            _, _, regions = observe(doc)
        bottom = regions[0]["row_fragments"][0]
        self.assertLessEqual(bottom["bbox"][3], 700)

    def test_real_raster_blank_continuation_cells_and_frames_remain_auditable(self):
        with scanned_split_row() as doc:
            _, payload, regions = observe(doc)
        self.assertEqual(len(resolved_fragments(regions)), 2)
        entries = [{"cpd": f"Compound {n}"} for n in (73, 84, 105, 211, 212)]
        self.assertEqual(reference_issues(payload, entries), [])
        for region in regions:
            validate_fragments(region)
            self.assertEqual(
                len(region["row_fragments"][0]["source_cells"]["rendered_frames"]), 2
            )
        for change in ("frame", "score", "raw_limit"):
            changed = copy.deepcopy(regions[0])
            source = changed["row_fragments"][0]["source_cells"]
            if change == "frame":
                source["rendered_frames"][0][0]["shape"][0] += 200
            elif change == "score":
                source["observations"][0]["cells"][0]["confidence"] = True
            else:
                source["observations"][0]["cells"][0]["raw_text"] = "x" * 4097
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_fragments(changed)

    def test_open_scan_cell_uses_replayable_original_rule_strips_only(self):
        from patent_sar_extractor.core.cell_raster import (
            original_reading_image,
            valid_source_window,
        )
        from patent_sar_extractor.core.open_cell_raster import render_open_cell_raster
        from patent_sar_extractor.core.source_grid_edges import original_grid_edges
        from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions

        with scanned_split_row() as doc:
            page = doc[0]
            grids = detect_ruled_table_regions(page, dpi=240)
            self.assertEqual(len(grids), 1)
            edges = original_grid_edges(page, grids[0])
            fragment = next(
                item for item in edge_intervals(edges) if item["edge"] == "bottom"
            )
            xs, box = edges["xs"], fragment["bbox"]
            bounds = [xs[0], box[1], xs[1], box[3]]
            raster = render_open_cell_raster(page, bounds, 400, edges, fragment, 0)
            self.assertIsNotNone(raster)
            self.assertEqual(raster.source_window["version"], 2)
            self.assertEqual(raster.source_window["frame_strips"][-1], 0)
            reading = {
                "source_window": raster.source_window,
                "source_frame": raster.frame,
            }
            self.assertTrue(
                (
                    original_reading_image(page, bounds, 400, reading) == raster.image
                ).all()
            )
            for mutate in ("bounds", "missing_open_edge", "foreign_grid", "hash"):
                changed = copy.deepcopy(reading)
                window = changed["source_window"]
                if mutate == "bounds":
                    window["read_bounds"][0] += 1
                elif mutate == "missing_open_edge":
                    window["frame_strips"][-1] = 1
                elif mutate == "foreign_grid":
                    window["open_grid"]["column"] = 1
                else:
                    window["source_pixel_sha256"] = "invalid"
                with self.subTest(mutate=mutate):
                    self.assertFalse(
                        valid_source_window(
                            window, bounds, 400, changed["source_frame"]["shape"]
                        )
                    )
                    with self.assertRaises(ValueError):
                        original_reading_image(page, bounds, 400, changed)
            forged = copy.deepcopy(reading)
            forged["source_window"]["open_grid"]["grid_edges"]["rule_frame"][
                "pixel_sha256"
            ] = "0" * 64
            with self.assertRaises(ValueError):
                original_reading_image(page, bounds, 400, forged)
            page.draw_line((75, box[1] + 30), (75, box[1] + 60))
            with self.assertRaises(ValueError):
                original_reading_image(page, bounds, 400, reading)

    def test_open_rule_view_never_crops_connected_or_unproved_ink(self):
        import numpy as np

        from patent_sar_extractor.core.open_cell_raster import open_rule_window

        pixels = np.full((300, 400, 3), 255, dtype=np.uint8)
        pixels[0:2, :, :] = 0
        pixels[:, 0:2, :] = 0
        pixels[:, -2:, :] = 0
        pixels[30:40, 60:90, :] = 0
        self.assertIsNotNone(open_rule_window(pixels, 400, "bottom"))
        connected = pixels.copy()
        connected[0:35, 65:67, :] = 0
        self.assertIsNone(open_rule_window(connected, 400, "bottom"))
        no_rule = pixels.copy()
        no_rule[:, -2:, :] = 255
        self.assertIsNone(open_rule_window(no_rule, 400, "bottom"))
        for invalid_dpi, invalid_edge in (
            (True, "bottom"),
            (300, "bottom"),
            (400, "left"),
        ):
            with (
                self.subTest(dpi=invalid_dpi, edge=invalid_edge),
                self.assertRaises(ValueError),
            ):
                open_rule_window(pixels, invalid_dpi, invalid_edge)

    def test_known_measurement_in_an_open_fragment_cannot_borrow_a_synthesis_role(self):
        with split_row() as doc:
            doc[0].insert_text((325, 310), "DC50 2 nM", fontsize=9)
            _, _, regions = observe(doc)
        region = regions[0]
        fragment = region["row_fragments"][0]
        validate_fragments(region)
        self.assertIsNone(fragment_texts(region, fragment, 0))
        self.assertIsNone(fragment_texts(region, fragment, 1))
        self.assertEqual(resolved_fragments([region, regions[1]]), set())

    def test_real_native_adjacent_fragments_keep_literal_ids_and_prove_one_row(self):
        with split_row() as doc:
            blocks, payload, regions = observe(doc)
        self.assertEqual(blocks, [])
        self.assertEqual(len(resolved_fragments(regions)), 2)
        entries = [{"cpd": f"Compound {number}"} for number in (73, 84, 105, 211, 212)]
        self.assertEqual(reference_issues(payload, entries), [])
        identifiers = [
            s["identifier"]
            for s in payload["source_sections"]
            if s["role"] == "characterization_identifier"
        ]
        self.assertIn("105", identifiers)
        self.assertNotIn("118", identifiers)
        self.assertNotIn("", identifiers)

    def test_gap_new_table_shift_conflicting_id_or_prose_prevent_row_completion(self):
        for options in (
            {"gap": True},
            {"caption": "Table 19. Continued"},
            {"shift": 8},
            {"conflicting_id": True},
            {"extra_title": True},
            {"extra_title": True, "tail_end": 350},
            {"missing_column": True},
        ):
            with self.subTest(options=options), split_row(**options) as doc:
                blocks, payload, regions = observe(doc)
                self.assertEqual(resolved_fragments(regions), set())
                issues = reference_issues(payload, [])
                self.assertTrue(
                    any(i["reason"] == "unresolved_original_open_row" for i in issues)
                )
                if options.get("extra_title"):
                    self.assertIn("Compound 63", [b["cpd"] for b in blocks])
                if options.get("missing_column"):
                    self.assertIn("Compound 118", [b["cpd"] for b in blocks])

    def test_rehashed_removed_fragments_cannot_turn_into_complete_saved_source(self):
        with split_row() as doc:
            _, payload, _ = observe(doc)
        changed = copy.deepcopy(payload)
        region = next(
            s["source_region"]
            for s in changed["source_sections"]
            if s["role"] == "characterization_region"
        )
        region["row_fragments"] = []
        # Recompute every public hash: raw physical-edge replay must still reject.
        from patent_sar_extractor.core.activity_header_evidence import proof_id

        prior = region["region_id"]
        region["region_id"] = proof_id(
            {k: v for k, v in region.items() if k != "region_id"}
        )
        for section in changed["source_sections"]:
            if section.get("source_region") == prior:
                section["source_region"] = region["region_id"]
        changed["source_reference_scope"] = reference_scope(changed["source_sections"])
        with self.assertRaisesRegex(ValueError, "open-row inventory"):
            reference_issues(changed, [])

    def test_edge_inventory_rejects_boolean_nonfinite_and_unbounded_geometry(self):
        packet = {
            "version": 1,
            "page_size": [560, 700],
            "xs": [40, 140, 315, 530],
            "ys": [90, 120, 250],
            "vertical_rules": [[x, 90, 650] for x in (40, 140, 315, 530)],
            "rule_frame": {"dpi": 240, "shape": [2334, 1867], "pixel_sha256": "a" * 64},
        }
        self.assertEqual(edge_intervals(packet)[0]["bbox"], [40, 250, 530, 650])
        for change in ("boolean", "nan", "outside", "many"):
            changed = copy.deepcopy(packet)
            if change == "boolean":
                changed["vertical_rules"][0][0] = True
            elif change == "nan":
                changed["xs"][1] = float("nan")
            elif change == "outside":
                changed["vertical_rules"][0][2] = 701
            else:
                changed["vertical_rules"] *= 129
            with self.subTest(change=change), self.assertRaises(ValueError):
                edge_intervals(changed)
