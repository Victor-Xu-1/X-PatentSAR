"""Unknown transposed columns remain original evidence, never inferred entities."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_coverage import source_record
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_transposed import read_activity_cell
from patent_sar_extractor.core.activity_transposed_source import (
    capture_transposed_layout,
)
from patent_sar_extractor.core.source_cell_tokens import cell_tokens, grid_token_index
from patent_sar_extractor.core.source_geometry import (
    SourceLayout,
    SourceTokens,
    native_region,
)
from patent_sar_extractor.core.source_observations import source_cell_observation
from tests.test_activity_transposed import transposed


class ActivityColumnInventoryTests(unittest.TestCase):
    def test_grid_index_preserves_half_open_native_raster_and_boundary_observations(
        self,
    ):
        def token(text, x, y, *, native=False):
            return {
                "text": text,
                "x": x,
                "y": y,
                "bbox": [x - 1, y - 1, x + 1, y + 1],
                "confidence": 1.0 if native else 0.92,
                "source": "native" if native else "raster",
                "geometry_space": "rendered",
            }

        native = [
            token("native", 0, 0, native=True),
            token("shadow", 10, 10, native=True),
        ]
        raster = [
            token("raster", 10, 10),
            token("last", 20, 20),
            token("outside", 30, 30),
        ]
        tokens = SourceTokens(
            native + raster, SourceLayout(tuple(native), None), (9, 9, 30, 30)
        )
        region = {"xs": [0, 10, 20, 30], "ys": [0, 10, 20, 30]}
        indexed = grid_token_index(tokens, region["xs"], region["ys"])
        with patch(
            "patent_sar_extractor.core.activity_transposed_source.source_cell_observation",
            wraps=source_cell_observation,
        ) as observer:
            captured = capture_transposed_layout(tokens, region, 0, native=True)
        self.assertEqual(observer.call_count, 9)
        self.assertTrue(all(len(call.args[0]) <= 2 for call in observer.call_args_list))
        for row in range(3):
            for column in range(3):
                bounds = [column * 10, row * 10, (column + 1) * 10, (row + 1) * 10]
                self.assertEqual(
                    indexed.get((row, column), []), cell_tokens(tokens, bounds)
                )
                self.assertEqual(
                    captured["columns"][column][row],
                    source_cell_observation(
                        tokens,
                        bounds,
                        native=native_region(tokens, bounds, True),
                    ),
                )

    def test_original_cell_capture_is_bounded_before_allocating_snapshots(self):
        tokens = SourceTokens([], SourceLayout((), None))
        with self.assertRaisesRegex(ValueError, "cell inventory exceeds"):
            capture_transposed_layout(
                tokens, {"xs": list(range(501)), "ys": list(range(52))}, 0, native=True
            )
        with self.assertRaisesRegex(ValueError, "token inventory exceeds"):
            grid_token_index([{}] * 50001, [0, 1], [0, 1])
        with self.assertRaisesRegex(TypeError, "original transposed cell observation"):
            capture_transposed_layout([], {"xs": [0, 1], "ys": [0, 1]}, 0, native=True)

    def artifact(self, *, headers=None, raster=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original.pdf"
            with fitz.open() as doc, fitz.open() as image_doc:
                transposed(
                    doc.new_page(),
                    headers
                    or ["Compound 17", "comparison-X", "Compound 17", "comparison-X"],
                )
                if raster:
                    pixels = doc[0].get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
                    page = image_doc.new_page()
                    page.insert_image(page.rect, stream=pixels.tobytes("png"))
                    image_doc.save(original)
                else:
                    doc.save(original)
            result = extract(str(original), {"activity_pages": [0]}, str(root / "out"))
            payload = load_json(root / "out/activity_data.json", None)
        return result, payload

    def test_full_native_facade_retains_unresolved_columns_without_crashing(self):
        result, payload = self.artifact()
        # The existing facade merges disjoint assay fields, retaining two sources.
        self.assertEqual(result["n_rows"], 1)
        self.assertEqual([row["cpd"] for row in payload["rows"]], ["Compound 17"])
        self.assertEqual(len(payload["rows"][0]["activity_sources"]), 2)
        unresolved = [
            region
            for region in payload["coverage"]["regions"]
            if region["status"] == "unresolved"
        ]
        self.assertEqual(len(unresolved), 2)
        self.assertTrue(
            all(region["header"] == "comparison-X" for region in unresolved)
        )
        errors = activity_evidence_errors(payload, [0])
        self.assertEqual(sum("Unresolved activity source" in e for e in errors), 2)
        self.assertFalse(any("transposed column population" in e for e in errors))
        root = next(
            r for r in payload["coverage"]["regions"] if "transposed_layout" in r
        )
        columns = root["transposed_layout"]["columns"]
        self.assertEqual(
            [[p["text"] for p in columns[i][1:]] for i in (2, 4)],
            [
                ["comparison-X", "300", "90"],
                ["comparison-X", "600", "95"],
            ],
        )
        self.assertTrue(
            all(
                cell["origin"] == "native"
                for c in columns
                for cell in c
                if cell["text"]
            )
        )

    def test_complete_columns_and_controls_pass_the_same_facade_and_saved_proof(self):
        _, payload = self.artifact(
            headers=["Compound 17", "Ref. 1", "Compound 17", "Ref. 1"]
        )
        self.assertEqual(activity_evidence_errors(payload, [0]), [])

    def test_generated_raster_facade_retains_original_unknown_column_cells(self):
        result, payload = self.artifact(raster=True)
        self.assertTrue(result["rows"])
        root = next(
            r for r in payload["coverage"]["regions"] if "transposed_layout" in r
        )
        children = [r for r in payload["coverage"]["regions"] if "column_scope" in r]
        self.assertEqual(len(children), 2)
        self.assertTrue(all("comparison" in r["header"].casefold() for r in children))
        columns = root["transposed_layout"]["columns"]
        header = root["transposed_layout"]["header_row"]
        for child in children:
            cells = columns[child["column_scope"]["column"]][header:]
            self.assertTrue(all(c["origin"] == "raster" for c in cells))
            self.assertTrue(all(c["tokens"] and c["bbox"] for c in cells))
        errors = activity_evidence_errors(payload, [0])
        self.assertEqual(sum("Unresolved activity source" in e for e in errors), 2)
        self.assertFalse(any("transposed column population" in e for e in errors))

    def test_numeric_dose_columns_remain_unknown_beside_a_literal_compound(self):
        _, payload = self.artifact(headers=["Compound 17", "10", "Compound 18", "100"])
        self.assertEqual(
            {row["cpd"] for row in payload["rows"]}, {"Compound 17", "Compound 18"}
        )
        unknown = [
            r["header"] for r in payload["coverage"]["regions"] if "column_scope" in r
        ]
        self.assertEqual(unknown, ["10", "100"])
        self.assertEqual(
            sum(
                "Unresolved activity source" in e
                for e in activity_evidence_errors(payload, [0])
            ),
            2,
        )

    def test_deleting_unknown_columns_or_current_layout_cannot_clear_review(self):
        _, original = self.artifact()
        changed = copy.deepcopy(original)
        changed["coverage"]["regions"] = [
            r for r in changed["coverage"]["regions"] if "column_scope" not in r
        ]
        self.assertTrue(
            any(
                "transposed column population" in e
                for e in activity_evidence_errors(changed, [0])
            )
        )
        changed = copy.deepcopy(original)
        root = next(
            r for r in changed["coverage"]["regions"] if "transposed_layout" in r
        )
        del root["transposed_layout"]
        self.reidentify(root)
        with self.assertRaisesRegex(ValueError, "unique physical source"):
            activity_evidence_errors(changed, [0])

    @staticmethod
    def reidentify(region):
        base = (
            "page_no",
            "kind",
            "bbox",
            "table_id",
            "header",
            "status",
            "reason",
            "row_count",
        )
        replacement = source_record(
            *[region[k] for k in base],
            **{k: v for k, v in region.items() if k not in {*base, "region_id"}},
        )
        region.clear()
        region.update(replacement)

    def test_rehashed_foreign_or_nonadjacent_column_geometry_is_rejected(self):
        _, original = self.artifact()
        for mutation in (
            "foreign_parent",
            "foreign_page",
            "wide_column",
            "wrong_index",
            "wrong_table",
        ):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(original)
                child = next(
                    r for r in changed["coverage"]["regions"] if "column_scope" in r
                )
                if mutation == "foreign_parent":
                    child["column_scope"]["parent_grid"][0] += 1
                elif mutation == "foreign_page":
                    child["page_no"] = 2
                elif mutation == "wide_column":
                    child["bbox"][2] += 100
                elif mutation == "wrong_index":
                    child["column_scope"]["column"] += 1
                else:
                    child["table_id"] = "Table 32"
                self.reidentify(child)
                with self.assertRaisesRegex(ValueError, "original column"):
                    activity_evidence_errors(changed, [0])

    def test_a_whole_column_cannot_masquerade_as_the_existing_row_scope(self):
        _, changed = self.artifact()
        child = next(r for r in changed["coverage"]["regions"] if "column_scope" in r)
        child["parent_grid"] = child.pop("column_scope")["parent_grid"]
        child["reason"] = "no_original_rows"
        self.reidentify(child)
        with self.assertRaisesRegex(ValueError, "original row.*exact physical parent"):
            activity_evidence_errors(changed, [0])

    def test_removed_or_reassigned_resolved_source_is_not_a_complete_population(self):
        _, original = self.artifact(
            headers=["Compound 17", "Ref. 1", "Compound 17", "Ref. 1"]
        )
        for mutation in ("removed", "reassigned", "missing_orientation"):
            changed = copy.deepcopy(original)
            sources = changed["rows"][0]["activity_sources"]
            if mutation == "removed":
                sources.pop()
            elif mutation == "reassigned":
                sources[0]["pair"] = 4
            else:
                sources[0].pop("orientation")
            with self.subTest(mutation=mutation):
                errors = activity_evidence_errors(changed, [0])
                self.assertTrue(
                    any(
                        "population" in e or "owned physical region" in e
                        for e in errors
                    )
                )

    def test_changed_values_cannot_outvote_the_separate_original_cell_inventory(self):
        _, payload = self.artifact(
            headers=["Compound 17", "Ref. 1", "Compound 17", "Ref. 1"]
        )
        row = payload["rows"][0]
        cell = row["activity_sources"][0]["cells"][1]
        row["activity_values"][cell["field"]] = cell["value"] = "999"
        cell["observations"] = [{"method": "native_cell", "text": "999"}]
        self.assertTrue(
            any(
                "transposed column population" in e
                for e in activity_evidence_errors(payload, [0])
            )
        )

    def test_malformed_column_types_and_missing_original_cells_are_rejected(self):
        _, original = self.artifact()
        for field, value in (
            ("column", True),
            ("column", 0),
            ("header_row", True),
            ("header_row", 3),
        ):
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(original)
                child = next(
                    r for r in payload["coverage"]["regions"] if "column_scope" in r
                )
                child["column_scope"][field] = value
                with self.assertRaisesRegex(ValueError, "column scope"):
                    self.reidentify(child)
        payload = copy.deepcopy(original)
        root = next(
            r for r in payload["coverage"]["regions"] if "transposed_layout" in r
        )
        root["transposed_layout"]["columns"][2].pop()
        with self.assertRaisesRegex(ValueError, "Incomplete original transposed"):
            self.reidentify(root)
        payload = copy.deepcopy(original)
        payload["rows"][0]["source"] = None
        with self.assertRaisesRegex(TypeError, "transposed row source"):
            activity_evidence_errors(payload, [0])

    def test_historical_derived_versions_are_not_retagged_as_current(self):
        _, original = self.artifact()
        for field in ("schema", "coverage"):
            payload = copy.deepcopy(original)
            schema = (
                payload["schema"]
                if field == "schema"
                else payload["coverage"]["schema"]
            )
            schema["version"] -= 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                activity_evidence_errors(payload, [0])

    def test_unread_declared_headers_and_values_survive_even_without_any_rows(self):
        def unread(*args, **kwargs):
            value, observations, review = read_activity_cell(*args, **kwargs)
            return (
                ("", observations, True)
                if kwargs["identifier"]
                else (value, observations, review)
            )

        with patch(
            "patent_sar_extractor.core.activity_transposed.read_activity_cell",
            side_effect=unread,
        ):
            result, payload = self.artifact()
        self.assertEqual(result["n_rows"], 0)
        root = next(
            r for r in payload["coverage"]["regions"] if "transposed_layout" in r
        )
        self.assertEqual(root["status"], "unresolved")
        self.assertEqual(len(root["transposed_layout"]["columns"]), 5)
        children = [r for r in payload["coverage"]["regions"] if "column_scope" in r]
        self.assertEqual(len(children), 4)
        self.assertEqual(sum(r["reason"] == "no_original_rows" for r in children), 2)
        errors = activity_evidence_errors(payload, [0])
        self.assertTrue(any("No activity rows" in e for e in errors))
        self.assertFalse(any("transposed column population" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
