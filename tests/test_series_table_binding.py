from __future__ import annotations

from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.series_table_binding import pair_series_table


class SeriesTableBindingTests(unittest.TestCase):
    def _table(self, numbers: list[int]):
        structures = []
        lines = []
        for index, number in enumerate(numbers):
            y0 = 100.0 + index * 120
            structures.append(
                {
                    "id": f"S{index:04d}",
                    "idx": index,
                    "page_no": 10,
                    "x0": 150.0,
                    "x1": 360.0,
                    "y0": y0,
                    "y1": y0 + 100,
                    "image_path": f"/tmp/s{index:04d}.png",
                }
            )
            lines.append((y0 + 50, f"I-{number}"))
        return structures, {9: lines}

    def _pair(self, structures, lines, active=range(1, 11)):
        return pair_series_table(
            structures, [9], lines, {str(number) for number in active}
        )

    def test_spatially_separate_duplicate_is_corrected_with_source_evidence(self):
        structures, lines = self._table([1, 2, 9, 4, 7, 8, 9, 10])
        original = deepcopy((structures, lines))
        result = self._pair(structures, lines)
        self.assertEqual(
            [pair.label for pair in result.bindings], [1, 2, 3, 4, 7, 8, 9, 10]
        )
        corrected = result.bindings[2]
        self.assertEqual(corrected.source_label, 9)
        self.assertEqual(corrected.structure["id"], "S0002")
        self.assertIn("duplicated and out of sequence", corrected.correction_reason)
        self.assertEqual(
            (structures, lines), original, "Input evidence must remain immutable"
        )

    def test_same_position_ocr_duplicate_is_not_a_second_printed_row(self):
        structures, lines = self._table([1, 2, 3, 4, 5, 6])
        lines[9].extend([(150.0, "1-1"), (151.5, "l-1")])
        result = self._pair(structures, lines)
        self.assertEqual(result.label_count, 6)
        self.assertEqual([pair.label for pair in result.bindings], list(range(1, 7)))
        self.assertTrue(all(not pair.correction_reason for pair in result.bindings))

    def test_missing_id_outside_activity_set_is_not_invented(self):
        structures, lines = self._table([1, 2, 9, 4, 7, 8, 9, 10])
        result = self._pair(structures, lines, active=[1, 2, 4, 7, 8, 9, 10])
        self.assertEqual([pair.label for pair in result.bindings], [1, 2, 4, 7, 8, 10])

    def test_gap_id_already_printed_elsewhere_is_not_reassigned(self):
        structures, lines = self._table([1, 2, 9, 4, 7, 8, 9, 10, 3])
        result = self._pair(structures[:-1], lines)
        self.assertEqual([pair.label for pair in result.bindings], [1, 2, 4, 7, 8, 10])
        self.assertTrue(all(not pair.correction_reason for pair in result.bindings))

    def test_duplicated_anchor_cannot_prove_a_correction(self):
        structures, lines = self._table([1, 2, 9, 4, 7, 8, 9, 10, 2])
        result = self._pair(structures, lines)
        self.assertNotIn(3, [pair.label for pair in result.bindings])
        self.assertNotIn(2, [pair.label for pair in result.bindings])
        self.assertNotIn(9, [pair.label for pair in result.bindings])

    def test_unsegmented_duplicate_remains_competing_evidence(self):
        structures, lines = self._table([1, 2, 3, 4, 5, 6, 3])
        result = self._pair(structures[:-1], lines)
        self.assertEqual([pair.label for pair in result.bindings], [1, 2, 4, 5, 6])

    def test_missing_segment_does_not_shift_later_rows(self):
        structures, lines = self._table([1, 2, 3, 4, 5, 6])
        result = self._pair([structures[0], structures[2]], lines)
        self.assertEqual(
            [(pair.label, pair.structure["id"]) for pair in result.bindings],
            [(1, "S0000"), (3, "S0002")],
        )

    def test_equal_distance_structures_are_withheld_not_tie_broken(self):
        structures, lines = self._table([1, 2, 3, 4, 5, 6])
        rival = {**structures[0], "id": "RIVAL", "x0": 400.0, "x1": 500.0}
        result = self._pair([*structures, rival], lines)
        self.assertEqual([pair.label for pair in result.bindings], [2, 3, 4, 5, 6])
        self.assertGreater(result.ambiguous_pairings, 0)

    def test_equal_distance_labels_are_withheld_not_tie_broken(self):
        structures, lines = self._table([1, 2, 3, 4, 5, 6])
        lines[9][1] = (150.0, "I-2")
        result = self._pair(structures, lines)
        self.assertEqual([pair.label for pair in result.bindings], [3, 4, 5, 6])
        self.assertGreater(result.ambiguous_pairings, 0)

    def test_invalid_geometry_is_rejected_without_unsafe_fallback(self):
        for changes in (
            {"y0": float("nan")},
            {"x1": float("inf")},
            {"y1": 50},
            {"x1": None},
        ):
            with self.subTest(changes=changes):
                structures, lines = self._table([1, 2, 3, 4, 5, 6])
                structures[0].update(changes)
                result = self._pair(structures, lines)
                self.assertEqual(result.rejected_geometry, 1)
                self.assertEqual(
                    [pair.label for pair in result.bindings], [2, 3, 4, 5, 6]
                )

    def test_nonfinite_ocr_coordinates_cannot_add_table_evidence(self):
        structures, lines = self._table([1, 2, 3, 4, 5, 6])
        lines[9].extend([(float("nan"), "I-99"), (float("inf"), "I-98"), (-1, "I-97")])
        result = self._pair(structures, lines)
        self.assertEqual(result.label_count, 6)
        self.assertEqual(len(result.bindings), 6)

    def test_small_non_table_series_does_not_activate_table_rule(self):
        structures, lines = self._table([1, 2, 3])
        result = self._pair(structures, lines)
        self.assertFalse(result.recognized)
        self.assertEqual(result.bindings, ())

    def test_discontinuous_table_pages_still_use_independent_geometry(self):
        from patent_sar_extractor.core.structure_binder import (
            _extract_authoritative_structure_table_sequence_bindings,
        )

        structures, lines = self._table([1, 2, 3, 4, 5, 6])
        for structure in structures[3:]:
            structure["page_no"] = 12
        split_lines = {9: lines[9][:3], 11: lines[9][3:]}
        bindings = _extract_authoritative_structure_table_sequence_bindings(
            structures,
            {},
            [f"Compound {number}" for number in range(1, 7)],
            {"authoritative_structure_table_pages": [9, 11]},
            ocr_line_map=split_lines,
        )
        self.assertEqual(
            [row["cpd"] for row in bindings],
            [f"Compound {number}" for number in range(1, 7)],
        )

    def test_correction_cannot_bridge_a_missing_table_page(self):
        structures, lines = self._table([1, 2, 9, 4, 7, 8, 9, 10])
        for structure in structures[3:]:
            structure["page_no"] = 12
        result = pair_series_table(
            structures,
            [9, 11],
            {9: lines[9][:3], 11: lines[9][3:]},
            {str(number) for number in range(1, 11)},
        )
        self.assertEqual([pair.label for pair in result.bindings], [1, 2, 4, 7, 8, 10])

    def test_unique_correction_can_cross_an_observed_adjacent_page_boundary(self):
        structures, lines = self._table([1, 2, 9, 4, 7, 8, 9, 10])
        for structure in structures[3:]:
            structure["page_no"] = 11
        result = pair_series_table(
            structures,
            [9, 10],
            {9: lines[9][:3], 10: lines[9][3:]},
            {str(number) for number in range(1, 11)},
        )
        self.assertEqual(
            [pair.label for pair in result.bindings], [1, 2, 3, 4, 7, 8, 9, 10]
        )

    def test_recognized_ambiguous_series_cannot_fall_back_to_numeric_zip(self):
        from patent_sar_extractor.core.structure_binder import (
            _extract_authoritative_structure_table_sequence_bindings,
        )

        structures, lines = self._table([1, 2, 3, 4, 5, 6])
        for structure in structures:
            structure.update(y0=100.0, y1=200.0)
        bindings = _extract_authoritative_structure_table_sequence_bindings(
            structures,
            {9: "\n".join(f"Compound {number}" for number in range(1, 7))},
            [f"Compound {number}" for number in range(1, 7)],
            {"authoritative_structure_table_pages": [9]},
            ocr_line_map=lines,
        )
        self.assertEqual(bindings, [])

    def test_previous_ruleset_binding_cache_is_not_reused(self):
        from patent_sar_extractor.application.commands import (
            _fingerprint_matches,
            _step_fingerprint,
            _write_step_manifest,
        )
        from patent_sar_extractor.contracts import ruleset_ref

        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "input.pdf"
            pdf.write_bytes(b"cache-identity-only")
            artifact = Path(directory) / "bindings.json"
            artifact.write_text("{}", encoding="utf-8")
            current = _step_fingerprint("bind", pdf_path=str(pdf))
            previous = {**current, "ruleset": {**ruleset_ref(), "version": "2.0.0"}}
            _write_step_manifest(str(artifact), previous)
            self.assertFalse(_fingerprint_matches(str(artifact), current))
            _write_step_manifest(str(artifact), current)
            self.assertTrue(_fingerprint_matches(str(artifact), current))

    def test_classification_cache_manifest_requires_current_identity(self):
        from patent_sar_extractor.application.commands import (
            _fingerprint_matches,
            _step_fingerprint,
            _write_step_manifest,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "input.pdf"
            pdf.write_bytes(b"cache-identity-only")
            artifact = root / "classification.json"
            artifact.write_text("{}", encoding="utf-8")
            current = _step_fingerprint("classify", pdf_path=str(pdf))
            _write_step_manifest(str(artifact), current)
            manifest_path = Path(str(artifact) + ".manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["ruleset"]["version"] = "2.0.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertFalse(_fingerprint_matches(str(artifact), current))
            _write_step_manifest(str(artifact), current)
            self.assertTrue(_fingerprint_matches(str(artifact), current))


if __name__ == "__main__":
    unittest.main()
