"""Real token/provenance SDK controls, without rendering or an OCR/model stub."""

import copy
import unittest

from patent_sar_extractor.core.source_body_context import (
    contained_source_diagrams,
    original_context_extent,
)
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.core.source_window_chunks import observe_source_window

WINDOW = [0, 80, 520, 720]
DIAGRAMS = [
    {"id": "BEFORE", "bbox": [215, 110, 355, 180]},
    {"id": "AFTER", "bbox": [215, 470, 355, 550]},
]


def token(text, top, *, x=40, confidence=0.99, native=False, width=190):
    return {
        "text": text,
        "bbox": [x, top, x + width, top + 12],
        "x": x + width / 2,
        "y": top + 6,
        "confidence": 1.0 if native else confidence,
        "source": "native" if native else "raster",
        "geometry_space": "rendered",
    }


def context(primary, native=(), *, window=WINDOW):
    source = SourceTokens(
        primary,
        SourceLayout(tuple(native), (0, 0, 520, 720)),
        scan_bounds=(0, 0, 520, 720),
    )
    return observe_source_window(source, window)


class SourceBodyContextTests(unittest.TestCase):
    def test_one_native_packet_lane_is_not_an_independent_second_observation(self):
        words = [token("Compound B80: Preparation", 430, native=True)]
        source = SourceTokens(words, SourceLayout(tuple(words), None))
        packets = observe_source_window(source, WINDOW)
        self.assertTrue(all(len(chunk["sources"]) == 1 for chunk in packets))
        extent = original_context_extent(packets, WINDOW, DIAGRAMS)
        self.assertEqual(extent["body_bottom"], 430)
        self.assertEqual(extent["unproved_boundaries"], [])

    def test_a_closed_original_frame_does_not_claim_an_independent_page_diagram(self):
        self.assertEqual(
            contained_source_diagrams(DIAGRAMS, [40, 100, 380, 330]),
            [DIAGRAMS[0]],
        )

    def test_crossing_observed_diagrams_cannot_be_silently_clipped_into_a_frame(self):
        self.assertEqual(
            contained_source_diagrams(DIAGRAMS, [240, 100, 380, 330]),
            [],
        )

    def extent(self, primary, native=(), **options):
        packets = context(primary, native)
        before = copy.deepcopy(packets)
        result = original_context_extent(packets, WINDOW, DIAGRAMS, **options)
        self.assertEqual(packets, before)
        return result

    def test_qualified_procedure_ends_both_inventory_and_trusted_ownership(self):
        result = self.extent([token("Compound B80: Preparation", 430)])
        self.assertEqual(result["body_bottom"], 430)
        self.assertEqual(result["trusted_bottom"], 430)
        self.assertEqual(result["unproved_boundaries"], [])

    def test_weak_procedure_keeps_all_facts_but_cannot_extend_nonfinal_ownership(self):
        result = self.extent([token("Compound B80: Preparation", 430, confidence=0.40)])
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 430)
        self.assertEqual(len(result["unproved_boundaries"]), 1)

    def test_known_original_lane_disagreement_is_not_a_proved_boundary(self):
        result = self.extent(
            [token("Compound B80: Preparation", 430)],
            [token("Compound B81: Preparation", 430, native=True)],
        )
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 430)
        self.assertEqual(len(result["unproved_boundaries"]), 2)

    def test_native_only_boundary_cannot_disappear_behind_an_empty_raster_lane(self):
        result = self.extent([], [token("Compound B80: Preparation", 430, native=True)])
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 430)
        self.assertEqual(len(result["unproved_boundaries"]), 1)

    def test_independently_agreeing_native_and_raster_facts_share_one_boundary(self):
        result = self.extent(
            [token("Compound B80: Preparation", 430)],
            [token("Compound B80: Preparation", 430, native=True)],
        )
        self.assertEqual(result["body_bottom"], 430)
        self.assertEqual(result["unproved_boundaries"], [])

    def test_plain_labels_and_prose_references_are_not_new_sections(self):
        for text in ("Compound B80", "See Table 13. Continued", "19"):
            with self.subTest(text=text):
                result = self.extent([token(text, 430)])
                self.assertEqual(result["trusted_bottom"], 720)
                self.assertEqual(result["unproved_boundaries"], [])

    def test_uncertainty_before_a_later_proved_boundary_is_not_waived(self):
        result = self.extent(
            [
                token("Compound B80: Preparation", 350, confidence=0.40),
                token("Table 13. Compounds", 600),
            ]
        )
        self.assertEqual(result["body_bottom"], 600)
        self.assertEqual(result["trusted_bottom"], 350)
        self.assertEqual(len(result["unproved_boundaries"]), 1)

    def test_suspect_text_after_a_proved_end_does_not_change_the_prior_scope(self):
        result = self.extent(
            [
                token("Table 13. Compounds", 300),
                token("Compound B80: Preparation", 600, confidence=0.40),
            ]
        )
        self.assertEqual(result["body_bottom"], 300)
        self.assertEqual(result["trusted_bottom"], 300)
        self.assertEqual(result["unproved_boundaries"], [])

    def test_a_boundary_overlapping_a_diagram_cannot_trim_the_known_population(self):
        result = self.extent([token("Compound B80: Preparation", 480)])
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 480)
        self.assertEqual(len(result["unproved_boundaries"]), 1)

    def test_neighbouring_baseline_cannot_hide_an_original_procedure_boundary(self):
        result = self.extent(
            [
                token("Compound B80: Preparation", 480),
                token("28", 487, x=60, width=14),
            ]
        )
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 480)
        self.assertTrue(result["unproved_boundaries"])

    def test_a_nominated_baseline_subset_cannot_waive_a_complete_native_conflict(self):
        result = self.extent(
            [token("Compound B80: Preparation", 430), token("28", 437, x=60, width=14)],
            [token("Table 13. Compounds", 430, native=True)],
        )
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 430)
        self.assertTrue(result["unproved_boundaries"])

    def test_a_table_reference_inside_a_drawing_does_not_become_a_page_boundary(self):
        result = self.extent([token("Table 22", 480, x=240, width=50)])
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 720)
        self.assertEqual(result["unproved_boundaries"], [])

    def test_a_table_title_crossing_a_drawing_edge_retains_boundary_uncertainty(self):
        result = self.extent([token("Table 22. Compounds", 480, x=40, width=300)])
        self.assertEqual(result["body_bottom"], 720)
        self.assertEqual(result["trusted_bottom"], 480)
        self.assertEqual(len(result["unproved_boundaries"]), 1)

    def test_actual_column_headers_share_the_existing_four_point_boundary(self):
        words = [
            token("Compound No.", 300, x=40, width=90),
            token("Structure", 300, x=240, width=70),
        ]
        result = self.extent(words)
        self.assertEqual(result["body_bottom"], 296)
        self.assertEqual(result["trusted_bottom"], 296)
        declaration = self.extent(words, column_boundaries=False)
        self.assertEqual(declaration["body_bottom"], 720)

    def test_editing_a_saved_qualification_flag_cannot_create_a_trusted_end(self):
        packets = context([token("Compound B80: Preparation", 430, confidence=0.40)])
        packets[0]["sources"][0]["status"] = "qualified"
        with self.assertRaises(ValueError):
            original_context_extent(packets, WINDOW, DIAGRAMS)
