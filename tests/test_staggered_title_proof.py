"""Original body/source witnesses are mandatory, not semantic exclusion flags."""

import copy
import cProfile
import json
import unittest
from itertools import cycle
from time import perf_counter
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import title_ink_geometry
from patent_sar_extractor.core.binding_source_references import reference_scope
from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.role_original_replay import original_role_source_errors
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.source_paint_paths import original_path_owners
from patent_sar_extractor.core.source_paint_visibility import native_paint_view
from patent_sar_extractor.core.structure_declaration_proof import declaration_issues
from patent_sar_extractor.core.structure_declaration_scopes import (
    validate_declaration_page,
)
from patent_sar_extractor.core.structure_declarations import observe_declaration_pages
from patent_sar_extractor.core.title_source_inventory import (
    title_source_cells,
    validate_title_page_inventory,
)
from tests import test_caption_role_writer as caption_writer_controls
from tests.parallel_catalogue_support import (
    TITLES,
    ParallelCatalogueControls,
    original_parallel_catalogues,
    title_reader,
)
from tests.staggered_catalogue_support import (
    prior_original_table,
    staggered_catalogues,
    wrapped_staggered_catalogues,
)


class StaggeredTitleProofTests(ParallelCatalogueControls, unittest.TestCase):
    def test_current_reader_cannot_downgrade_the_complete_declaration_inventory(self):
        document, structures, boxes, _ = wrapped_staggered_catalogues()
        payload, records = (
            caption_writer_controls.CaptionRoleWriterTests.execute_document(
                self, document, structures, boxes
            )
        )
        self.assertEqual(len(read_catalog_entries(payload)[0]), 2)
        changed = copy.deepcopy(payload)
        for page in changed["source_sections"]:
            if page["role"] != "structure_declaration_page":
                continue
            page["source"]["version"] = 1
            page["source"].pop("catalogue_scopes")
            page["region_id"] = proof_id(page["source"])
            # The old representation remains a readable historical source,
            # but rehashing it cannot manufacture current completeness.
            validate_declaration_page(page["source"])
        changed["source_reference_scope"] = reference_scope(changed["source_sections"])
        changed["source_issues"] = []
        with self.assertRaises(ValueError):
            read_catalog_entries(changed)
        with self.assertRaises(ValueError):
            coverage_errors(changed)
        historical, _ = read_catalog_entries(
            changed, {r["structure_id"] for r in records}, historical_review=True
        )
        self.assertEqual(len(historical), 2)

    def test_qualified_raw_title_cannot_disappear_as_an_empty_native_family(self):
        document, _, _, frames = original_parallel_catalogues("native", titles=("", ""))
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError(
                    "A source contradiction must not acquire a model"
                ),
            ),
        ):
            page = document[0]
            layout = source_layout(page)
            hint = {
                "text": "Table A. Intermediates",
                "bbox": [30, 74, 150, 88],
                "x": 90,
                "y": 81,
                "confidence": 0.99,
                "source": "raster",
                "geometry_space": "rendered",
            }
            tokens = SourceTokens([hint, *layout.native], layout, layout.raster_bounds)
            scope = observe_caption_role(page, frames[0], frames, tokens)
            self.assertEqual(scope["observations"][0]["text"], hint["text"])
            self.assertEqual(scope["role"], "unresolved")

    def test_only_complete_native_empty_family_can_declare_no_title(self):
        for mode in ("native", "raster"):
            document, _, _, frames = original_parallel_catalogues(mode, titles=("", ""))
            with (
                self.subTest(mode=mode),
                document,
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=AssertionError(
                        "Empty-title geometry must not acquire OCR"
                    ),
                ),
            ):
                scopes = self.scopes(document, frames)
                expected = "unknown" if mode == "native" else "unresolved"
                self.assertEqual([scope["role"] for scope in scopes], [expected] * 2)
                if mode == "native":
                    scope = scopes[0]
                    self.assertEqual(
                        caption_role_status(scope, 1, scope["table_bbox"]), "unknown"
                    )
                    bad = copy.deepcopy(scope)
                    bad["sources"][0]["title_context"]["ink_source"]["ruling_sources"][
                        0
                    ]["pixels"] = None
                    self.assertNotEqual(
                        caption_role_status(bad, 1, bad["table_bbox"]), "unknown"
                    )

    def test_wrapped_native_catalogues_reuse_the_same_complete_declarations(self):
        document, structures, boxes, _ = wrapped_staggered_catalogues()
        payload, records = (
            caption_writer_controls.CaptionRoleWriterTests.execute_document(
                self, document, structures, boxes
            )
        )
        entries, _ = read_catalog_entries(payload, {r["structure_id"] for r in records})
        self.assertEqual(
            [row["cpd"] for row in entries], ["Compound 11A", "Compound 12A"]
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_saved_reader_computes_each_original_title_geometry_once(self):
        document, structures, boxes, _ = wrapped_staggered_catalogues()
        payload, records = (
            caption_writer_controls.CaptionRoleWriterTests.execute_document(
                self,
                document,
                structures,
                boxes,
            )
        )
        identities = {
            proof_id(
                {
                    "status": "original_title_geometry",
                    "source": parent["title_context"]["ink_source"],
                }
            )
            for section in payload["source_sections"]
            if section["role"] == "structure_declaration_page"
            for scope in section["source"]["catalogue_scopes"]
            for parent in scope["sources"]
            if parent["title_context"]["ink_source"] is not None
        }
        profiler = cProfile.Profile()
        with patch.object(
            title_ink_geometry,
            "_title_ink_rows",
            wraps=title_ink_geometry._title_ink_rows,
        ) as calculate:
            start = perf_counter()
            profiler.enable()
            try:
                entries, _ = read_catalog_entries(
                    payload, {r["structure_id"] for r in records}
                )
            finally:
                profiler.disable()
                elapsed = perf_counter() - start
            self.assertEqual(len(entries), 2)
            self.assertEqual(calculate.call_count, len(identities))
        print(
            json.dumps(
                {
                    "controlled_saved_reader_profile_seconds": elapsed,
                    "geometry_evaluations": calculate.call_count,
                    "original_inventories": len(identities),
                    "private_input_computed": False,
                }
            ),
            flush=True,
        )

    def test_actual_writer_and_saved_reader_reject_rehashed_prior_grid_omission(self):
        document, structures, boxes, frames = staggered_catalogues("native")
        prior_original_table(document, frames)
        payload, records = (
            caption_writer_controls.CaptionRoleWriterTests.execute_document(
                self,
                document,
                structures,
                boxes,
            )
        )
        entries, _ = read_catalog_entries(payload, {r["structure_id"] for r in records})
        self.assertEqual(
            [row["cpd"] for row in entries], ["Compound 11A", "Compound 12A"]
        )
        self.assertEqual(coverage_errors(payload), [])
        changed = copy.deepcopy(payload)
        page = next(
            s
            for s in changed["source_sections"]
            if s["role"] == "structure_declaration_page"
        )
        page["source"]["page_grids"] = [
            grid for grid in page["source"]["page_grids"] if grid["ys"][-1] > 61
        ]
        page["region_id"] = proof_id(page["source"])
        changed["source_reference_scope"] = reference_scope(changed["source_sections"])
        changed["source_issues"] = []
        with self.assertRaises(ValueError):
            read_catalog_entries(changed)
        # A malformed source is rejected before coverage can become a finding
        # list; it must never be converted into an accepted empty result.
        with self.assertRaises(ValueError):
            coverage_errors(changed)

    def test_nested_original_forms_do_not_misassign_later_ruling_paths(self):
        document, _, _, frames = staggered_catalogues("outlined")
        with document:
            prior_original_table(document, frames)
            page = document[0]
            view = native_paint_view(page)
            for order, (kind, box) in enumerate(view.paints):
                if kind != "stroke-path" or box[3] > 61:
                    continue
                path = view.paths[order]
                half = path["width"] / 2
                rect = path["rect"]
                self.assertEqual(
                    tuple(box),
                    (rect.x0 - half, rect.y0 - half, rect.x1 + half, rect.y1 + half),
                )
            drawings = page.get_drawings()
            target = next(
                path for path in drawings if list(path["rect"]) == [30, 20, 30, 60]
            )
            duplicated = [*drawings, {**target, "seqno": -1}]
            index = next(
                i
                for i, (kind, box) in enumerate(view.paints)
                if kind == "stroke-path" and tuple(box) == (29.5, 19.5, 30.5, 60.5)
            )
            self.assertNotIn(index, original_path_owners(view.paints, duplicated))
            repeated = [*view.paints, view.paints[index]]
            self.assertNotIn(index, original_path_owners(repeated, drawings))
            self.assertNotIn(
                len(repeated) - 1, original_path_owners(repeated, drawings)
            )

    def test_left_local_projection_keeps_the_complete_family_in_source_inventory(self):
        document, _, _, frames = staggered_catalogues("raster")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(),
            ),
        ):
            scope = self.scopes(document, frames, title_cache={})[0]
            self.assertEqual(scope["role"], "compound")
            payload = {
                "bindings": [
                    {"exact_caption_evidence": {"ownership": {"caption_role": scope}}}
                ]
            }
            cells = list(title_source_cells(payload))
            self.assertEqual(
                len([cell for _, cell in cells if cell["method"] == "original_title"]),
                2,
            )
            self.assertEqual(original_role_source_errors(document, cells), [])

    def test_prior_table_fence_is_retained_for_both_staggered_columns(self):
        document, _, _, frames = staggered_catalogues("native")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Complete native families must need no OCR"),
            ),
        ):
            grids = prior_original_table(document, frames)
            scopes = self.scopes(document, grids)
            self.assertEqual(
                [s["role"] for s in scopes], ["nonfinal", "compound", "nonfinal"]
            )

    def declaration_pages(self, document, frames):
        def tokens(page):
            layout = source_layout(page)
            return SourceTokens(layout.native, layout, layout.raster_bounds)

        sections, _ = observe_declaration_pages(
            document,
            [],
            [0],
            {0: document[0].get_text()},
            tokens,
            grids_for_page=lambda page: frames,
        )
        return sections

    def test_outlined_titles_keep_original_grid_page_without_word_nominations(self):
        document, _, _, frames = staggered_catalogues("outlined")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Grid inventory capture needs no OCR"),
            ),
        ):
            sections = self.declaration_pages(document, frames)
            self.assertEqual(len(sections), 1)
            self.assertEqual(sections[0]["source"]["page_grids"], frames)

    def test_page_grids_are_mandatory_unique_and_consistent_with_family(self):
        document, _, _, frames = staggered_catalogues("native")
        with document:
            scope = self.scopes(document, frames)[0]
            self.assertEqual(scope["page_grids"], frames)
            for fault in ("missing", "null", "subset", "duplicate", "foreign"):
                bad = copy.deepcopy(scope)
                if fault == "missing":
                    bad.pop("page_grids")
                elif fault == "null":
                    bad["page_grids"] = None
                elif fault == "subset":
                    bad["page_grids"].pop()
                elif fault == "duplicate":
                    bad["page_grids"].append(bad["page_grids"][0])
                else:
                    bad["page_grids"][1]["xs"][0] += 1
                with self.subTest(fault=fault):
                    self.assertIsNone(caption_role_status(bad, 1, bad["table_bbox"]))

    def test_earlier_source_is_preserved_in_native_outline_and_raster_families(self):
        for mode in ("native", "outlined", "raster"):
            document, _, _, frames = staggered_catalogues(mode)
            with (
                self.subTest(mode=mode),
                document,
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=AssertionError("Native family needs no reader")
                    if mode == "native"
                    else self.readers(),
                ) as reader,
            ):
                grids = prior_original_table(document, frames)
                scopes = self.scopes(document, grids, title_cache={})
                self.assertEqual(
                    [s["role"] for s in scopes], ["nonfinal", "compound", "nonfinal"]
                )
                self.assertEqual(reader.call_count, 0 if mode == "native" else 2)
                native = scopes[1]["sources"][0]["title_context"]["native_source"]
                self.assertIn("Table Z.", native["text"])
                payload = {
                    "bindings": [
                        {
                            "exact_caption_evidence": {
                                "ownership": {"caption_role": scopes[1]}
                            }
                        }
                    ]
                }
                self.assertEqual(
                    original_role_source_errors(document, title_source_cells(payload)),
                    [],
                )

    def test_unrelated_foreign_page_grid_cannot_pass_saved_declaration_replay(self):
        document, _, _, frames = staggered_catalogues("native")
        with document:
            # Outside this family's source window: pixel replay alone cannot
            # establish that an extra grid belongs to the complete original page.
            foreign = {"xs": [450, 480], "ys": [270, 280]}
            page = document[0]
            layout = source_layout(page)
            scope = observe_caption_role(
                page,
                frames[0],
                [*frames, foreign],
                SourceTokens(layout.native, layout, layout.raster_bounds),
            )
            self.assertEqual(scope["role"], "compound")
            sections = self.declaration_pages(document, frames)
            payload = {
                "bindings": [
                    {"exact_caption_evidence": {"ownership": {"caption_role": scope}}}
                ]
            }
            self.assertEqual(
                original_role_source_errors(document, title_source_cells(payload)), []
            )
            with self.assertRaisesRegex(ValueError, "complete page grid inventory"):
                validate_title_page_inventory(payload, sections)
            rejected = {
                "source_role_observations": {
                    "candidate": {
                        "kind": "binding_proposal",
                        "proposal": {"caption_role": scope},
                    }
                }
            }
            with self.assertRaisesRegex(ValueError, "complete page grid inventory"):
                declaration_issues(
                    sections,
                    reference_scope(sections),
                    [],
                    nonfinal_diagrams=set(),
                    title_payload=rejected,
                )

    def test_every_saved_owner_needs_the_same_complete_original_page(self):
        document, _, _, frames = staggered_catalogues("native")
        with document:
            scope = self.scopes(document, frames)[1]
            sections = self.declaration_pages(document, frames)
            caption = {"exact_caption_evidence": {"ownership": {"caption_role": scope}}}
            owners = {
                "final": {"bindings": [caption]},
                "additional": {"bindings": [{"additional_sources": [caption]}]},
                "excluded": {
                    "source_sections": [
                        {"role": "nonfinal_caption_catalog", "caption_role": scope}
                    ]
                },
                "rejected": {
                    "source_role_observations": {
                        "candidate": {
                            "kind": "binding_proposal",
                            "proposal": {"caption_role": scope},
                        }
                    }
                },
                "header": {
                    "source_sections": [
                        {
                            "role": "structure_column_anchor",
                            "source": {
                                "header_scope": {"context_sources": scope["sources"]}
                            },
                        }
                    ]
                },
            }
            for name, payload in owners.items():
                with self.subTest(owner=name):
                    validate_title_page_inventory(payload, sections)
                    with self.assertRaisesRegex(
                        ValueError, "complete page grid inventory"
                    ):
                        validate_title_page_inventory(payload, [])

    def scope(self, document, frames):
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=self.readers(),
        ):
            return self.scopes(document, frames, title_cache={})[1]

    def test_missing_or_changed_body_cell_cannot_authorize_a_saved_role(self):
        document, _, _, frames = staggered_catalogues("raster")
        with document:
            scope = self.scope(document, frames)
            self.assertEqual(scope["role"], "nonfinal")
            for fault in ("missing", "null", "axes", "pixels"):
                changed = json.loads(json.dumps(scope))
                for parent in changed["sources"]:
                    rows = parent["title_context"]["ink_source"]["ruling_sources"]
                    index = next(
                        i
                        for i, r in enumerate(rows)
                        if r["cell"][1] == frames[0]["ys"][1]
                    )
                    if fault == "missing":
                        rows.pop(index)
                    elif fault == "null":
                        rows[index]["pixels"] = None
                    elif fault == "axes":
                        rows[index]["cell"][0] += 1
                    else:
                        rows[index]["pixels"]["readings"][0]["pixel_sha256"] = "a" * 64
                with self.subTest(fault=fault):
                    self.assertIsNone(
                        caption_role_status(changed, 1, changed["table_bbox"])
                    )

    def test_original_body_pixels_are_replayed_without_a_new_reader(self):
        document, _, _, frames = staggered_catalogues("raster")
        with document:
            scope = self.scope(document, frames)
            cells = list(
                title_source_cells(
                    {
                        "source_sections": [
                            {"role": "nonfinal_caption_catalog", "caption_role": scope}
                        ]
                    }
                )
            )
            self.assertEqual(original_role_source_errors(document, cells), [])
            document[0].draw_rect(fitz.Rect(45, 114, 49, 118), fill=(0, 0, 0))
            with patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=AssertionError("Saved replay must not load OCR"),
            ):
                self.assertTrue(original_role_source_errors(document, cells))

    def test_crossing_body_ink_and_open_cells_refuse_before_ocr(self):
        for fault in ("crossing", "open"):
            document, _, _, frames = staggered_catalogues(
                "raster", open_right=fault == "open"
            )
            with (
                document,
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=AssertionError("Unproved body must refuse before OCR"),
                ),
            ):
                if fault == "crossing":
                    document[0].draw_line((260, 140), (410, 145))
                self.assertEqual(
                    [s["role"] for s in self.scopes(document, frames)],
                    ["unresolved"] * 2,
                )

    def test_weak_peer_attempt_is_conserved_across_both_staggered_members(self):
        readings = cycle(((TITLES[0], 0.99), (TITLES[1], 0.2)))
        document, _, _, frames = staggered_catalogues("raster")
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=lambda: ("rapidocr", title_reader(*next(readings))),
            ) as reader,
        ):
            self.assertEqual(
                [s["role"] for s in self.scopes(document, frames, title_cache={})],
                ["unresolved"] * 2,
            )
            self.assertEqual(reader.call_count, 2)

    def test_unowned_negative_source_cannot_be_discarded_as_neighbour_body(self):
        document, _, _, frames = staggered_catalogues(
            "raster", unowned="and intermediates"
        )
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                side_effect=self.readers(
                    (TITLES[0], "and intermediates Table B. Intermediates")
                ),
            ),
        ):
            self.assertEqual(
                [s["role"] for s in self.scopes(document, frames)], ["unresolved"] * 2
            )

    def test_qualified_raster_role_and_table_claims_remain_binding_constraints(self):
        document, _, _, frames = staggered_catalogues("raster")
        with document:
            page = document[0]
            layout = source_layout(page)
            for literal in ("Table A. Intermediates", "Table C. Compounds"):
                hint = {
                    "text": literal,
                    "bbox": [30, 74, 150, 88],
                    "x": 90,
                    "y": 81,
                    "confidence": 0.99,
                    "source": "raster",
                    "geometry_space": "rendered",
                }
                tokens = SourceTokens(
                    [hint, *layout.native], layout, layout.raster_bounds
                )
                with patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    side_effect=self.readers(),
                ):
                    scope = observe_caption_role(page, frames[0], frames, tokens)
                self.assertEqual(scope["role"], "unresolved")
                self.assertEqual(scope["observations"][0]["text"], literal)


if __name__ == "__main__":
    unittest.main()
