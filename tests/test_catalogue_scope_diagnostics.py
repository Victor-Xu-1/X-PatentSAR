"""Precise integrity errors must not change the catalogue acceptance gate."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core.structure_declaration_catalogues import (
    validate_catalogue_scopes,
)


def blank_frame():
    from patent_sar_extractor.core.activity_context_geometry import (
        context_floor,
        context_region,
    )
    from patent_sar_extractor.core.caption_role_titles import project_caption_titles
    from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
    from patent_sar_extractor.core.source_observations import source_cell_observation
    from patent_sar_extractor.core.source_table_roles import observed_role
    from patent_sar_extractor.core.title_context_grids import title_context_spec

    axes = {"xs": [10, 50], "ys": [20, 80]}
    box = [10, 20, 50, 80]
    geometry = context_region(axes, [box])["context_geometry"]
    window = [0, context_floor(geometry), 100, 20]
    tokens = SourceTokens([], SourceLayout((), None))
    raw = source_cell_observation(tokens, window, native=True)
    parent = {
        **raw,
        "title_context": {
            "version": 1,
            "page_no": 1,
            "page_size": [100, 100],
            "native_source": raw,
            "raster_bounds": None,
            "ink_source": None,
        },
        "original_titles": [],
    }
    observations = project_caption_titles([parent], geometry)
    role, key = observed_role(
        observations,
        contexts=[parent],
        context=title_context_spec(geometry=geometry, grid_axes=axes),
    )
    scope = {
        "version": 1,
        "page_no": 1,
        "table_bbox": box,
        "grid_axes": copy.deepcopy(axes),
        "context_geometry": geometry,
        "window": window,
        "observations": observations,
        "sources": [parent],
        "role": role,
        "table_key": key,
    }
    return axes, box, tokens, scope


class CatalogueScopeDiagnosticsTests(unittest.TestCase):
    def test_duplicate_catalogue_frame_preserves_original_inventory(self):
        from patent_sar_extractor.core.structure_declaration_catalogues import (
            catalogue_scopes_for_grids,
        )

        axes, box, _tokens, scope = blank_frame()
        inventory = [axes, copy.deepcopy(axes)]
        before = copy.deepcopy(inventory)
        scopes = catalogue_scopes_for_grids(1, inventory, {(1, tuple(box)): scope})
        source = {
            "page_no": 1,
            "page_size": [100, 100],
            "page_grids": inventory,
            "catalogue_scopes": scopes,
        }
        self.assertEqual(validate_catalogue_scopes(source), [scope])
        self.assertEqual(inventory, before)
        self.assertEqual(len(source["page_grids"]), 2)

        ambiguous = copy.deepcopy(inventory)
        ambiguous[1]["ys"].insert(1, 40)
        with self.assertRaisesRegex(ValueError, "conflicting original grid axes"):
            catalogue_scopes_for_grids(1, ambiguous, {(1, tuple(box)): scope})

        other = {"xs": [60, 90], "ys": [20, 80]}
        other_box = [60, 20, 90, 80]
        other_scope = {"table_bbox": other_box}
        roles = {(1, tuple(box)): scope, (1, tuple(other_box)): other_scope}
        self.assertEqual(
            catalogue_scopes_for_grids(1, [other, axes, other], roles),
            [other_scope, scope],
        )
        self.assertEqual(catalogue_scopes_for_grids(1, inventory, None), [])
        self.assertEqual(catalogue_scopes_for_grids(2, inventory, roles), [])

    def test_changed_producer_epoch_does_not_reuse_derived_stage_checkpoint(self):
        from patent_sar_extractor.application.stage_cache import (
            _fingerprint_matches,
            _step_fingerprint,
            _write_step_manifest,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "generated-input"
            source.write_bytes(b"synthetic input, not a patent")
            for stage, parameter in (
                ("bind", "structure_binder_version"),
                ("activity", "activity_extractor_version"),
            ):
                with self.subTest(stage=stage):
                    output = root / stage
                    output.write_text("synthetic checkpoint", encoding="utf-8")
                    old = _step_fingerprint(
                        stage, pdf_path=str(source), params={parameter: "old"}
                    )
                    new = _step_fingerprint(
                        stage, pdf_path=str(source), params={parameter: "new"}
                    )
                    _write_step_manifest(str(output), old)
                    self.assertTrue(_fingerprint_matches(str(output), old))
                    self.assertFalse(_fingerprint_matches(str(output), new))
                    self.assertEqual(output.read_text(), "synthetic checkpoint")

    def test_reference_categories_are_uncertain_but_reference_values_are_not(self):
        from patent_sar_extractor.core.caption_role_semantics import catalog_title_role

        for title in (
            "Table 47. Reference compounds",
            "Table 47. Control compounds",
            "Table 47. Comparator compounds",
            "Table 47. Comparative examples",
            "Table 47. Compounds and reference compounds",
            "Table 47. Positive controls",
            "Table 47. Compounds and negative controls",
            "Positive controls",
            "Compounds and negative controls",
            "Table 47. 参考化合物",
            "Table 47. 对照化合物",
            "Table 47. 比较例",
            "Table 47. 比較例",
            "Reference compounds",
            "Compounds and reference compounds",
            "参考化合物",
            "比较例",
            "比較例",
        ):
            with self.subTest(title=title):
                self.assertEqual(catalog_title_role(title), "conflict")
        self.assertEqual(
            catalog_title_role("Table 47. Compounds with reference values"),
            "compound",
        )
        self.assertEqual(catalog_title_role("比较数据"), "unknown")
        self.assertEqual(
            catalog_title_role("Table 47. Compounds with control values"),
            "compound",
        )

    def test_reference_declaration_nominates_source_page_for_review(self):
        from patent_sar_extractor.core.structure_declarations import (
            declaration_page_hint,
        )

        self.assertTrue(declaration_page_hint("Reference compounds"))

    def test_invalid_frame_error_does_not_echo_untrusted_geometry(self):
        axes = {"xs": [10, 50], "ys": [20, 80]}
        source = {
            "page_no": 1,
            "page_size": [100, 100],
            "page_grids": [axes],
            "catalogue_scopes": [{"table_bbox": [123456] * 10000}],
        }
        with self.assertRaisesRegex(ValueError, "invalid frame") as raised:
            validate_catalogue_scopes(source)
        self.assertLess(len(str(raised.exception)), 200)
        self.assertNotIn("123456", str(raised.exception))

    def test_real_legacy_cell_replay_preserves_duplicate_grid_inventory(self):
        import fitz

        from patent_sar_extractor.core.heading_cell_source import (
            observe_cell_source,
            valid_cell_geometry,
        )
        from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions

        with fitz.open() as document:
            page = document.new_page(width=100, height=100)
            page.draw_rect(fitz.Rect(10, 20, 80, 80), width=1)
            grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
            self.assertEqual(len(grids), 1)
            grid = grids[0]
            left, top = grid["xs"][0], grid["ys"][0]
            nomination = [left + 10, top + 10, left + 20, top + 20]
            repeated = [grid, copy.deepcopy(grid)]
            saved = observe_cell_source(page, nomination, repeated, 100)
            replay = observe_cell_source(page, nomination, repeated, 100)
            shortened = observe_cell_source(page, nomination, [grid], 100)
            self.assertIsNotNone(saved)
            self.assertTrue(valid_cell_geometry(saved, nomination, [100, 100], 100))
            self.assertEqual(len(saved["grid_inventory"]), 2)
            self.assertEqual(saved, replay)
            self.assertNotEqual(saved, shortened)

    def test_legacy_cell_source_preserves_complete_duplicate_inventory(self):
        from patent_sar_extractor.core.heading_cell_source import observe_cell_source

        axes, _box, _tokens, _scope = blank_frame()

        class Page:
            rect = type("Rect", (), {"width": 100, "height": 100})()

        observations = [axes, copy.deepcopy(axes)]
        with patch(
            "patent_sar_extractor.core.heading_cell_source.observe_closed_cell",
            return_value={"synthetic": "proof"},
        ):
            saved = observe_cell_source(Page(), [15, 25, 20, 30], observations, 100)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["grid_inventory"], observations)

    def test_blank_original_frame_stays_unresolved_and_cannot_be_forged(self):
        from patent_sar_extractor.core.caption_role_proof import caption_role_status

        axes, box, _tokens, scope = blank_frame()
        self.assertEqual(caption_role_status(scope, 1, box), "unresolved")
        source = {
            "page_no": 1,
            "page_size": [100, 100],
            "page_grids": [axes],
            "catalogue_scopes": [scope],
        }
        self.assertEqual(validate_catalogue_scopes(source), [scope])
        for field, value in (
            ("page_no", 2),
            ("role", "compound"),
            ("table_key", "FORGED"),
        ):
            bad = copy.deepcopy(scope)
            bad[field] = value
            with self.subTest(field=field):
                self.assertIsNone(caption_role_status(bad, 1, box))
                with self.assertRaisesRegex(ValueError, "unreplayable caption role"):
                    validate_catalogue_scopes({**source, "catalogue_scopes": [bad]})

    def test_rejects_each_inconsistent_original_frame_with_reason(self):
        axes = {"xs": [10, 50], "ys": [20, 80]}
        scope = {
            "table_bbox": [10, 20, 50, 80],
            "grid_axes": copy.deepcopy(axes),
            "window": [0, 0, 100, 20],
        }
        source = {
            "page_no": 1,
            "page_size": [100, 100],
            "page_grids": [axes],
            "catalogue_scopes": [scope],
        }
        with patch(
            "patent_sar_extractor.core.structure_declaration_catalogues.caption_role_status",
            return_value="unknown",
        ):
            self.assertEqual(validate_catalogue_scopes(source), [scope])
            for reason in (
                "duplicate frame",
                "grid axes mismatch",
                "window width mismatch",
            ):
                bad = copy.deepcopy(source)
                if reason == "duplicate frame":
                    bad["catalogue_scopes"].append(
                        copy.deepcopy(bad["catalogue_scopes"][0])
                    )
                elif reason == "grid axes mismatch":
                    bad["catalogue_scopes"][0]["grid_axes"]["ys"].insert(1, 40)
                else:
                    bad["catalogue_scopes"][0]["window"][2] = 99
                with (
                    self.subTest(reason=reason),
                    self.assertRaisesRegex(ValueError, reason),
                ):
                    validate_catalogue_scopes(bad)
        with (
            patch(
                "patent_sar_extractor.core.structure_declaration_catalogues.caption_role_status",
                return_value=None,
            ),
            self.assertRaisesRegex(ValueError, "unreplayable caption role"),
        ):
            validate_catalogue_scopes(source)


if __name__ == "__main__":
    unittest.main()
